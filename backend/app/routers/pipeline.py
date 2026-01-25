"""
Document Pipeline Router - 文档处理流水线

4 阶段流水线:
1. OCR层: 百度OCR / GPT-4o Vision
2. LLM1分析层: 提取实体、标签、引用
3. LLM2关系层: 分析实体关系、证据链
4. LLM3撰写层: 生成带引用的段落
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form, BackgroundTasks, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, AsyncGenerator
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import asyncio
import httpx
import json
import base64
import uuid

from app.core.config import settings
from app.db.database import get_db, SessionLocal
from app.models.document import Document, DocumentAnalysis, OCRStatus, TextBlock
from app.services import storage
from app.services import deepseek_ocr
from app.services import bbox_matcher
from app.services import page_cache
from app.services.ocr_queue import ocr_queue
from app.services.storage import (
    save_style_template, get_style_templates, get_style_template,
    delete_style_template, update_style_template
)
from app.services.l1_analyzer import get_l1_analysis_prompt, parse_analysis_result, L1_STANDARDS, clean_ocr_for_llm
from app.services.quote_merger import merge_chunk_analyses, generate_summary, prepare_for_writing, format_citation
from app.services.model_preloader import get_preload_state

router = APIRouter(prefix="/api", tags=["pipeline"])

# ============== 配置 ==============

OPENAI_API_KEY = settings.openai_api_key
OPENAI_API_BASE = settings.openai_api_base
BAIDU_OCR_API_KEY = settings.baidu_ocr_api_key
BAIDU_OCR_SECRET_KEY = settings.baidu_ocr_secret_key
OCR_PROVIDER = settings.ocr_provider
LLM_PROVIDER = settings.llm_provider
LLM_MODEL = settings.llm_model
LLM_API_BASE = settings.llm_api_base  # 本地模型 API 地址

# 百度 access_token 缓存
_baidu_access_token: str = ""
_baidu_token_expires: Optional[datetime] = None

# PDF 处理
try:
    import fitz  # PyMuPDF
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False


# L1 分析进度追踪（内存中）
# 结构: { project_id: { status, total, completed, current_doc, errors, results } }
_l1_analysis_progress: Dict[str, Dict[str, Any]] = {}

# 关系分析进度追踪（内存中）
# 结构: { project_id: { status, result, error } }
_relationship_progress: Dict[str, Dict[str, Any]] = {}


# ============== 数据模型 ==============

class DocumentResponse(BaseModel):
    id: str
    project_id: str
    file_name: str
    file_type: str
    file_size: Optional[int]
    page_count: int
    ocr_text: Optional[str]
    ocr_status: str
    exhibit_number: Optional[str]
    exhibit_title: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AnalysisResult(BaseModel):
    document_type: str
    document_date: Optional[str]
    entities: List[Dict[str, Any]]
    tags: List[str]
    key_quotes: List[Dict[str, Any]]
    summary: str


class RelationshipGraph(BaseModel):
    entities: List[Dict[str, Any]]
    relations: List[Dict[str, Any]]
    evidence_chains: List[Dict[str, Any]]


class GeneratedParagraph(BaseModel):
    text: str
    citations: List[Dict[str, str]]
    section_type: str


# ============== Stage 1: OCR ==============

def pdf_to_images(pdf_bytes: bytes, max_pages: int = 20, dpi: int = 200) -> List[bytes]:
    """将 PDF 转换为图片列表"""
    if not PDF_SUPPORT:
        raise ValueError("PyMuPDF not installed")

    images = []
    pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
    num_pages = min(pdf_document.page_count, max_pages)

    for page_num in range(num_pages):
        page = pdf_document[page_num]
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg", jpg_quality=90)
        images.append(img_bytes)

    pdf_document.close()
    return images


async def get_baidu_access_token() -> str:
    """获取百度 OCR access_token"""
    global _baidu_access_token, _baidu_token_expires

    if _baidu_access_token and _baidu_token_expires:
        if datetime.utcnow() < _baidu_token_expires - timedelta(days=1):
            return _baidu_access_token

    token_url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": BAIDU_OCR_API_KEY,
        "client_secret": BAIDU_OCR_SECRET_KEY
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(token_url, params=params)
        if response.status_code != 200:
            raise ValueError(f"Failed to get Baidu access token: {response.text}")

        data = response.json()
        if "error" in data:
            raise ValueError(f"Baidu OAuth error: {data.get('error_description')}")

        _baidu_access_token = data["access_token"]
        expires_in = data.get("expires_in", 2592000)
        _baidu_token_expires = datetime.utcnow() + timedelta(seconds=expires_in)

        return _baidu_access_token


async def call_baidu_ocr_single(image_bytes: bytes) -> str:
    """对单张图片调用百度 OCR"""
    access_token = await get_baidu_access_token()
    ocr_url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token={access_token}"

    image_base64 = base64.b64encode(image_bytes).decode('utf-8')

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            ocr_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"image": image_base64, "detect_direction": "true", "paragraph": "true"}
        )

        if response.status_code != 200:
            raise ValueError(f"Baidu OCR error: {response.status_code}")

        result = response.json()
        if "error_code" in result:
            raise ValueError(f"Baidu OCR error: {result.get('error_msg')}")

        words_result = result.get("words_result", [])
        return "\n".join([item["words"] for item in words_result])


async def perform_ocr(file_bytes: bytes, file_name: str, file_type: str) -> tuple[str, int, list]:
    """执行 OCR，返回 (text, page_count, text_blocks)

    text_blocks 仅在使用 DeepSeek-OCR 时返回非空列表
    """
    text_blocks = []

    # DeepSeek-OCR provider
    if OCR_PROVIDER == "deepseek":
        if not deepseek_ocr.is_available():
            raise ValueError("DeepSeek-OCR environment not available")

        # PDF 处理
        if file_type == "application/pdf" or file_name.lower().endswith('.pdf'):
            result = await deepseek_ocr.process_pdf_async(file_bytes)
            return result["markdown_text"], result["total_pages"], result["text_blocks"]

        # 图片处理
        result = await deepseek_ocr.process_image_async(file_bytes)
        return result["markdown_text"], 1, result["text_blocks"]

    # Baidu OCR provider (默认)
    # PDF 处理
    if file_type == "application/pdf" or file_name.lower().endswith('.pdf'):
        if not PDF_SUPPORT:
            raise ValueError("PDF support not available")

        images = pdf_to_images(file_bytes)
        all_texts = []

        for i, img_bytes in enumerate(images):
            try:
                page_text = await call_baidu_ocr_single(img_bytes)
                all_texts.append(f"--- Page {i + 1} ---\n{page_text}")
            except Exception as e:
                all_texts.append(f"--- Page {i + 1} ---\n[OCR Error: {str(e)}]")

        return "\n\n".join(all_texts), len(images), []

    # 图片处理
    text = await call_baidu_ocr_single(file_bytes)
    return text, 1, []


def perform_ocr_sync(file_bytes: bytes, file_name: str, file_type: str) -> tuple:
    """同步版本的 OCR 执行函数，用于后台任务"""
    text_blocks = []

    # DeepSeek-OCR provider
    if OCR_PROVIDER == "deepseek":
        if not deepseek_ocr.is_available():
            raise ValueError("DeepSeek-OCR environment not available")

        # PDF 处理 - 使用同步版本
        if file_type == "application/pdf" or file_name.lower().endswith('.pdf'):
            print(f"[OCR] Calling DeepSeek-OCR process_pdf (sync)...", flush=True)
            result = deepseek_ocr.process_pdf(file_bytes)
            return result["markdown_text"], result["total_pages"], result["text_blocks"]

        # 图片处理 - 使用同步版本
        print(f"[OCR] Calling DeepSeek-OCR process_image_bytes (sync)...", flush=True)
        result = deepseek_ocr.process_image_bytes(file_bytes)
        return result["markdown_text"], 1, result["text_blocks"]

    # Baidu OCR provider - 需要异步处理
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # PDF 处理
        if file_type == "application/pdf" or file_name.lower().endswith('.pdf'):
            if not PDF_SUPPORT:
                raise ValueError("PDF support not available")

            images = pdf_to_images(file_bytes)
            all_texts = []

            for i, img_bytes in enumerate(images):
                try:
                    page_text = loop.run_until_complete(call_baidu_ocr_single(img_bytes))
                    all_texts.append(f"--- Page {i + 1} ---\n{page_text}")
                except Exception as e:
                    all_texts.append(f"--- Page {i + 1} ---\n[OCR Error: {str(e)}]")

            return "\n\n".join(all_texts), len(images), []

        # 图片处理
        text = loop.run_until_complete(call_baidu_ocr_single(file_bytes))
        return text, 1, []
    finally:
        loop.close()


def process_ocr_background(document_id: str, file_bytes: bytes, file_name: str, file_type: str):
    """后台执行 OCR - 同步函数"""
    print(f"[OCR] Starting background OCR for document: {document_id}", flush=True)

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            print(f"[OCR] Document not found: {document_id}", flush=True)
            return

        doc.ocr_status = OCRStatus.PROCESSING.value
        db.commit()
        print(f"[OCR] Set status to PROCESSING for: {document_id}", flush=True)

        # 使用同步版本的 OCR 函数
        text, page_count, text_blocks = perform_ocr_sync(file_bytes, file_name, file_type)

        print(f"[OCR] OCR completed for {document_id}: {page_count} pages, {len(text)} chars", flush=True)

        doc.ocr_text = text
        doc.ocr_status = OCRStatus.COMPLETED.value
        doc.page_count = page_count
        doc.ocr_completed_at = datetime.utcnow()

        # 如果有 text_blocks (DeepSeek-OCR)，保存到数据库
        if text_blocks:
            # 先删除该文档的旧 text_blocks
            db.query(TextBlock).filter(TextBlock.document_id == document_id).delete()

            # 保存新的 text_blocks
            for block in text_blocks:
                bbox = block.get("bbox", {})
                text_block = TextBlock(
                    document_id=document_id,
                    block_id=block.get("block_id", ""),
                    page_number=block.get("page_number", 1),
                    text_content=block.get("text_content", ""),
                    block_type=block.get("block_type", ""),
                    bbox_x1=bbox.get("x1"),
                    bbox_y1=bbox.get("y1"),
                    bbox_x2=bbox.get("x2"),
                    bbox_y2=bbox.get("y2"),
                    confidence=block.get("confidence")
                )
                db.add(text_block)

        db.commit()
        print(f"[OCR] Successfully saved results for: {document_id}", flush=True)

    except Exception as e:
        print(f"[OCR] ERROR for {document_id}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.ocr_status = OCRStatus.FAILED.value
            doc.ocr_error = str(e)
            db.commit()
    finally:
        db.close()
        print(f"[OCR] Finished processing: {document_id}", flush=True)


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    folder: Optional[str] = Form(None),
    exhibit_number: Optional[str] = Form(None),
    exhibit_title: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Stage 1: 上传文档（不自动执行 OCR，需手动触发）

    参数:
    - folder: 文件夹 (A/B/C/D)，如果提供则自动生成 exhibit_number
    - exhibit_number: 直接指定 exhibit number (优先于 folder)
    """
    file_bytes = await file.read()
    file_name = file.filename or "unknown"
    file_type = file.content_type or "application/octet-stream"

    # 如果指定了 folder，自动生成 exhibit_number
    final_exhibit_number = exhibit_number
    if not final_exhibit_number and folder:
        # 查找该项目中该文件夹的最大编号
        existing_docs = db.query(Document).filter(
            Document.project_id == project_id,
            Document.exhibit_number.like(f"{folder.upper()}-%")
        ).all()

        max_num = 0
        for doc in existing_docs:
            if doc.exhibit_number:
                match = doc.exhibit_number.split('-')
                if len(match) == 2:
                    try:
                        num = int(match[1])
                        max_num = max(max_num, num)
                    except ValueError:
                        pass

        final_exhibit_number = f"{folder.upper()}-{max_num + 1}"

    document = Document(
        id=str(uuid.uuid4()),
        project_id=project_id,
        file_name=file_name,
        file_type=file_type,
        file_size=len(file_bytes),
        ocr_status=OCRStatus.PENDING.value,
        ocr_provider=OCR_PROVIDER,
        exhibit_number=final_exhibit_number,
        exhibit_title=exhibit_title or file_name.replace('.', '_')
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    # 保存原始文件到本地存储（用于后续 OCR）
    storage.save_uploaded_file(project_id, document.id, file_bytes, file_name)

    # 不再自动启动 OCR，需要手动调用 /ocr/{document_id} 或 /ocr/batch/{project_id}

    return DocumentResponse(
        id=document.id,
        project_id=document.project_id,
        file_name=document.file_name,
        file_type=document.file_type,
        file_size=document.file_size,
        page_count=document.page_count,
        ocr_text=document.ocr_text,
        ocr_status=document.ocr_status,
        exhibit_number=document.exhibit_number,
        exhibit_title=document.exhibit_title,
        created_at=document.created_at
    )


@router.get("/documents/{project_id}")
async def get_documents(project_id: str, db: Session = Depends(get_db)):
    """获取项目的所有文档 - 优先从数据库读取，否则从本地文件存储读取"""
    # 首先尝试从数据库读取
    documents = db.query(Document).filter(Document.project_id == project_id).all()

    if documents:
        return {
            "documents": [DocumentResponse(
                id=d.id, project_id=d.project_id, file_name=d.file_name,
                file_type=d.file_type, file_size=d.file_size, page_count=d.page_count,
                ocr_text=d.ocr_text, ocr_status=d.ocr_status,
                exhibit_number=d.exhibit_number, exhibit_title=d.exhibit_title,
                created_at=d.created_at
            ) for d in documents],
            "total": len(documents)
        }

    # 如果数据库没有，尝试从本地文件存储读取 (用于导入的项目)
    local_documents = storage.get_documents(project_id)
    if local_documents:
        return {
            "documents": local_documents,
            "total": len(local_documents),
            "source": "local_storage"
        }

    return {"documents": [], "total": 0}


@router.delete("/document/{document_id}")
async def delete_document(document_id: str, db: Session = Depends(get_db)):
    """删除单个文档"""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    project_id = document.project_id

    # 删除关联的 text_blocks
    db.query(TextBlock).filter(TextBlock.document_id == document_id).delete()

    # 删除关联的分析结果
    db.query(DocumentAnalysis).filter(DocumentAnalysis.document_id == document_id).delete()

    # 删除文档记录
    db.delete(document)
    db.commit()

    # 尝试删除本地存储的文件
    try:
        storage.delete_document_file(project_id, document_id)
    except Exception:
        pass  # 文件可能不存在，忽略错误

    # 删除页面图片缓存
    try:
        page_cache.delete_document_cache(document_id)
    except Exception:
        pass

    return {"success": True, "message": "Document deleted", "document_id": document_id}


@router.delete("/document/batch/{project_id}")
async def delete_documents_batch(
    project_id: str,
    document_ids: list[str] = Body(...),
    db: Session = Depends(get_db)
):
    """批量删除文档"""
    deleted_count = 0
    errors = []

    for doc_id in document_ids:
        document = db.query(Document).filter(
            Document.id == doc_id,
            Document.project_id == project_id
        ).first()

        if document:
            # 删除关联的 text_blocks
            db.query(TextBlock).filter(TextBlock.document_id == doc_id).delete()

            # 删除关联的分析结果
            db.query(DocumentAnalysis).filter(DocumentAnalysis.document_id == doc_id).delete()

            # 删除文档记录
            db.delete(document)
            deleted_count += 1

            # 尝试删除本地存储的文件
            try:
                storage.delete_document_file(project_id, doc_id)
            except Exception:
                pass

            # 删除页面图片缓存
            try:
                page_cache.delete_document_cache(doc_id)
            except Exception:
                pass
        else:
            errors.append({"document_id": doc_id, "error": "Document not found"})

    db.commit()

    return {
        "success": True,
        "deleted_count": deleted_count,
        "total_requested": len(document_ids),
        "errors": errors if errors else None
    }


# ============== OCR 手动触发与进度监控 ==============

# 全局 OCR 任务状态存储
_ocr_batch_status: Dict[str, Dict] = {}


def _ocr_processor_callback(document_id: str, file_bytes: bytes, file_name: str, file_type: str, batch_id: str = None) -> bool:
    """OCR 队列处理回调函数 - 实际执行 OCR 的地方

    这个函数会在队列 worker 线程中被调用，确保每次只处理一个文档。
    支持页级别进度监控、断点续传、暂停/取消控制和页级别时间记录。
    """
    print(f"[OCR-Queue-Processor] Processing document: {document_id}", flush=True)

    db = SessionLocal()
    ocr_started_at = datetime.utcnow()

    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            print(f"[OCR-Queue-Processor] Document not found: {document_id}", flush=True)
            return False

        project_id = doc.project_id
        doc.ocr_status = OCRStatus.PROCESSING.value
        doc.ocr_started_at = ocr_started_at
        db.commit()

        # 更新批次状态（如果有）
        if batch_id and batch_id in _ocr_batch_status:
            _ocr_batch_status[batch_id]["documents"][document_id]["status"] = "processing"
            _ocr_batch_status[batch_id]["processing"] += 1

        # 检查已完成的页（断点续传）
        completed_pages = storage.get_completed_pages(project_id, document_id)
        if completed_pages:
            print(f"[OCR-Queue-Processor] Resuming from page {max(completed_pages)+1}, skipping {len(completed_pages)} completed pages", flush=True)

        # 用于记录每页开始时间
        page_start_time = {}

        # 定义进度回调 - 更新队列任务状态并记录页开始时间
        def on_page_progress(current_page: int, total_pages: int):
            page_start_time[current_page] = datetime.utcnow()
            ocr_queue.update_page_progress(document_id, current_page, total_pages)
            print(f"[OCR] {file_name}: page {current_page}/{total_pages}", flush=True)

        # 定义单页完成回调 - 即时保存并记录时间
        def on_page_complete(page_number: int, page_result: dict):
            storage.save_ocr_page(project_id, document_id, page_number, page_result)

            # 记录页级别时间
            started_at = page_start_time.get(page_number, datetime.utcnow())
            completed_at = datetime.utcnow()
            ocr_queue.record_page_timing(document_id, page_number, started_at, completed_at)

            print(f"[OCR] {file_name}: page {page_number} saved to disk", flush=True)

        # 定义停止检查回调
        def check_should_stop():
            return ocr_queue.check_should_stop(document_id)

        # 判断文件类型并执行 OCR
        is_pdf = file_type == "application/pdf" or file_name.lower().endswith('.pdf')
        stopped = None
        stopped_at_page = None

        if OCR_PROVIDER == "deepseek":
            if not deepseek_ocr.is_available():
                raise ValueError("DeepSeek-OCR environment not available")

            if is_pdf:
                # PDF 处理 - 带进度回调、断点续传和停止检查
                result = deepseek_ocr.process_pdf(
                    file_bytes,
                    progress_callback=on_page_progress,
                    page_callback=on_page_complete,
                    skip_pages=completed_pages,
                    should_stop_callback=check_should_stop
                )
                text = result["markdown_text"]
                page_count = result["total_pages"]
                text_blocks = result["text_blocks"]
                stopped = result.get("stopped")
                stopped_at_page = result.get("stopped_at_page")
            else:
                # 图片处理
                result = deepseek_ocr.process_image_bytes(file_bytes)
                text = result["markdown_text"]
                page_count = 1
                text_blocks = result["text_blocks"]
        else:
            # Baidu OCR - 保持原逻辑
            text, page_count, text_blocks = perform_ocr_sync(file_bytes, file_name, file_type)

        # 处理停止信号
        if stopped:
            completed_pages_now = storage.get_completed_pages(project_id, document_id)
            if stopped == "pause":
                # 暂停 - 标记状态并让队列管理器处理
                doc.ocr_status = OCRStatus.PAUSED.value
                doc.ocr_completed_pages = len(completed_pages_now)
                doc.ocr_total_pages = page_count
                ocr_queue.mark_task_paused(document_id)
                print(f"[OCR-Queue-Processor] Paused at page {stopped_at_page}: {document_id}", flush=True)
            elif stopped == "cancel":
                # 取消 - 标记状态
                if completed_pages_now:
                    doc.ocr_status = OCRStatus.PARTIAL.value
                    doc.ocr_completed_pages = len(completed_pages_now)
                else:
                    doc.ocr_status = OCRStatus.CANCELLED.value
                doc.ocr_total_pages = page_count
                ocr_queue.mark_task_cancelled(document_id)
                print(f"[OCR-Queue-Processor] Cancelled at page {stopped_at_page}: {document_id}", flush=True)

            db.commit()

            # 更新批次状态
            if batch_id and batch_id in _ocr_batch_status:
                _ocr_batch_status[batch_id]["documents"][document_id]["status"] = stopped
                if _ocr_batch_status[batch_id]["processing"] > 0:
                    _ocr_batch_status[batch_id]["processing"] -= 1

            return stopped == "pause"  # 暂停返回 True 以便后续恢复

        # 如果有断点续传，需要合并所有页面结果
        if completed_pages and is_pdf:
            all_pages = storage.load_all_ocr_pages(project_id, document_id)
            if all_pages:
                # 重新合并所有页的 markdown 和 text_blocks
                all_markdown_parts = []
                all_text_blocks = []
                for page_result in all_pages:
                    page_num = page_result.get("page_number", 0)
                    all_markdown_parts.append(f"--- Page {page_num} ---\n{page_result.get('markdown_text', '')}")
                    all_text_blocks.extend(page_result.get("text_blocks", []))
                text = "\n\n".join(all_markdown_parts)
                text_blocks = all_text_blocks

        # 计算总耗时
        ocr_completed_at = datetime.utcnow()
        total_duration = (ocr_completed_at - ocr_started_at).total_seconds()

        print(f"[OCR-Queue-Processor] OCR completed: {page_count} pages, {len(text)} chars, {total_duration:.1f}s", flush=True)

        doc.ocr_text = text
        doc.ocr_status = OCRStatus.COMPLETED.value
        doc.page_count = page_count
        doc.ocr_completed_at = ocr_completed_at
        doc.ocr_total_pages = page_count
        doc.ocr_completed_pages = page_count
        doc.ocr_total_duration = total_duration

        # 保存 text_blocks
        if text_blocks:
            db.query(TextBlock).filter(TextBlock.document_id == document_id).delete()
            for block in text_blocks:
                bbox = block.get("bbox", {})
                text_block = TextBlock(
                    document_id=document_id,
                    block_id=block.get("block_id", ""),
                    page_number=block.get("page_number", 1),
                    text_content=block.get("text_content", ""),
                    block_type=block.get("block_type", ""),
                    bbox_x1=bbox.get("x1"),
                    bbox_y1=bbox.get("y1"),
                    bbox_x2=bbox.get("x2"),
                    bbox_y2=bbox.get("y2"),
                    confidence=block.get("confidence")
                )
                db.add(text_block)

        db.commit()

        # 更新批次状态
        if batch_id and batch_id in _ocr_batch_status:
            _ocr_batch_status[batch_id]["documents"][document_id]["status"] = "completed"
            _ocr_batch_status[batch_id]["completed"] += 1
            _ocr_batch_status[batch_id]["processing"] -= 1

            # 检查是否全部完成
            total = _ocr_batch_status[batch_id]["total"]
            done = _ocr_batch_status[batch_id]["completed"] + _ocr_batch_status[batch_id]["failed"]
            if done >= total:
                _ocr_batch_status[batch_id]["finished_at"] = datetime.utcnow().isoformat()

        print(f"[OCR-Queue-Processor] Successfully saved: {document_id}", flush=True)

        # OCR 完成后预渲染所有页面图片到缓存
        try:
            file_bytes = storage.load_uploaded_file(doc.project_id, document_id)
            if file_bytes and doc.file_name.lower().endswith('.pdf'):
                rendered = page_cache.prerender_document(document_id, file_bytes, page_count)
                print(f"[OCR-Queue-Processor] Prerendered {rendered}/{page_count} pages for {document_id}", flush=True)
        except Exception as prerender_err:
            print(f"[OCR-Queue-Processor] Prerender failed (non-critical): {prerender_err}", flush=True)

        return True

    except Exception as e:
        print(f"[OCR-Queue-Processor] ERROR for {document_id}: {e}", flush=True)
        import traceback
        traceback.print_exc()

        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            # 检查是否有已完成的页（部分完成）
            completed_pages = storage.get_completed_pages(doc.project_id, document_id)
            if completed_pages:
                doc.ocr_status = OCRStatus.PARTIAL.value
                doc.ocr_error = f"Failed at page {max(completed_pages)+1}: {str(e)}"
                doc.ocr_completed_pages = len(completed_pages)
            else:
                doc.ocr_status = OCRStatus.FAILED.value
                doc.ocr_error = str(e)
            db.commit()

        # 更新批次状态
        if batch_id and batch_id in _ocr_batch_status:
            _ocr_batch_status[batch_id]["documents"][document_id]["status"] = "failed"
            _ocr_batch_status[batch_id]["documents"][document_id]["error"] = str(e)
            _ocr_batch_status[batch_id]["failed"] += 1
            if _ocr_batch_status[batch_id]["processing"] > 0:
                _ocr_batch_status[batch_id]["processing"] -= 1

            # 检查是否全部完成
            total = _ocr_batch_status[batch_id]["total"]
            done = _ocr_batch_status[batch_id]["completed"] + _ocr_batch_status[batch_id]["failed"]
            if done >= total:
                _ocr_batch_status[batch_id]["finished_at"] = datetime.utcnow().isoformat()

        return False

    finally:
        db.close()


# 初始化 OCR 队列处理器
ocr_queue.set_processor(_ocr_processor_callback)


# 注意：更具体的路由必须在通用路由之前定义
# /ocr/batch, /ocr/reset, /ocr/status, /ocr/progress 必须在 /ocr/{document_id} 之前

@router.post("/ocr/reset/{project_id}")
async def reset_stuck_ocr(project_id: str, db: Session = Depends(get_db)):
    """重置卡在 processing 状态的文档为 pending 状态"""
    stuck_docs = db.query(Document).filter(
        Document.project_id == project_id,
        Document.ocr_status == OCRStatus.PROCESSING.value
    ).all()

    reset_count = 0
    for doc in stuck_docs:
        doc.ocr_status = OCRStatus.PENDING.value
        doc.ocr_error = None
        reset_count += 1

    db.commit()

    return {
        "success": True,
        "project_id": project_id,
        "reset_count": reset_count,
        "message": f"Reset {reset_count} stuck documents to pending status"
    }


@router.post("/ocr/retry/{document_id}")
async def retry_ocr(
    document_id: str,
    force_restart: bool = False,
    db: Session = Depends(get_db)
):
    """重试 OCR 处理

    对于 partial 或 failed 状态的文档，重新加入队列处理。
    - 如果 force_restart=False（默认），会从断点继续处理（跳过已完成页）
    - 如果 force_restart=True，会清除所有已完成页，完全重新处理

    Args:
        document_id: 文档 ID
        force_restart: 是否强制完全重新开始
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 检查状态
    if document.ocr_status == OCRStatus.COMPLETED.value:
        return {"success": True, "message": "Document OCR already completed", "document_id": document_id}
    if document.ocr_status == OCRStatus.PROCESSING.value:
        return {"success": True, "message": "Document OCR already in progress", "document_id": document_id}

    # 检查是否已在队列中
    queue_status = ocr_queue.get_task_status(document_id)
    if queue_status and queue_status["status"] in ["queued", "processing"]:
        return {
            "success": True,
            "message": f"Document already in queue at position {queue_status['position']}",
            "document_id": document_id,
            "queue_position": queue_status["position"]
        }

    project_id = document.project_id

    # 如果强制重新开始，清除已完成的页
    if force_restart:
        storage.clear_ocr_pages(project_id, document_id)
        print(f"[OCR-Retry] Cleared all completed pages for {document_id}", flush=True)

    # 加载文件
    file_bytes = storage.load_uploaded_file(project_id, document_id)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="Original file not found")

    # 重置状态
    document.ocr_status = OCRStatus.PENDING.value
    document.ocr_error = None
    db.commit()

    # 加入队列
    position = ocr_queue.add_task(
        document_id=document_id,
        project_id=project_id,
        file_name=document.file_name,
        file_type=document.file_type,
        file_bytes=file_bytes
    )

    # 检查已完成的页数
    completed_pages = storage.get_completed_pages(project_id, document_id)

    return {
        "success": True,
        "message": f"Added to OCR queue at position {position}",
        "document_id": document_id,
        "queue_position": position,
        "resume_from_page": max(completed_pages) + 1 if completed_pages else 1,
        "completed_pages": len(completed_pages),
        "force_restart": force_restart
    }


@router.post("/ocr/batch/{project_id}")
async def trigger_ocr_batch(
    project_id: str,
    db: Session = Depends(get_db)
):
    """批量触发项目中所有待处理文档的 OCR (使用队列串行处理)

    文档会被加入队列，逐个处理，避免内存溢出。
    可以通过 /ocr/status/{batch_id} 或 /ocr/queue 查询进度。
    """
    # 查找所有 pending 状态的文档
    pending_docs = db.query(Document).filter(
        Document.project_id == project_id,
        Document.ocr_status == OCRStatus.PENDING.value
    ).all()

    if not pending_docs:
        return {
            "success": True,
            "message": "No pending documents",
            "total": 0,
            "batch_id": None
        }

    # 创建批次 ID
    batch_id = str(uuid.uuid4())[:8]

    # 初始化批次状态
    _ocr_batch_status[batch_id] = {
        "project_id": project_id,
        "total": len(pending_docs),
        "completed": 0,
        "failed": 0,
        "processing": 0,
        "documents": {doc.id: {"status": "pending", "file_name": doc.file_name} for doc in pending_docs},
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None
    }

    # 将文档加入 OCR 队列（串行处理，不是并行）
    queued_count = 0
    for doc in pending_docs:
        file_bytes = storage.load_uploaded_file(project_id, doc.id)
        if file_bytes:
            _ocr_batch_status[batch_id]["documents"][doc.id]["status"] = "queued"
            position = ocr_queue.add_task(
                document_id=doc.id,
                project_id=project_id,
                file_name=doc.file_name,
                file_type=doc.file_type,
                file_bytes=file_bytes,
                batch_id=batch_id
            )
            _ocr_batch_status[batch_id]["documents"][doc.id]["queue_position"] = position
            queued_count += 1
        else:
            _ocr_batch_status[batch_id]["documents"][doc.id]["status"] = "file_not_found"
            _ocr_batch_status[batch_id]["failed"] += 1

    return {
        "success": True,
        "message": f"Added {queued_count} documents to OCR queue (serial processing)",
        "total": len(pending_docs),
        "queued": queued_count,
        "batch_id": batch_id,
        "mode": "queue"  # 标记使用队列模式
    }


@router.post("/ocr/{document_id}")
async def trigger_ocr_single(
    document_id: str,
    db: Session = Depends(get_db)
):
    """手动触发单个文档的 OCR (加入队列串行处理)"""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 检查是否已完成或正在处理
    if document.ocr_status == OCRStatus.COMPLETED.value:
        return {"success": True, "message": "OCR already completed", "document_id": document_id}
    if document.ocr_status == OCRStatus.PROCESSING.value:
        return {"success": True, "message": "OCR already in progress", "document_id": document_id}

    # 检查是否已在队列中
    queue_status = ocr_queue.get_task_status(document_id)
    if queue_status and queue_status["status"] in ["queued", "processing"]:
        return {
            "success": True,
            "message": f"Document already in queue at position {queue_status['position']}",
            "document_id": document_id,
            "queue_position": queue_status["position"]
        }

    # 加载文件
    file_bytes = storage.load_uploaded_file(document.project_id, document_id)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="Original file not found")

    # 加入 OCR 队列
    position = ocr_queue.add_task(
        document_id=document_id,
        project_id=document.project_id,
        file_name=document.file_name,
        file_type=document.file_type,
        file_bytes=file_bytes
    )

    return {
        "success": True,
        "message": f"Added to OCR queue at position {position}",
        "document_id": document_id,
        "queue_position": position,
        "mode": "queue"
    }


def process_ocr_with_tracking(
    batch_id: str,
    document_id: str,
    file_bytes: bytes,
    file_name: str,
    file_type: str
):
    """执行 OCR 并更新批次进度 - 同步函数，内部运行异步代码"""
    import asyncio
    print(f"[OCR-Batch] Starting OCR for document: {document_id} (batch: {batch_id})", flush=True)

    db = SessionLocal()
    try:
        # 更新状态为 processing
        if batch_id in _ocr_batch_status:
            _ocr_batch_status[batch_id]["documents"][document_id]["status"] = "processing"
            _ocr_batch_status[batch_id]["processing"] += 1

        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            print(f"[OCR-Batch] Document not found: {document_id}", flush=True)
            if batch_id in _ocr_batch_status:
                _ocr_batch_status[batch_id]["documents"][document_id]["status"] = "error"
                _ocr_batch_status[batch_id]["documents"][document_id]["error"] = "Document not found"
                _ocr_batch_status[batch_id]["failed"] += 1
                _ocr_batch_status[batch_id]["processing"] -= 1
            return

        doc.ocr_status = OCRStatus.PROCESSING.value
        db.commit()

        # 在同步函数中运行异步 OCR
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            text, page_count, text_blocks = loop.run_until_complete(
                perform_ocr(file_bytes, file_name, file_type)
            )
        finally:
            loop.close()

        print(f"[OCR-Batch] OCR completed for {document_id}: {page_count} pages", flush=True)

        doc.ocr_text = text
        doc.ocr_status = OCRStatus.COMPLETED.value
        doc.page_count = page_count
        doc.ocr_completed_at = datetime.utcnow()

        # 保存 text_blocks
        if text_blocks:
            db.query(TextBlock).filter(TextBlock.document_id == document_id).delete()
            for block in text_blocks:
                bbox = block.get("bbox", {})
                text_block = TextBlock(
                    document_id=document_id,
                    block_id=block.get("block_id", ""),
                    page_number=block.get("page_number", 1),
                    text_content=block.get("text_content", ""),
                    block_type=block.get("block_type", ""),
                    bbox_x1=bbox.get("x1"),
                    bbox_y1=bbox.get("y1"),
                    bbox_x2=bbox.get("x2"),
                    bbox_y2=bbox.get("y2"),
                    confidence=block.get("confidence")
                )
                db.add(text_block)

        db.commit()

        # 更新批次状态
        if batch_id in _ocr_batch_status:
            _ocr_batch_status[batch_id]["documents"][document_id]["status"] = "completed"
            _ocr_batch_status[batch_id]["completed"] += 1
            _ocr_batch_status[batch_id]["processing"] -= 1

            # 检查是否全部完成
            total = _ocr_batch_status[batch_id]["total"]
            done = _ocr_batch_status[batch_id]["completed"] + _ocr_batch_status[batch_id]["failed"]
            if done >= total:
                _ocr_batch_status[batch_id]["finished_at"] = datetime.utcnow().isoformat()

    except Exception as e:
        print(f"[OCR-Batch] ERROR for {document_id}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.ocr_status = OCRStatus.FAILED.value
            doc.ocr_error = str(e)
            db.commit()

        if batch_id in _ocr_batch_status:
            _ocr_batch_status[batch_id]["documents"][document_id]["status"] = "failed"
            _ocr_batch_status[batch_id]["documents"][document_id]["error"] = str(e)
            _ocr_batch_status[batch_id]["failed"] += 1
            _ocr_batch_status[batch_id]["processing"] -= 1

            # 检查是否全部完成
            total = _ocr_batch_status[batch_id]["total"]
            done = _ocr_batch_status[batch_id]["completed"] + _ocr_batch_status[batch_id]["failed"]
            if done >= total:
                _ocr_batch_status[batch_id]["finished_at"] = datetime.utcnow().isoformat()
    finally:
        db.close()
        print(f"[OCR-Batch] Finished processing: {document_id}", flush=True)


@router.get("/ocr/queue")
async def get_ocr_queue_status():
    """获取 OCR 队列整体状态

    返回当前队列的运行状态，包括：
    - running: 队列是否在运行
    - pending_count: 等待处理的文档数
    - current_task: 当前正在处理的任务信息
    """
    return ocr_queue.get_queue_status()


@router.get("/ocr/queue/{document_id}")
async def get_ocr_queue_task_status(document_id: str):
    """获取单个文档在队列中的状态"""
    status = ocr_queue.get_task_status(document_id)
    if not status:
        raise HTTPException(status_code=404, detail="Document not found in queue")
    return status


@router.post("/ocr/cancel/{document_id}")
async def cancel_ocr(document_id: str, db: Session = Depends(get_db)):
    """取消 OCR 处理

    如果文档正在处理中，会在当前页完成后停止。
    已完成的页面会保留，文档状态变为 PARTIAL 或 CANCELLED。
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 尝试取消
    success = ocr_queue.request_cancel(document_id)

    if success:
        return {
            "success": True,
            "message": "Cancel request sent. OCR will stop after current page completes.",
            "document_id": document_id
        }
    else:
        # 可能不在队列中，检查文档状态
        if document.ocr_status in [OCRStatus.COMPLETED.value, OCRStatus.FAILED.value, OCRStatus.CANCELLED.value]:
            return {
                "success": False,
                "message": f"Cannot cancel: document is already {document.ocr_status}",
                "document_id": document_id
            }
        return {
            "success": False,
            "message": "Document not found in queue or cannot be cancelled",
            "document_id": document_id
        }


@router.post("/ocr/pause/{document_id}")
async def pause_ocr(document_id: str, db: Session = Depends(get_db)):
    """暂停 OCR 处理

    只能暂停正在处理中的文档。暂停后可以通过 resume 恢复。
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 尝试暂停
    success = ocr_queue.request_pause(document_id)

    if success:
        return {
            "success": True,
            "message": "Pause request sent. OCR will pause after current page completes.",
            "document_id": document_id
        }
    else:
        # 检查状态
        if document.ocr_status == OCRStatus.PAUSED.value:
            return {
                "success": False,
                "message": "Document is already paused",
                "document_id": document_id
            }
        elif document.ocr_status != OCRStatus.PROCESSING.value:
            return {
                "success": False,
                "message": f"Cannot pause: document status is {document.ocr_status}",
                "document_id": document_id
            }
        return {
            "success": False,
            "message": "Document not found in queue or cannot be paused",
            "document_id": document_id
        }


@router.post("/ocr/resume/{document_id}")
async def resume_ocr(document_id: str, db: Session = Depends(get_db)):
    """恢复暂停的 OCR 处理

    从上次暂停的页面继续处理。
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 检查状态
    if document.ocr_status not in [OCRStatus.PAUSED.value, OCRStatus.PARTIAL.value]:
        return {
            "success": False,
            "message": f"Cannot resume: document status is {document.ocr_status}",
            "document_id": document_id
        }

    # 尝试从队列恢复（如果任务还在内存中）
    success = ocr_queue.request_resume(document_id)

    if success:
        # 更新数据库状态
        document.ocr_status = OCRStatus.PROCESSING.value
        db.commit()
        return {
            "success": True,
            "message": "Resume request sent. OCR will continue from last completed page.",
            "document_id": document_id
        }

    # 任务不在内存中（可能后端重启过），需要重新加入队列
    project_id = document.project_id
    file_bytes = storage.load_uploaded_file(project_id, document_id)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="Original file not found")

    # 重新加入队列（会自动跳过已完成的页）
    position = ocr_queue.add_task(
        document_id=document_id,
        project_id=project_id,
        file_name=document.file_name,
        file_type=document.file_type,
        file_bytes=file_bytes
    )

    # 更新状态
    document.ocr_status = OCRStatus.QUEUED.value
    db.commit()

    # 获取已完成页数
    completed_pages = storage.get_completed_pages(project_id, document_id)

    return {
        "success": True,
        "message": f"Added back to queue at position {position}. Will resume from page {len(completed_pages) + 1}.",
        "document_id": document_id,
        "queue_position": position,
        "completed_pages": len(completed_pages)
    }


@router.get("/ocr/status/{batch_id}")
async def get_ocr_batch_status(batch_id: str):
    """获取批量 OCR 进度"""
    if batch_id not in _ocr_batch_status:
        raise HTTPException(status_code=404, detail="Batch not found")

    status = _ocr_batch_status[batch_id]

    # 合并队列状态信息
    queue_info = ocr_queue.get_batch_status(batch_id)
    if queue_info:
        # 使用队列的实时状态更新
        return {
            "batch_id": batch_id,
            "project_id": status["project_id"],
            "total": queue_info["total"],
            "completed": queue_info["completed"],
            "failed": queue_info["failed"],
            "processing": queue_info["processing"],
            "pending": queue_info["queued"],
            "progress_percent": queue_info["progress_percent"],
            "started_at": status["started_at"],
            "finished_at": status["finished_at"] if queue_info["is_finished"] else None,
            "is_finished": queue_info["is_finished"],
            "current_file": queue_info.get("current_file"),
            "documents": status["documents"],
            "mode": "queue"
        }

    return {
        "batch_id": batch_id,
        "project_id": status["project_id"],
        "total": status["total"],
        "completed": status["completed"],
        "failed": status["failed"],
        "processing": status["processing"],
        "pending": status["total"] - status["completed"] - status["failed"] - status["processing"],
        "progress_percent": round((status["completed"] + status["failed"]) / status["total"] * 100, 1) if status["total"] > 0 else 0,
        "started_at": status["started_at"],
        "finished_at": status["finished_at"],
        "is_finished": status["finished_at"] is not None,
        "documents": status["documents"]
    }


@router.get("/ocr/progress/{project_id}")
async def get_project_ocr_progress(project_id: str, db: Session = Depends(get_db)):
    """获取项目的 OCR 总体进度，包括当前处理文档的页级别信息"""
    documents = db.query(Document).filter(Document.project_id == project_id).all()

    if not documents:
        return {
            "project_id": project_id,
            "total": 0,
            "pending": 0,
            "queued": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "partial": 0,
            "paused": 0,
            "cancelled": 0,
            "progress_percent": 0
        }

    total = len(documents)
    pending = sum(1 for d in documents if d.ocr_status == OCRStatus.PENDING.value)
    queued = sum(1 for d in documents if d.ocr_status == OCRStatus.QUEUED.value)
    processing = sum(1 for d in documents if d.ocr_status == OCRStatus.PROCESSING.value)
    completed = sum(1 for d in documents if d.ocr_status == OCRStatus.COMPLETED.value)
    failed = sum(1 for d in documents if d.ocr_status == OCRStatus.FAILED.value)
    partial = sum(1 for d in documents if d.ocr_status == OCRStatus.PARTIAL.value)
    paused = sum(1 for d in documents if d.ocr_status == OCRStatus.PAUSED.value)
    cancelled = sum(1 for d in documents if d.ocr_status == OCRStatus.CANCELLED.value)

    # 获取当前正在处理的文档的页级别进度
    current_processing = None
    queue_status = ocr_queue.get_queue_status()
    if queue_status.get("current_task"):
        current_task = queue_status["current_task"]
        current_processing = {
            "document_id": current_task.get("document_id"),
            "file_name": current_task.get("file_name"),
            "current_page": current_task.get("current_page", 0),
            "total_pages": current_task.get("total_pages", 0),
            "page_status": current_task.get("page_status", "")
        }

    return {
        "project_id": project_id,
        "total": total,
        "pending": pending,
        "queued": queued,
        "processing": processing,
        "completed": completed,
        "failed": failed,
        "partial": partial,
        "paused": paused,
        "cancelled": cancelled,
        "progress_percent": round(completed / total * 100, 1) if total > 0 else 0,
        "current_processing": current_processing,
        "documents": [
            {
                "id": d.id,
                "file_name": d.file_name,
                "exhibit_number": d.exhibit_number,
                "ocr_status": d.ocr_status,
                "page_count": d.page_count,
                "ocr_error": d.ocr_error
            }
            for d in documents
        ]
    }


@router.get("/ocr/stream/{project_id}")
async def stream_ocr_progress(project_id: str, db: Session = Depends(get_db)):
    """SSE 端点：实时推送 OCR 进度

    返回 Server-Sent Events 流：
    - event: progress - 进度更新
    - event: complete - OCR 全部完成
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            # 获取当前进度
            documents = db.query(Document).filter(Document.project_id == project_id).all()

            if not documents:
                # 没有文档，发送空进度并结束
                yield f"event: complete\ndata: {json.dumps({'project_id': project_id, 'total': 0, 'completed': 0})}\n\n"
                break

            total = len(documents)
            pending = sum(1 for d in documents if d.ocr_status == OCRStatus.PENDING.value)
            queued = sum(1 for d in documents if d.ocr_status == OCRStatus.QUEUED.value)
            processing = sum(1 for d in documents if d.ocr_status == OCRStatus.PROCESSING.value)
            completed = sum(1 for d in documents if d.ocr_status == OCRStatus.COMPLETED.value)
            failed = sum(1 for d in documents if d.ocr_status == OCRStatus.FAILED.value)
            partial = sum(1 for d in documents if d.ocr_status == OCRStatus.PARTIAL.value)
            paused = sum(1 for d in documents if d.ocr_status == OCRStatus.PAUSED.value)
            cancelled = sum(1 for d in documents if d.ocr_status == OCRStatus.CANCELLED.value)

            # 获取当前正在处理的文档的页级别进度
            current_processing = None
            queue_status = ocr_queue.get_queue_status()
            if queue_status.get("current_task"):
                current_task = queue_status["current_task"]
                current_processing = {
                    "document_id": current_task.get("document_id"),
                    "file_name": current_task.get("file_name"),
                    "current_page": current_task.get("current_page", 0),
                    "total_pages": current_task.get("total_pages", 0),
                    "page_status": current_task.get("page_status", "")
                }

            progress = {
                "project_id": project_id,
                "total": total,
                "pending": pending,
                "queued": queued,
                "processing": processing,
                "completed": completed,
                "failed": failed,
                "partial": partial,
                "paused": paused,
                "cancelled": cancelled,
                "progress_percent": round(completed / total * 100, 1) if total > 0 else 0,
                "current_processing": current_processing,
                "documents": [
                    {
                        "id": d.id,
                        "file_name": d.file_name,
                        "exhibit_number": d.exhibit_number,
                        "ocr_status": d.ocr_status,
                        "page_count": d.page_count,
                        "ocr_error": d.ocr_error
                    }
                    for d in documents
                ]
            }

            # 检查是否完成（没有正在处理或等待处理的文档）
            if processing == 0 and pending == 0 and queued == 0:
                yield f"event: complete\ndata: {json.dumps(progress)}\n\n"
                break

            # 发送进度更新
            yield f"event: progress\ndata: {json.dumps(progress)}\n\n"

            # 刷新数据库会话以获取最新数据
            db.expire_all()

            # 等待 1 秒后再次检查
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        }
    )


# ============== 模型配置 ==============

# 可用模型列表
AVAILABLE_MODELS = [
    {"id": "gpt-4o", "name": "GPT-4o", "type": "standard"},
    {"id": "gpt-4.1", "name": "GPT-4.1", "type": "standard"},
    {"id": "o4-mini", "name": "O4-Mini (推理模型)", "type": "reasoning"},
    {"id": "o3", "name": "O3 (推理模型)", "type": "reasoning"},
]

# 当前选择的模型（可动态切换）
current_model = LLM_MODEL


# ============== Stage 2: LLM1 Analysis ==============

async def call_llm(prompt: str, model_override: str = None, max_retries: int = 3) -> dict:
    """调用 LLM，支持本地模型和 OpenAI，带速率限制重试"""
    import asyncio
    import re

    model = model_override or current_model

    # 根据 LLM_PROVIDER 选择 API 配置
    if LLM_PROVIDER == "ollama":
        api_base = settings.ollama_api_base  # http://localhost:11434/v1
        api_key = "ollama"  # Ollama 不需要真实 key
        is_reasoning_model = False
        model = model_override or settings.ollama_model
    elif LLM_PROVIDER == "local":
        api_base = LLM_API_BASE
        api_key = OPENAI_API_KEY or "not-needed"  # 本地模型通常不需要 key
        is_reasoning_model = False  # 本地模型按标准模型处理
    else:  # openai / azure / deepseek / claude
        api_base = OPENAI_API_BASE
        api_key = OPENAI_API_KEY
        # 判断是否是推理模型（o 系列）
        is_reasoning_model = model.startswith("o")

    # 构建请求参数
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise document analyzer. Return ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ],
    }

    if is_reasoning_model:
        # o 系列模型使用 max_completion_tokens，不支持 temperature 和 response_format
        request_body["max_completion_tokens"] = 16000
    else:
        # 标准模型使用 max_tokens
        request_body["temperature"] = 0.1
        request_body["max_tokens"] = 16000  # 增加到 16000 以容纳 Qwen3 思考模式
        # 本地模型可能不支持 response_format，但 vLLM 和 Ollama 支持
        if LLM_PROVIDER == "ollama" or LLM_PROVIDER != "local" or "qwen" in model.lower() or "deepseek" in model.lower():
            request_body["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=request_body
                )

                if response.status_code == 429:
                    # Rate limit - 等待后重试
                    retry_after = 3.0  # 默认等待 3 秒
                    # 尝试从响应中获取建议的等待时间
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get("message", "")
                        # 提取等待时间，如 "Please try again in 2.156s"
                        time_match = re.search(r'try again in ([\d.]+)s', error_msg)
                        if time_match:
                            retry_after = float(time_match.group(1)) + 0.5  # 多等一点
                    except:
                        pass

                    if attempt < max_retries - 1:
                        print(f"Rate limited, waiting {retry_after}s before retry {attempt + 2}/{max_retries}")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        raise ValueError(f"Rate limit exceeded after {max_retries} retries")

                if response.status_code != 200:
                    raise ValueError(f"LLM error: {response.text}")

                data = response.json()
                message = data["choices"][0]["message"]
                content = message.get("content", "")

                # Qwen3 思考模式：如果 content 为空，尝试从 reasoning 字段获取
                if not content and "reasoning" in message:
                    reasoning = message.get("reasoning", "")
                    # 尝试找到 JSON 部分
                    json_match = re.search(r'\{[\s\S]*\}', reasoning)
                    if json_match:
                        content = json_match.group()
                    else:
                        raise ValueError(f"Qwen3 reasoning mode returned no valid JSON. Reasoning: {reasoning[:500]}")

                if not content:
                    raise ValueError("LLM returned empty content")

                # 尝试解析 JSON（推理模型可能返回带有额外文本的 JSON）
                def extract_first_json(text: str) -> dict:
                    """提取第一个完整的 JSON 对象，忽略后面的额外内容"""
                    # 方法1: 直接解析
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as e:
                        # 如果是 "Extra data" 错误，尝试只解析到第一个 JSON 结束位置
                        if "Extra data" in str(e):
                            # 找到第一个 { 开始，匹配括号找到结束位置
                            start = text.find('{')
                            if start >= 0:
                                depth = 0
                                for i in range(start, len(text)):
                                    if text[i] == '{':
                                        depth += 1
                                    elif text[i] == '}':
                                        depth -= 1
                                        if depth == 0:
                                            try:
                                                return json.loads(text[start:i+1])
                                            except json.JSONDecodeError:
                                                break

                    # 方法2: 查找 JSON 代码块
                    json_block = re.search(r'```json\s*([\s\S]*?)\s*```', text)
                    if json_block:
                        try:
                            return json.loads(json_block.group(1))
                        except json.JSONDecodeError:
                            pass

                    # 方法3: 贪婪匹配（最后手段）
                    json_match = re.search(r'\{[\s\S]*\}', text)
                    if json_match:
                        try:
                            return json.loads(json_match.group())
                        except json.JSONDecodeError:
                            pass

                    raise ValueError(f"Failed to parse LLM response as JSON: {text[:200]}")

                return extract_first_json(content)

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1 and "rate" in str(e).lower():
                await asyncio.sleep(3)
                continue
            raise

    raise last_error or ValueError("LLM call failed")


@router.post("/analyze/{document_id}")
async def analyze_document(document_id: str, db: Session = Depends(get_db)):
    """Stage 2: LLM1 分析文档"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.ocr_text:
        raise HTTPException(status_code=400, detail="Document not OCR'd yet")

    prompt = f"""Analyze this document and extract information.

DOCUMENT:
{doc.ocr_text}

Extract:
1. document_type: What type of document (Employment Contract, Financial Statement, etc.)
2. document_date: Date in YYYY-MM-DD format or null
3. entities: List of {{type, name, role, context}} where type is person/company/position/amount/date
4. tags: List of lowercase tags (employment, salary, executive, etc.)
5. key_quotes: List of {{text, page, topic}} with EXACT quotes from document
6. summary: 2-3 sentence objective description

Return JSON:
{{"document_type": "...", "document_date": "...", "entities": [...], "tags": [...], "key_quotes": [...], "summary": "..."}}
"""

    result = await call_llm(prompt)

    # Save to DB
    existing = db.query(DocumentAnalysis).filter(DocumentAnalysis.document_id == document_id).first()
    if existing:
        existing.document_type = result.get("document_type")
        existing.document_date = result.get("document_date")
        existing.entities_json = json.dumps(result.get("entities", []))
        existing.tags_json = json.dumps(result.get("tags", []))
        existing.key_quotes_json = json.dumps(result.get("key_quotes", []))
        existing.summary = result.get("summary")
        existing.analyzed_at = datetime.utcnow()
    else:
        analysis = DocumentAnalysis(
            document_id=document_id,
            document_type=result.get("document_type"),
            document_date=result.get("document_date"),
            entities_json=json.dumps(result.get("entities", [])),
            tags_json=json.dumps(result.get("tags", [])),
            key_quotes_json=json.dumps(result.get("key_quotes", [])),
            summary=result.get("summary"),
            analyzed_at=datetime.utcnow()
        )
        db.add(analysis)

    db.commit()

    # 同时保存到本地文件存储
    # 获取 project_id
    doc_project_id = doc.project_id
    analysis_to_save = {document_id: result}
    storage.save_analysis(doc_project_id, analysis_to_save)

    return {"success": True, "document_id": document_id, "analysis": result}


@router.get("/analysis/{document_id}")
async def get_analysis(document_id: str, db: Session = Depends(get_db)):
    """获取文档分析结果"""
    analysis = db.query(DocumentAnalysis).filter(DocumentAnalysis.document_id == document_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return {
        "document_id": document_id,
        "document_type": analysis.document_type,
        "document_date": analysis.document_date,
        "entities": json.loads(analysis.entities_json) if analysis.entities_json else [],
        "tags": json.loads(analysis.tags_json) if analysis.tags_json else [],
        "key_quotes": json.loads(analysis.key_quotes_json) if analysis.key_quotes_json else [],
        "summary": analysis.summary
    }


# ============== Stage 3: LLM2 Relationship ==============

class ManualRelationshipRequest(BaseModel):
    """手动关系分析结果请求"""
    entities: List[Dict[str, Any]]
    relations: List[Dict[str, Any]]
    evidence_chains: List[Dict[str, Any]]


@router.post("/relationship-manual/{project_id}")
async def save_manual_relationship(project_id: str, data: ManualRelationshipRequest):
    """保存手动关系分析结果

    接收前端粘贴的 JSON 分析结果并保存
    """
    relationship_data = {
        "entities": data.entities,
        "relations": data.relations,
        "evidence_chains": data.evidence_chains
    }

    # 保存到本地文件
    version_id = storage.save_relationship(project_id, relationship_data)

    return {
        "success": True,
        "project_id": project_id,
        "version_id": version_id,
        "saved": {
            "entities": len(data.entities),
            "relations": len(data.relations),
            "evidence_chains": len(data.evidence_chains)
        }
    }


async def _run_relationship_analysis_background(project_id: str, prompt: str):
    """后台运行关系分析任务"""
    global _relationship_progress

    _relationship_progress[project_id] = {
        "status": "processing",
        "result": None,
        "error": None
    }

    try:
        result = await call_llm(prompt)

        # 保存到本地文件
        storage.save_relationship(project_id, result)

        _relationship_progress[project_id] = {
            "status": "completed",
            "result": result,
            "error": None
        }
    except Exception as e:
        _relationship_progress[project_id] = {
            "status": "failed",
            "result": None,
            "error": str(e)
        }


@router.post("/relationship/{project_id}")
async def analyze_relationships(project_id: str, beneficiary_name: Optional[str] = None, db: Session = Depends(get_db)):
    """Stage 3: LLM2 分析实体关系 - 使用 L-1 专项分析的所有 quotes 数据

    现在返回 202 并在后台执行分析，使用 /relationship/stream/{project_id} 监控进度
    """
    global _relationship_progress

    # 检查是否已有分析在进行中
    if project_id in _relationship_progress:
        current_status = _relationship_progress[project_id].get("status")
        if current_status == "processing":
            return {
                "success": True,
                "message": "Relationship analysis already in progress",
                "project_id": project_id,
                "status": "processing"
            }

    # 从 L-1 专项分析加载所有 quotes（使用 load_l1_analysis 而不是 summary）
    l1_analyses = storage.load_l1_analysis(project_id)

    if l1_analyses and len(l1_analyses) > 0:
        # 使用 L-1 专项分析的所有 quotes 数据
        # l1_analyses 是一个列表，每个元素包含 document_id, exhibit_id, file_name, quotes

        docs_data = []
        for doc_analysis in l1_analyses:
            exhibit_id = doc_analysis.get("exhibit_id", "Unknown")
            file_name = doc_analysis.get("file_name", "Unknown")
            quotes = doc_analysis.get("quotes", [])

            if quotes:
                docs_data.append({
                    "exhibit_id": exhibit_id,
                    "file_name": file_name,
                    "quotes": quotes  # 保留完整的 quote 数据
                })

        if not docs_data:
            raise HTTPException(status_code=400, detail="No L-1 analysis quotes found. Run L-1 Analysis first.")

        beneficiary_ctx = f"\nBeneficiary: {beneficiary_name}\n" if beneficiary_name else ""

        prompt = f"""You are a Senior L-1 Immigration Paralegal. Analyze relationships between entities across the following L-1 visa evidence documents.

**L-1 Visa: 4 Core Legal Requirements:**
1. **Qualifying Corporate Relationship** - Parent/subsidiary/affiliate relationship between foreign and U.S. entities
2. **Qualifying Employment Abroad** - At least 1 year of continuous employment with the foreign entity in the past 3 years
3. **Qualifying Capacity** - L-1A (Executive/Managerial) or L-1B (Specialized Knowledge) role
4. **Doing Business (Active Operations)** - Both entities must be actively doing business
{beneficiary_ctx}
**DOCUMENTS WITH EXTRACTED QUOTES:**
{json.dumps(docs_data, indent=2, ensure_ascii=False)}

**Your Task:**
Based on the quotes extracted from the documents above, identify:
1. **Entities**: People, companies, positions mentioned across documents
2. **Relations**: Relationships between entities (e.g., "employed_by", "owns", "subsidiary_of", "manages")
3. **Evidence Chains**: How the documents support each L-1 standard (qualifying_relationship, qualifying_employment, qualifying_capacity, doing_business)

**Return JSON:**
{{
  "entities": [
    {{"id": "e1", "type": "person|company|position", "name": "...", "documents": ["exhibit_id"], "attributes": {{"role": "...", "title": "..."}}}}
  ],
  "relations": [
    {{"source_id": "e1", "target_id": "e2", "relation_type": "employed_by|owns|subsidiary_of|manages|founded", "evidence": ["exhibit_id"], "description": "..."}}
  ],
  "evidence_chains": [
    {{"claim": "Qualifying Corporate Relationship|Qualifying Employment Abroad|Qualifying Capacity|Doing Business", "documents": ["exhibit_id"], "strength": "strong|moderate|weak", "reasoning": "..."}}
  ]
}}
"""
    else:
        # 回退到原来的通用分析方式
        documents = db.query(Document).filter(Document.project_id == project_id).all()
        if not documents:
            raise HTTPException(status_code=404, detail="No documents found")

        # 收集分析数据
        docs_data = []
        for doc in documents:
            analysis = db.query(DocumentAnalysis).filter(DocumentAnalysis.document_id == doc.id).first()
            if analysis:
                docs_data.append({
                    "id": doc.id,
                    "exhibit": doc.exhibit_number,
                    "title": doc.exhibit_title,
                    "type": analysis.document_type,
                    "entities": json.loads(analysis.entities_json) if analysis.entities_json else [],
                    "tags": json.loads(analysis.tags_json) if analysis.tags_json else []
                })

        if not docs_data:
            raise HTTPException(status_code=400, detail="No analyzed documents. Run L-1 Analysis or general Analysis first.")

        beneficiary_ctx = f"\nBeneficiary: {beneficiary_name}\n" if beneficiary_name else ""

        prompt = f"""Analyze relationships between entities across these documents.
{beneficiary_ctx}
DOCUMENTS:
{json.dumps(docs_data, indent=2)}

Return JSON:
{{
  "entities": [{{"id": "e1", "type": "person", "name": "...", "documents": ["doc_id"], "attributes": {{}}}}],
  "relations": [{{"source_id": "e1", "target_id": "e2", "relation_type": "employed_by", "evidence": ["doc_id"], "description": "..."}}],
  "evidence_chains": [{{"claim": "Executive Capacity", "documents": ["doc_id"], "strength": "strong", "reasoning": "..."}}]
}}
"""

    # 启动后台任务
    asyncio.create_task(_run_relationship_analysis_background(project_id, prompt))

    return {
        "success": True,
        "message": "Started relationship analysis",
        "project_id": project_id,
        "documents_count": len(docs_data)
    }


@router.get("/relationship/stream/{project_id}")
async def stream_relationship_progress(project_id: str):
    """SSE 端点：实时推送关系分析进度

    返回 Server-Sent Events 流：
    - event: progress - 进度更新
    - event: complete - 分析完成
    """
    global _relationship_progress

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            # 获取当前进度
            progress_data = _relationship_progress.get(project_id)

            if not progress_data:
                # 没有分析任务，发送空状态并结束
                yield f"event: complete\ndata: {json.dumps({'project_id': project_id, 'status': 'idle'})}\n\n"
                break

            status = progress_data.get("status", "unknown")
            result = progress_data.get("result")
            error = progress_data.get("error")

            progress = {
                "project_id": project_id,
                "status": status,
                "error": error
            }

            # 检查是否完成
            if status == "completed":
                progress["result"] = result
                yield f"event: complete\ndata: {json.dumps(progress)}\n\n"
                break
            elif status == "failed":
                yield f"event: complete\ndata: {json.dumps(progress)}\n\n"
                break

            # 发送进度更新（处理中）
            yield f"event: progress\ndata: {json.dumps(progress)}\n\n"

            # 等待 1 秒后再次检查
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ============== Stage 4: LLM3 Writing ==============

@router.post("/write/{project_id}")
async def generate_writing(
    project_id: str,
    section_type: str,
    beneficiary_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Stage 4: LLM3 生成带引用的段落"""
    documents = db.query(Document).filter(Document.project_id == project_id).all()
    if not documents:
        raise HTTPException(status_code=404, detail="No documents found")

    # 收集证据
    evidence = []
    for doc in documents:
        analysis = db.query(DocumentAnalysis).filter(DocumentAnalysis.document_id == doc.id).first()
        if analysis:
            evidence.append({
                "exhibit": doc.exhibit_number,
                "title": doc.exhibit_title,
                "type": analysis.document_type,
                "entities": json.loads(analysis.entities_json) if analysis.entities_json else [],
                "quotes": json.loads(analysis.key_quotes_json) if analysis.key_quotes_json else []
            })

    if not evidence:
        raise HTTPException(status_code=400, detail="No analyzed documents")

    section_templates = {
        "executive_capacity": "Write about the beneficiary's executive capacity, focusing on high-level decision-making and strategic responsibilities.",
        "managerial_capacity": "Write about the beneficiary's managerial capacity, focusing on supervision and management duties.",
        "specialized_knowledge": "Write about the beneficiary's specialized knowledge that is critical to the organization.",
        "company_structure": "Write about the company structure and qualifying relationship.",
        "compensation": "Write about the compensation package and wage level.",
        "position_description": "Write about the position duties and responsibilities."
    }

    template = section_templates.get(section_type, "Write a paragraph for the petition.")
    beneficiary_ctx = f"Beneficiary: {beneficiary_name}\n" if beneficiary_name else ""

    prompt = f"""{template}
{beneficiary_ctx}
EVIDENCE:
{json.dumps(evidence, indent=2)}

Citation format: [Exhibit A-1: Title] for single, [Exhibits A-1, A-2: Description] for multiple.

Return JSON:
{{
  "paragraph_text": "The paragraph with [Exhibit X] citations...",
  "citations_used": [{{"exhibit_number": "A-1", "exhibit_title": "...", "reason": "..."}}]
}}
"""

    result = await call_llm(prompt)

    # 保存到本地文件
    text = result.get("paragraph_text", "")
    citations = result.get("citations_used", [])
    storage.save_writing(project_id, section_type, text, citations)

    return {
        "success": True,
        "section_type": section_type,
        "paragraph": {
            "text": text,
            "citations": citations,
            "section_type": section_type
        }
    }


# ============== 模型管理 ==============

@router.get("/models")
async def list_models():
    """获取可用模型列表"""
    global current_model
    return {
        "models": AVAILABLE_MODELS,
        "current": current_model
    }


@router.post("/models/{model_id}")
async def set_model(model_id: str):
    """设置当前使用的模型"""
    global current_model

    # 验证模型是否在可用列表中
    valid_ids = [m["id"] for m in AVAILABLE_MODELS]
    if model_id not in valid_ids:
        raise HTTPException(status_code=400, detail=f"Invalid model. Available: {valid_ids}")

    current_model = model_id
    return {
        "success": True,
        "current": current_model,
        "message": f"Model switched to {model_id}"
    }


# ============== LLM Provider 管理 ==============

# 可用的 LLM Providers
AVAILABLE_PROVIDERS = [
    {"id": "ollama", "name": "Ollama (本地)", "description": "本地 Ollama 服务 (推荐)"},
    {"id": "openai", "name": "OpenAI", "description": "OpenAI API"},
    {"id": "local", "name": "vLLM (本地)", "description": "本地 vLLM 服务"},
]


def get_current_llm_provider() -> str:
    """获取当前 LLM Provider（供其他模块导入使用）"""
    global LLM_PROVIDER
    return LLM_PROVIDER


def set_current_llm_provider(provider_id: str) -> bool:
    """设置当前 LLM Provider（供其他模块导入使用）"""
    global LLM_PROVIDER
    valid_ids = [p["id"] for p in AVAILABLE_PROVIDERS]
    if provider_id not in valid_ids:
        return False
    LLM_PROVIDER = provider_id
    return True


@router.get("/llm-providers")
async def list_llm_providers():
    """获取可用的 LLM Provider 列表"""
    global LLM_PROVIDER
    return {
        "providers": AVAILABLE_PROVIDERS,
        "current": LLM_PROVIDER
    }


@router.post("/llm-providers/{provider_id}")
async def set_llm_provider(provider_id: str):
    """切换 LLM Provider（运行时切换，重启后恢复默认）"""
    global LLM_PROVIDER

    # 验证 provider 是否有效
    valid_ids = [p["id"] for p in AVAILABLE_PROVIDERS]
    if provider_id not in valid_ids:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider_id}. Available: {valid_ids}")

    old_provider = LLM_PROVIDER
    LLM_PROVIDER = provider_id

    return {
        "success": True,
        "current": provider_id,
        "previous": old_provider,
        "message": f"LLM Provider switched from {old_provider} to {provider_id}"
    }


# ============== L-1 专项分析流水线 (整文档模式，无 Chunking) ==============


class ManualAnalysisRequest(BaseModel):
    """手动分析结果请求"""
    document_id: str
    exhibit_id: str
    file_name: str
    quotes: List[Dict[str, Any]]


async def _run_l1_analysis_background(project_id: str, doc_list: List[Dict[str, Any]]):
    """后台运行 L1 分析任务"""
    global _l1_analysis_progress, current_model

    total = len(doc_list)
    _l1_analysis_progress[project_id] = {
        "status": "processing",
        "total": total,
        "completed": 0,
        "current_doc": None,
        "errors": [],
        "results": [],
        "model_used": current_model
    }

    all_results = []
    errors = []

    for idx, doc_info in enumerate(doc_list):
        try:
            # 更新当前处理的文档
            _l1_analysis_progress[project_id]["current_doc"] = {
                "document_id": doc_info["document_id"],
                "file_name": doc_info["file_name"],
                "exhibit_id": doc_info["exhibit_id"]
            }

            # 生成 L-1 专项提示词（整文档模式）
            prompt = get_l1_analysis_prompt(doc_info)

            # 调用 LLM (带重试)
            llm_result = await call_llm(prompt, model_override=current_model, max_retries=3)

            # 解析结果
            parsed_quotes = parse_analysis_result(llm_result, doc_info)

            doc_result = {
                "document_id": doc_info["document_id"],
                "exhibit_id": doc_info["exhibit_id"],
                "file_name": doc_info["file_name"],
                "quotes": parsed_quotes
            }
            all_results.append(doc_result)

            # 更新进度
            _l1_analysis_progress[project_id]["completed"] = idx + 1
            _l1_analysis_progress[project_id]["results"] = all_results

            # 添加请求间隔以避免触发速率限制
            await asyncio.sleep(0.5)

        except Exception as e:
            error_info = {
                "document_id": doc_info["document_id"],
                "exhibit_id": doc_info["exhibit_id"],
                "error": str(e)
            }
            errors.append(error_info)
            _l1_analysis_progress[project_id]["errors"] = errors
            _l1_analysis_progress[project_id]["completed"] = idx + 1

    # 保存分析结果
    storage.save_l1_analysis(project_id, all_results)

    # 标记完成
    _l1_analysis_progress[project_id]["status"] = "completed"
    _l1_analysis_progress[project_id]["current_doc"] = None


@router.post("/l1-analyze/{project_id}")
async def l1_analyze_project(
    project_id: str,
    doc_ids: Optional[str] = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """Stage 2 (L-1 专项): 整文档 L-1 标准分析（无 Chunking）

    参数:
    - project_id: 项目 ID
    - doc_ids: 可选，逗号分隔的文档 ID 列表。如果不提供，分析所有已完成 OCR 的文档

    返回 202 并在后台执行分析，使用 /l1-analyze/stream/{project_id} 监控进度
    """
    global _l1_analysis_progress

    # 检查是否已有分析在进行中
    if project_id in _l1_analysis_progress:
        current_status = _l1_analysis_progress[project_id].get("status")
        if current_status == "processing":
            return {
                "success": True,
                "message": "L1 analysis already in progress",
                "project_id": project_id,
                "status": "processing"
            }

    # 基础查询
    query = db.query(Document).filter(
        Document.project_id == project_id,
        Document.ocr_status == OCRStatus.COMPLETED.value
    )

    # 如果提供了 doc_ids，只分析选中的文档
    if doc_ids:
        doc_id_list = [id.strip() for id in doc_ids.split(',') if id.strip()]
        if doc_id_list:
            query = query.filter(Document.id.in_(doc_id_list))

    documents = query.all()

    if not documents:
        raise HTTPException(status_code=404, detail="No documents found")

    # 准备文档信息列表（清理 OCR 文本中的垃圾数据，只影响 LLM 输入，不影响原始数据）
    doc_list = [
        {
            "document_id": doc.id,
            "exhibit_id": doc.exhibit_number or "X-1",
            "file_name": doc.file_name,
            "text": clean_ocr_for_llm(doc.ocr_text or "")
        }
        for doc in documents
    ]

    # 启动后台任务
    asyncio.create_task(_run_l1_analysis_background(project_id, doc_list))

    return {
        "success": True,
        "message": f"Started L1 analysis for {len(documents)} documents",
        "project_id": project_id,
        "total": len(documents),
        "documents": [
            {"id": doc.id, "file_name": doc.file_name, "exhibit_id": doc.exhibit_number}
            for doc in documents
        ]
    }


@router.get("/l1-analyze/stream/{project_id}")
async def stream_l1_analysis_progress(project_id: str):
    """SSE 端点：实时推送 L1 分析进度

    返回 Server-Sent Events 流：
    - event: progress - 进度更新
    - event: complete - 分析全部完成
    """
    global _l1_analysis_progress

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            # 获取当前进度
            progress_data = _l1_analysis_progress.get(project_id)

            if not progress_data:
                # 没有分析任务，发送空状态并结束
                yield f"event: complete\ndata: {json.dumps({'project_id': project_id, 'status': 'idle', 'total': 0, 'completed': 0})}\n\n"
                break

            status = progress_data.get("status", "unknown")
            total = progress_data.get("total", 0)
            completed = progress_data.get("completed", 0)
            current_doc = progress_data.get("current_doc")
            errors = progress_data.get("errors", [])
            results = progress_data.get("results", [])
            model_used = progress_data.get("model_used", "")

            progress = {
                "project_id": project_id,
                "status": status,
                "total": total,
                "completed": completed,
                "progress_percent": round(completed / total * 100, 1) if total > 0 else 0,
                "current_doc": current_doc,
                "errors": errors,
                "total_quotes_found": sum(len(r.get("quotes", [])) for r in results),
                "model_used": model_used
            }

            # 检查是否完成
            if status == "completed":
                yield f"event: complete\ndata: {json.dumps(progress)}\n\n"
                break

            # 发送进度更新
            yield f"event: progress\ndata: {json.dumps(progress)}\n\n"

            # 等待 1 秒后再次检查
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/l1-analyze/progress/{project_id}")
async def get_l1_analysis_progress(project_id: str):
    """获取 L1 分析进度（非 SSE，用于检查状态）"""
    global _l1_analysis_progress

    progress_data = _l1_analysis_progress.get(project_id)

    if not progress_data:
        return {
            "project_id": project_id,
            "status": "idle",
            "total": 0,
            "completed": 0
        }

    results = progress_data.get("results", [])

    return {
        "project_id": project_id,
        "status": progress_data.get("status", "unknown"),
        "total": progress_data.get("total", 0),
        "completed": progress_data.get("completed", 0),
        "progress_percent": round(progress_data.get("completed", 0) / progress_data.get("total", 1) * 100, 1),
        "current_doc": progress_data.get("current_doc"),
        "errors": progress_data.get("errors", []),
        "total_quotes_found": sum(len(r.get("quotes", [])) for r in results),
        "model_used": progress_data.get("model_used", "")
    }


@router.post("/l1-manual-analysis/{project_id}")
async def save_manual_analysis(project_id: str, analyses: List[ManualAnalysisRequest]):
    """保存手动分析结果

    接收前端粘贴的 JSON 分析结果并保存
    """
    all_results = []

    for analysis in analyses:
        doc_result = {
            "document_id": analysis.document_id,
            "exhibit_id": analysis.exhibit_id,
            "file_name": analysis.file_name,
            "quotes": analysis.quotes
        }
        all_results.append(doc_result)

    # 加载现有分析结果（如果有）并合并
    existing = storage.load_l1_analysis(project_id) or []

    # 按 document_id 更新或添加
    existing_ids = {r.get("document_id") for r in existing}
    for new_result in all_results:
        if new_result["document_id"] in existing_ids:
            # 更新现有结果
            for i, r in enumerate(existing):
                if r.get("document_id") == new_result["document_id"]:
                    existing[i] = new_result
                    break
        else:
            # 添加新结果
            existing.append(new_result)

    # 保存合并后的结果
    storage.save_l1_analysis(project_id, existing)

    return {
        "success": True,
        "project_id": project_id,
        "saved_count": len(all_results),
        "total_quotes": sum(len(a.quotes) for a in analyses)
    }


@router.post("/l1-summary/{project_id}")
async def l1_summary_project(project_id: str):
    """Stage 3 (L-1 专项): 汇总所有分析结果 - 本地处理，不调用 LLM"""
    # 从本地文件加载分析结果
    chunk_analyses = storage.load_l1_analysis(project_id)

    if not chunk_analyses:
        raise HTTPException(status_code=404, detail="No L-1 analysis found. Run /l1-analyze first.")

    # 合并和去重
    merged = merge_chunk_analyses(chunk_analyses)

    # 生成汇总报告
    summary = generate_summary(merged, project_id)

    # 保存汇总结果
    storage.save_l1_summary(project_id, summary)

    return {
        "success": True,
        "project_id": project_id,
        "summary": summary
    }


@router.get("/l1-summary/{project_id}")
async def get_l1_summary(project_id: str):
    """获取 L-1 汇总结果"""
    summary = storage.load_l1_summary(project_id)

    if not summary:
        raise HTTPException(status_code=404, detail="No L-1 summary found")

    return summary


@router.get("/l1-standards")
async def get_l1_standards():
    """获取 L-1 四大标准的详细信息"""
    return {
        "standards": L1_STANDARDS,
        "count": len(L1_STANDARDS)
    }


@router.get("/l1-status/{project_id}")
async def get_l1_status(project_id: str):
    """获取 L-1 分析流程状态 - 用于判断哪些按钮应该启用"""
    # 检查是否有 L-1 分析结果
    analysis = storage.load_l1_analysis(project_id)
    has_analysis = analysis is not None and len(analysis) > 0

    # 检查是否有 L-1 汇总结果
    summary = storage.load_l1_summary(project_id)
    has_summary = summary is not None and summary.get('total_quotes', 0) > 0

    return {
        "has_analysis": has_analysis,
        "analysis_chunks": len(analysis) if analysis else 0,
        "has_summary": has_summary,
        "summary_quotes": summary.get('total_quotes', 0) if summary else 0
    }


@router.post("/l1-write/{project_id}")
async def l1_write_section(
    project_id: str,
    section_type: str,
    beneficiary_name: Optional[str] = None
):
    """Stage 4 (L-1 专项): 基于汇总结果生成带引用的段落"""
    # 加载汇总结果
    summary = storage.load_l1_summary(project_id)

    if not summary:
        raise HTTPException(status_code=404, detail="No L-1 summary found. Run /l1-summary first.")

    # 准备证据材料
    by_standard = summary.get("by_standard", {})
    evidence = prepare_for_writing(by_standard, section_type)

    if not evidence.get("quotes"):
        raise HTTPException(status_code=400, detail=f"No relevant quotes found for section: {section_type}")

    # 构建撰写提示词
    beneficiary_name_str = beneficiary_name if beneficiary_name else "[Beneficiary]"
    petitioner_name = "Kings Elevator Parts Inc."  # TODO: 从项目配置中获取

    prompt = f"""You are a Senior Immigration Attorney at a top-tier U.S. law firm. Your task is to write a single, persuasive paragraph for an L-1 Petition Letter.

You will write *only* for the specific section requested, using *only* the evidence provided.

**1. Available Evidence (JSON):**
(This JSON contains all relevant quotes extracted from the client's documents)
{json.dumps(evidence["quotes"], indent=2, ensure_ascii=False)}

**2. Context for this Task:**
* **Section to Write:** {section_type}
    *(e.g., "Qualifying Corporate Relationship", "Beneficiary's Managerial Capacity Abroad", "Petitioner's Active Operations")*
* **Beneficiary Name:** {beneficiary_name_str}
* **Petitioner Name:** {petitioner_name}

**3. Strict Instructions:**

* **Language:** You must write in formal, professional, and persuasive legal English.
* **Focus:** The `paragraph_text` must *only* address the `{section_type}`. Do not include facts or arguments irrelevant to this specific legal standard.
* **Evidence-Based:** Your argument *must* be built by synthesizing one or more `quote` fields from the Evidence JSON. Do not make any claims that are not directly supported by the provided quotes.
* **Inline Citations (MANDATORY):**
    1.  Every factual claim you make in the `paragraph_text` *must* be followed by an inline citation.
    2.  You will create the citation using the `source` object (which contains `exhibit_id` and `file_name`) found within the Evidence JSON.
    3.  **Citation Format:** `[Exhibit {{exhibit_id}}: {{file_name}}]`
* **Output Format:** You *must* provide your response as a single JSON object matching the exact structure specified below.

**4. Required Output Format (JSON):**

{{
  "paragraph_text": "The generated paragraph text, complete with inline citations. For example: The Petitioner, {petitioner_name}, has secured a physical office space [Exhibit A-1: Commercial Lease] and has been actively doing business since its incorporation [Exhibit A-2: NYS DOS Filing]...",
  "citations_used": [
    {{
      "exhibit": "A-1",
      "file_name": "Commercial Lease",
      "quote": "The specific quote from the evidence_json that was used...",
      "claim": "A brief summary of the specific fact supported by this quote (e.g., 'Petitioner secured a physical office.')"
    }}
  ]
}}
"""

    global current_model
    result = await call_llm(prompt, model_override=current_model)

    # 保存撰写结果
    text = result.get("paragraph_text", "")
    citations = result.get("citations_used", [])
    storage.save_writing(project_id, section_type, text, citations)

    return {
        "success": True,
        "section_type": section_type,
        "paragraph": {
            "text": text,
            "citations": citations,
            "section_type": section_type
        }
    }


class ManualWritingRequest(BaseModel):
    """手动撰写结果请求"""
    section_type: str
    paragraph_text: str
    citations_used: List[Dict[str, Any]]


@router.post("/l1-write-manual/{project_id}")
async def save_manual_writing(project_id: str, data: ManualWritingRequest):
    """保存手动撰写结果

    接收前端粘贴的 JSON 撰写结果并保存
    """
    # 保存到本地文件
    storage.save_writing(project_id, data.section_type, data.paragraph_text, data.citations_used)

    return {
        "success": True,
        "project_id": project_id,
        "section_type": data.section_type,
        "saved": {
            "paragraph_length": len(data.paragraph_text),
            "citations_count": len(data.citations_used)
        }
    }


@router.get("/l1-writing/{project_id}")
async def get_writing_results(project_id: str):
    """获取项目的所有撰写结果"""
    results = storage.load_all_writing(project_id)

    if not results:
        return {"project_id": project_id, "sections": {}, "count": 0}

    return {
        "project_id": project_id,
        "sections": results,
        "count": len(results)
    }


# ============== 样式模板 API ==============

class ParseStyleRequest(BaseModel):
    """解析样式请求"""
    section: str
    sample_text: str


class SaveStyleTemplateRequest(BaseModel):
    """保存样式模板请求"""
    section: str
    name: str
    original_text: str
    parsed_structure: str


class UpdateStyleTemplateRequest(BaseModel):
    """更新样式模板请求"""
    name: Optional[str] = None
    parsed_structure: Optional[str] = None


@router.post("/style-templates/parse")
async def parse_style_template(data: ParseStyleRequest):
    """解析例文结构

    用户粘贴例文，LLM 解析出结构和公式，用占位符替代具体内容
    """
    section_names = {
        "qualifying_relationship": "Qualifying Corporate Relationship & Physical Premises",
        "qualifying_employment": "Qualifying Employment Abroad",
        "qualifying_capacity": "Qualifying Capacity (Executive/Managerial)",
        "doing_business": "Doing Business / Active Operations"
    }

    section_name = section_names.get(data.section, data.section)

    prompt = f"""You are a legal writing expert. Analyze the following sample paragraph from an L-1 visa petition letter and extract its structural template.

**Section Type:** {section_name}

**Sample Paragraph:**
{data.sample_text}

**Your Task:**
1. Identify the rhetorical structure and flow of the paragraph
2. Extract the "formula" or pattern used
3. Replace specific facts with descriptive placeholders

**Placeholder Format:**
- Use brackets with descriptive names: [COMPANY_NAME], [DATE], [AMOUNT], [POSITION], etc.
- Keep legal phrases and transitional words intact
- Preserve the sentence structure and flow

**Output Format (JSON):**
{{
  "structure_analysis": "A brief description of the paragraph's structure and approach (2-3 sentences)",
  "template": "The paragraph with all specific facts replaced by [PLACEHOLDERS]. Keep all legal language, transitions, and rhetorical devices intact.",
  "placeholders": [
    {{
      "name": "[PLACEHOLDER_NAME]",
      "description": "What type of information goes here",
      "example": "The original text that was replaced"
    }}
  ]
}}
"""

    global current_model
    result = await call_llm(prompt, model_override=current_model)

    return {
        "success": True,
        "section": data.section,
        "parsed": result
    }


@router.post("/style-templates")
async def create_style_template(data: SaveStyleTemplateRequest):
    """保存样式模板到后端"""
    template = save_style_template(
        section=data.section,
        name=data.name,
        original_text=data.original_text,
        parsed_structure=data.parsed_structure
    )

    return {
        "success": True,
        "template": template
    }


@router.get("/style-templates")
async def list_style_templates(section: Optional[str] = None):
    """获取样式模板列表

    可选参数 section 过滤指定段落类型的模板
    """
    templates = get_style_templates(section)

    return {
        "templates": templates,
        "count": len(templates)
    }


@router.get("/style-templates/{template_id}")
async def get_style_template_by_id(template_id: str):
    """获取单个样式模板"""
    template = get_style_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return template


@router.patch("/style-templates/{template_id}")
async def update_style_template_by_id(template_id: str, data: UpdateStyleTemplateRequest):
    """更新样式模板"""
    updates = {}
    if data.name is not None:
        updates['name'] = data.name
    if data.parsed_structure is not None:
        updates['parsed_structure'] = data.parsed_structure

    template = update_style_template(template_id, updates)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "success": True,
        "template": template
    }


@router.delete("/style-templates/{template_id}")
async def delete_style_template_by_id(template_id: str):
    """删除样式模板"""
    success = delete_style_template(template_id)

    if not success:
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "success": True,
        "deleted": template_id
    }


# ============== Health Check ==============

@router.get("/health")
async def health_check():
    """健康检查"""
    global current_model
    baidu_status = "configured" if BAIDU_OCR_API_KEY and BAIDU_OCR_SECRET_KEY else "not_configured"
    openai_status = "configured" if OPENAI_API_KEY else "not_configured"
    deepseek_ocr_status = "available" if deepseek_ocr.is_available() else "not_available"

    # 获取预加载状态
    preload_state = get_preload_state()

    return {
        "status": "healthy",
        "ocr_provider": OCR_PROVIDER,
        "baidu_ocr": baidu_status,
        "deepseek_ocr": deepseek_ocr_status,
        "llm_provider": LLM_PROVIDER,
        "llm_model": current_model,
        "available_models": [m["id"] for m in AVAILABLE_MODELS],
        "openai": openai_status,
        "models_ready": preload_state.is_ready,
        "models_loading": preload_state.is_loading,
    }


@router.get("/preload-status")
async def get_preload_status():
    """获取模型预加载状态

    返回 OCR 和 LLM 模型的加载状态，前端可用于显示加载进度
    """
    state = get_preload_state()
    return state.to_dict()


# ============== BBox 匹配 API ==============

class MatchBBoxRequest(BaseModel):
    """BBox 匹配请求"""
    quotes: List[Dict[str, Any]]  # [{"quote": "...", "page": 1}, ...]
    similarity_threshold: Optional[float] = 0.7


@router.post("/match-bbox/{document_id}")
async def match_bbox(document_id: str, data: MatchBBoxRequest, db: Session = Depends(get_db)):
    """
    将 quotes 匹配到文档的 text_blocks，获取 BBox 坐标

    用于 Inline Provenance 功能：点击引用 → 跳转 PDF 页面 → 高亮对应区域

    请求体:
    {
        "quotes": [
            {"quote": "原文引用内容...", "page": 1}
        ],
        "similarity_threshold": 0.7
    }

    响应:
    {
        "document_id": "xxx",
        "matches": [
            {
                "quote": "原文引用内容...",
                "page_hint": 1,
                "matched": true,
                "matches": [
                    {
                        "block_id": "p1_b3",
                        "page_number": 1,
                        "bbox": {"x1": 10, "y1": 20, "x2": 100, "y2": 50},
                        "match_type": "exact",
                        "match_score": 1.0
                    }
                ]
            }
        ],
        "stats": {
            "total_quotes": 5,
            "matched_count": 4,
            "match_rate": 0.8
        }
    }
    """
    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 检查是否有 text_blocks
    block_count = db.query(TextBlock).filter(TextBlock.document_id == document_id).count()
    if block_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No text blocks found. Document may not have been processed with DeepSeek-OCR."
        )

    # 执行批量匹配
    results = bbox_matcher.batch_match_quotes(
        quotes=data.quotes,
        document_id=document_id,
        db=db,
        similarity_threshold=data.similarity_threshold or 0.7
    )

    # 统计
    total = len(results)
    matched = sum(1 for r in results if r.get("matched"))

    return {
        "document_id": document_id,
        "matches": results,
        "stats": {
            "total_quotes": total,
            "matched_count": matched,
            "match_rate": round(matched / total, 2) if total > 0 else 0
        }
    }


@router.get("/document/{document_id}/file")
async def get_document_file(document_id: str, db: Session = Depends(get_db)):
    """
    获取文档的原始文件（用于预览）

    返回文件的二进制内容，支持 PDF 和图片
    """
    from fastapi.responses import Response

    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 加载原始文件
    file_bytes = storage.load_uploaded_file(doc.project_id, document_id)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File not found in storage")

    # 确定 content type
    content_type = doc.file_type or "application/octet-stream"

    # 如果是 PDF，可能需要特殊处理
    if doc.file_name.lower().endswith('.pdf'):
        content_type = "application/pdf"
    elif doc.file_name.lower().endswith(('.jpg', '.jpeg')):
        content_type = "image/jpeg"
    elif doc.file_name.lower().endswith('.png'):
        content_type = "image/png"
    elif doc.file_name.lower().endswith('.gif'):
        content_type = "image/gif"

    return Response(
        content=file_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": f"inline; filename=\"{doc.file_name}\""
        }
    )


@router.get("/text-blocks/{document_id}")
async def get_text_blocks(document_id: str, page: Optional[int] = None, db: Session = Depends(get_db)):
    """
    获取文档的所有 text_blocks

    可选参数 page 过滤指定页码
    """
    query = db.query(TextBlock).filter(TextBlock.document_id == document_id)

    if page is not None:
        query = query.filter(TextBlock.page_number == page)

    blocks = query.order_by(TextBlock.page_number, TextBlock.block_id).all()

    return {
        "document_id": document_id,
        "total": len(blocks),
        "page_filter": page,
        "blocks": [
            {
                "block_id": b.block_id,
                "page_number": b.page_number,
                "block_type": b.block_type,
                "text_content": b.text_content,
                "bbox": {
                    "x1": b.bbox_x1,
                    "y1": b.bbox_y1,
                    "x2": b.bbox_x2,
                    "y2": b.bbox_y2
                }
            }
            for b in blocks
        ]
    }


# ============== Chunked Upload API ==============
# 分块上传 API，用于大文件上传

import os
import shutil
from pathlib import Path

# 分块临时存储目录
CHUNKS_DIR = Path(__file__).parent.parent.parent / "data" / "chunks"

# 存储上传会话元信息
_upload_sessions: Dict[str, Dict[str, Any]] = {}


class InitUploadRequest(BaseModel):
    project_id: str
    file_name: str
    file_size: int
    total_chunks: int
    exhibit_number: Optional[str] = None
    exhibit_title: Optional[str] = None


class InitUploadResponse(BaseModel):
    upload_id: str
    chunk_size: int


class ChunkUploadResponse(BaseModel):
    success: bool
    upload_id: str
    chunk_index: int
    chunks_received: int
    total_chunks: int


@router.post("/upload/init", response_model=InitUploadResponse)
async def init_chunked_upload(request: InitUploadRequest):
    """初始化分块上传，返回 upload_id"""
    upload_id = str(uuid.uuid4())

    # 创建临时目录
    upload_dir = CHUNKS_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 保存上传会话信息
    _upload_sessions[upload_id] = {
        "project_id": request.project_id,
        "file_name": request.file_name,
        "file_size": request.file_size,
        "total_chunks": request.total_chunks,
        "exhibit_number": request.exhibit_number,
        "exhibit_title": request.exhibit_title,
        "chunks_received": set(),
        "created_at": datetime.now().isoformat()
    }

    # 5MB chunk size
    chunk_size = 5 * 1024 * 1024

    return InitUploadResponse(
        upload_id=upload_id,
        chunk_size=chunk_size
    )


@router.post("/upload/chunk/{upload_id}/{chunk_index}", response_model=ChunkUploadResponse)
async def upload_chunk(
    upload_id: str,
    chunk_index: int,
    chunk: UploadFile = File(...)
):
    """上传单个分块"""
    if upload_id not in _upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session = _upload_sessions[upload_id]

    if chunk_index >= session["total_chunks"]:
        raise HTTPException(status_code=400, detail="Invalid chunk index")

    # 保存分块
    upload_dir = CHUNKS_DIR / upload_id
    chunk_path = upload_dir / f"chunk_{chunk_index:06d}"

    chunk_data = await chunk.read()
    with open(chunk_path, 'wb') as f:
        f.write(chunk_data)

    # 更新会话
    session["chunks_received"].add(chunk_index)

    return ChunkUploadResponse(
        success=True,
        upload_id=upload_id,
        chunk_index=chunk_index,
        chunks_received=len(session["chunks_received"]),
        total_chunks=session["total_chunks"]
    )


@router.post("/upload/complete/{upload_id}", response_model=DocumentResponse)
async def complete_chunked_upload(upload_id: str, db: Session = Depends(get_db)):
    """完成分块上传，合并分块并创建文档"""
    if upload_id not in _upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session = _upload_sessions[upload_id]

    # 检查是否所有分块都已上传
    if len(session["chunks_received"]) != session["total_chunks"]:
        missing = set(range(session["total_chunks"])) - session["chunks_received"]
        raise HTTPException(
            status_code=400,
            detail=f"Missing chunks: {sorted(missing)}"
        )

    # 合并分块
    upload_dir = CHUNKS_DIR / upload_id
    merged_data = bytearray()

    for i in range(session["total_chunks"]):
        chunk_path = upload_dir / f"chunk_{i:06d}"
        with open(chunk_path, 'rb') as f:
            merged_data.extend(f.read())

    file_bytes = bytes(merged_data)
    file_name = session["file_name"]

    # 确定文件类型
    if file_name.lower().endswith('.pdf'):
        file_type = "application/pdf"
    elif file_name.lower().endswith('.png'):
        file_type = "image/png"
    elif file_name.lower().endswith(('.jpg', '.jpeg')):
        file_type = "image/jpeg"
    elif file_name.lower().endswith(('.tif', '.tiff')):
        file_type = "image/tiff"
    else:
        file_type = "application/octet-stream"

    # 创建文档记录
    document = Document(
        id=str(uuid.uuid4()),
        project_id=session["project_id"],
        file_name=file_name,
        file_type=file_type,
        file_size=len(file_bytes),
        ocr_status=OCRStatus.PENDING.value,
        ocr_provider=OCR_PROVIDER,
        exhibit_number=session["exhibit_number"],
        exhibit_title=session["exhibit_title"] or file_name.replace('.', '_')
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    # 保存原始文件到本地存储
    storage.save_uploaded_file(session["project_id"], document.id, file_bytes, file_name)

    # 清理临时文件
    try:
        shutil.rmtree(upload_dir)
    except Exception as e:
        print(f"[Chunked Upload] Warning: Failed to clean up temp dir: {e}")

    # 清理会话
    del _upload_sessions[upload_id]

    return DocumentResponse(
        id=document.id,
        project_id=document.project_id,
        file_name=document.file_name,
        file_type=document.file_type,
        file_size=document.file_size,
        page_count=document.page_count or 0,
        ocr_text=document.ocr_text,
        ocr_status=document.ocr_status,
        exhibit_number=document.exhibit_number,
        exhibit_title=document.exhibit_title,
        created_at=document.created_at
    )


@router.delete("/upload/cancel/{upload_id}")
async def cancel_chunked_upload(upload_id: str):
    """取消分块上传，清理临时文件"""
    if upload_id not in _upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    # 清理临时文件
    upload_dir = CHUNKS_DIR / upload_id
    try:
        if upload_dir.exists():
            shutil.rmtree(upload_dir)
    except Exception as e:
        print(f"[Chunked Upload] Warning: Failed to clean up temp dir: {e}")

    # 清理会话
    del _upload_sessions[upload_id]

    return {"success": True, "message": "Upload cancelled"}


