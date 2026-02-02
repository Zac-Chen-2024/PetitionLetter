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
from app.models.document import Document, DocumentAnalysis, OCRStatus, TextBlock, Highlight
from app.services import storage
from app.services import deepseek_ocr
from app.services import bbox_matcher
from app.services import page_cache
from app.services.ocr_queue import ocr_queue
from app.services.storage import (
    save_style_template, get_style_templates, get_style_template,
    delete_style_template, update_style_template
)
from app.services.l1_analyzer import (
    get_l1_analysis_prompt, parse_analysis_result, L1_STANDARDS, clean_ocr_for_llm,
    get_l1_analysis_prompt_for_material, parse_material_analysis_result,
    MaterialAnalysisResult, save_material_analysis,
    get_l1_analysis_prompt_for_material_with_blocks
)
from app.services.quote_merger import merge_chunk_analyses, generate_summary, prepare_for_writing, format_citation
from app.services.quote_consolidator import (
    consolidate_all_document_quotes,
    enrich_all_quotes_with_bbox,
    consolidate_all_quotes_with_llm,
    consolidate_material_quotes,
    consolidate_all_material_quotes,
    enrich_quotes_with_bbox
)
from app.services.model_preloader import get_preload_state

# New imports for material-based pipeline
from app.services.material_splitter import (
    split_exhibit_into_materials,
    load_ocr_pages_for_document,
    save_materials,
    load_materials,
    load_all_materials_for_project,
    Material
)
from app.services.highlight_analyzer import (
    analyze_material_highlights,
    analyze_all_materials,
    save_highlight_results,
    load_highlight_result,
    load_all_highlight_results,
    get_highlight_context_for_l1,
    HighlightResult
)

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


async def _run_relationship_analysis_background(
    project_id: str,
    quotes: List[Dict],
    quote_index_map: Dict = None,
    force_restart: bool = False
):
    """后台运行关系分析任务 - 使用增量式分析器（支持断点续传）"""
    global _relationship_progress
    from app.services.relationship_analyzer import run_relationship_analysis, RelationshipCheckpoint

    # 创建 checkpoint 管理器
    checkpoint = RelationshipCheckpoint(project_id)

    # 如果强制重启，清除旧的 checkpoint
    if force_restart:
        checkpoint.clear()
        print(f"[Relationship] 强制重启，清除旧的 checkpoint")

    # 检查是否有有效断点可恢复
    has_checkpoint = checkpoint.has_valid_checkpoint()
    if has_checkpoint:
        # 从 checkpoint 恢复 quotes 和 quote_index_map
        saved_quotes = checkpoint.get_quotes_list()
        saved_quote_map = checkpoint.get_quote_index_map()
        if saved_quotes:
            quotes = saved_quotes
            quote_index_map = saved_quote_map
        checkpoint_progress = checkpoint.get_progress()
        print(f"[Relationship] 检测到断点: 已完成 {checkpoint_progress['completed']}/{checkpoint_progress['total']} 批次")

    _relationship_progress[project_id] = {
        "status": "processing",
        "result": None,
        "error": None,
        "progress": {"current": 0, "total": 0, "message": "初始化..."},
        "resumed": has_checkpoint
    }

    def progress_callback(current, total, message):
        _relationship_progress[project_id]["progress"] = {
            "current": current,
            "total": total,
            "message": message
        }

    try:
        result = await run_relationship_analysis(
            quotes=quotes,
            progress_callback=progress_callback,
            checkpoint=checkpoint,
            quote_index_map=quote_index_map
        )

        # 保存到本地文件
        storage.save_relationship(project_id, result)

        # 同时保存引用索引映射（用于 bbox 回溯）
        if quote_index_map:
            storage.save_quote_index_map(project_id, quote_index_map)

        _relationship_progress[project_id] = {
            "status": "completed",
            "result": result,
            "error": None
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        # 标记 checkpoint 失败但保留状态以便恢复
        checkpoint.mark_failed(str(e))
        _relationship_progress[project_id] = {
            "status": "failed",
            "result": None,
            "error": str(e)
        }


@router.post("/relationship/{project_id}")
async def analyze_relationships(
    project_id: str,
    beneficiary_name: Optional[str] = None,
    force: bool = False,
    db: Session = Depends(get_db)
):
    """Stage 3: LLM2 分析实体关系 - 使用 L-1 专项分析的所有 quotes 数据

    现在返回 202 并在后台执行分析，使用 /relationship/stream/{project_id} 监控进度

    Query Parameters:
        force: 如果为 true，强制从头开始分析（忽略断点）
    """
    global _relationship_progress
    from app.services.relationship_analyzer import RelationshipCheckpoint

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

    # 检查是否有断点可恢复
    checkpoint = RelationshipCheckpoint(project_id)
    has_checkpoint = checkpoint.has_valid_checkpoint() and not force

    if has_checkpoint:
        # 从断点恢复，使用 checkpoint 中保存的 quotes
        checkpoint_progress = checkpoint.get_progress()
        quotes_list = checkpoint.get_quotes_list()
        quote_index_map = checkpoint.get_quote_index_map()

        if not quotes_list:
            # checkpoint 数据不完整，需要重新加载
            has_checkpoint = False
        else:
            print(f"[Relationship] 从断点恢复: 已完成 {checkpoint_progress['completed']}/{checkpoint_progress['total']} 批次")

    if not has_checkpoint:
        # 从 L-1 专项分析加载所有 quotes（支持新版材料级分析格式）
        l1_analyses = storage.load_l1_analysis(project_id)

        if not l1_analyses or len(l1_analyses) == 0:
            raise HTTPException(status_code=400, detail="No L-1 analysis found. Run L-1 Analysis first.")

        # v3.0: 构建引用列表，用于增量式关系分析
        quotes_list = []  # 传给分析器的引用列表
        quote_index_map = {}  # idx -> 完整引用数据（用于 bbox 回溯）

        idx = 0
        for doc_analysis in l1_analyses:
            exhibit_id = doc_analysis.get("exhibit_id", "Unknown")
            quotes = doc_analysis.get("quotes", [])

            for q in quotes:
                # 构建引用对象
                quotes_list.append({
                    "quote": q.get("quote", ""),
                    "standard_key": q.get("standard_key", ""),
                    "exhibit_id": exhibit_id,
                    "page": q.get("page"),
                })

                # 保存完整信息用于回溯
                quote_index_map[idx] = {
                    "exhibit_id": exhibit_id,
                    "material_id": q.get("source", {}).get("material_id", ""),
                    "page": q.get("page"),
                    "quote": q.get("quote", ""),
                    "standard_key": q.get("standard_key", ""),
                    "bbox": q.get("bbox")
                }
                idx += 1

        print(f"[Relationship] 加载引用: {len(quotes_list)} 条")

        if not quotes_list:
            raise HTTPException(status_code=400, detail="No quotes found in L-1 analysis.")

    item_count = len(quotes_list)

    # 启动后台任务 - 使用增量式分析器（支持断点续传）
    asyncio.create_task(_run_relationship_analysis_background(
        project_id, quotes_list, quote_index_map, force_restart=force
    ))

    return {
        "success": True,
        "message": "Resuming relationship analysis from checkpoint" if has_checkpoint else "Started relationship analysis",
        "project_id": project_id,
        "quotes_count": item_count,
        "resumed_from_checkpoint": has_checkpoint
    }


@router.delete("/relationship/checkpoint/{project_id}")
async def delete_relationship_checkpoint(project_id: str):
    """删除关系分析的断点，下次分析将从头开始"""
    from app.services.relationship_analyzer import RelationshipCheckpoint

    checkpoint = RelationshipCheckpoint(project_id)
    had_checkpoint = checkpoint.has_valid_checkpoint()
    checkpoint.clear()

    return {
        "success": True,
        "message": "Checkpoint cleared" if had_checkpoint else "No checkpoint found",
        "project_id": project_id,
        "had_checkpoint": had_checkpoint
    }


@router.get("/relationship/checkpoint/{project_id}")
async def get_relationship_checkpoint_status(project_id: str):
    """获取关系分析断点状态"""
    from app.services.relationship_analyzer import RelationshipCheckpoint

    checkpoint = RelationshipCheckpoint(project_id)

    if not checkpoint.has_valid_checkpoint():
        return {
            "success": True,
            "project_id": project_id,
            "has_checkpoint": False,
            "progress": None
        }

    progress = checkpoint.get_progress()
    return {
        "success": True,
        "project_id": project_id,
        "has_checkpoint": True,
        "progress": progress
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


async def _run_l1_analysis_background(
    project_id: str,
    doc_list: List[Dict[str, Any]],
    force_restart: bool = False
):
    """后台运行 L1 分析任务 - 支持语义分组模式和断点续传"""
    global _l1_analysis_progress, current_model

    # 导入语义分组函数和 checkpoint
    from app.services.l1_analyzer import (
        should_use_page_mode, load_ocr_pages, group_pages_semantically,
        LONG_DOC_THRESHOLD, MAX_PAGE_GROUP_SIZE, L1AnalysisCheckpoint
    )
    from app.services.quote_merger import merge_page_group_results

    MAX_RETRIES = 3  # 单文档最大重试次数

    # 创建 checkpoint 管理器
    checkpoint = L1AnalysisCheckpoint(project_id)

    # 如果强制重启，清除旧的 checkpoint
    if force_restart:
        checkpoint.clear()
        checkpoint = L1AnalysisCheckpoint(project_id)  # 重新创建
        print(f"[L1] 强制重启，清除旧的 checkpoint")

    # 检查是否有断点可恢复
    has_checkpoint = checkpoint.has_valid_checkpoint()
    if has_checkpoint:
        # 从 checkpoint 恢复
        saved_doc_list = checkpoint.get_doc_list()
        if saved_doc_list:
            doc_list = saved_doc_list
        resume_info = checkpoint.get_resume_info()
        print(f"[L1] 从断点恢复: 已完成 {resume_info['completed_count']}/{resume_info['total']} 文档")
        # 加载已完成的结果
        all_results = checkpoint.get_all_results()
    else:
        all_results = []
        # 初始化新的 checkpoint
        checkpoint.init_new(doc_list)
        print(f"[L1] 开始新的分析任务")

    total = len(doc_list)
    completed_count = len(checkpoint.state.get("completed_docs", []))

    _l1_analysis_progress[project_id] = {
        "status": "processing",
        "total": total,
        "completed": completed_count,
        "current_doc": None,
        "errors": [],
        "results": all_results,
        "model_used": current_model,
        "resumed": has_checkpoint
    }

    errors = []

    for idx, doc_info in enumerate(doc_list):
        doc_id = doc_info["document_id"]

        # 跳过已完成的文档
        if checkpoint.is_doc_completed(doc_id):
            continue

        # 标记文档处理中
        checkpoint.mark_doc_in_progress(doc_id)

        # 带重试的文档处理
        doc_success = False
        last_error = None

        for retry in range(MAX_RETRIES):
            try:
                doc_text = doc_info.get("text", "")
                text_length = len(doc_text)

                # 更新当前处理的文档
                _l1_analysis_progress[project_id]["current_doc"] = {
                    "document_id": doc_id,
                    "file_name": doc_info["file_name"],
                    "exhibit_id": doc_info["exhibit_id"],
                    "text_length": text_length
                }

                # 判断是否使用语义分组模式
                if should_use_page_mode(project_id, doc_id, text_length):
                    # === 语义分组分析模式 ===
                    print(f"[L1] Using SEMANTIC page-group mode for {doc_info['file_name']} ({text_length:,} chars)")

                    pages = load_ocr_pages(project_id, doc_id)
                    page_groups = group_pages_semantically(pages, max_chars=MAX_PAGE_GROUP_SIZE)

                    # 打印语义分组详情
                    print(f"[L1] Split into {len(page_groups)} semantic groups:")
                    for g in page_groups:
                        print(f"  - Group {g['group_id']}: pages {g['page_range']} | {g['type_desc']} | {g['char_count']:,} chars")

                    # 更新进度信息
                    _l1_analysis_progress[project_id]["current_doc"]["mode"] = "semantic_groups"
                    _l1_analysis_progress[project_id]["current_doc"]["total_groups"] = len(page_groups)

                    group_results = []
                    for group in page_groups:
                        # 构建分组文档信息，包含语义上下文
                        group_doc_info = {
                            **doc_info,
                            "text": group["text"],
                            "page_group_id": group["group_id"],
                            "page_range": group["page_range"],
                            "semantic_type": group["semantic_type"],
                            "semantic_desc": group["type_desc"]
                        }

                        prompt = get_l1_analysis_prompt(group_doc_info)
                        llm_result = await call_llm(prompt, model_override=current_model, max_retries=3)
                        group_quotes = parse_analysis_result(llm_result, group_doc_info)
                        group_results.append(group_quotes)

                        print(f"[L1] Group {group['group_id']} ({group['type_desc']}): {len(group_quotes)} quotes")

                        # 更新分组进度
                        _l1_analysis_progress[project_id]["current_doc"]["current_group"] = group["group_id"]

                        await asyncio.sleep(0.5)  # Rate limit between groups

                    # 合并所有分组的结果并去重
                    parsed_quotes = merge_page_group_results(group_results)
                    print(f"[L1] Merged total: {len(parsed_quotes)} unique quotes from {doc_info['file_name']}")

                else:
                    # === 原有整文档模式（短文档） ===
                    print(f"[L1] Using whole-doc mode for {doc_info['file_name']} ({text_length:,} chars)")
                    _l1_analysis_progress[project_id]["current_doc"]["mode"] = "whole_doc"

                    prompt = get_l1_analysis_prompt(doc_info)
                    llm_result = await call_llm(prompt, model_override=current_model, max_retries=3)
                    parsed_quotes = parse_analysis_result(llm_result, doc_info)

                    doc_result = {
                        "document_id": doc_id,
                        "exhibit_id": doc_info["exhibit_id"],
                        "file_name": doc_info["file_name"],
                        "quotes": parsed_quotes
                    }
                    all_results.append(doc_result)

                    # 保存到 checkpoint
                    checkpoint.mark_doc_completed(doc_id, doc_result)
                    doc_success = True

                    # 更新进度
                    completed_count = len(checkpoint.state.get("completed_docs", []))
                    _l1_analysis_progress[project_id]["completed"] = completed_count
                    _l1_analysis_progress[project_id]["results"] = all_results

                    # 成功，跳出重试循环
                    break

            except Exception as e:
                import traceback
                error_traceback = traceback.format_exc()
                last_error = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
                print(f"[L1] Error processing {doc_info['exhibit_id']} (retry {retry + 1}/{MAX_RETRIES}): {e}")

                if retry < MAX_RETRIES - 1:
                    print(f"[L1] Retrying in 2 seconds...")
                    await asyncio.sleep(2.0)
                else:
                    print(f"[L1] Max retries reached for {doc_info['exhibit_id']}")
                    print(f"[L1] Traceback:\n{error_traceback}")

        # 处理最终失败的情况
        if not doc_success:
            # 标记文档失败
            checkpoint.mark_doc_failed(doc_id, last_error or "Unknown error")

            error_info = {
                "document_id": doc_info["document_id"],
                "exhibit_id": doc_info["exhibit_id"],
                "error": last_error,
                "retries": MAX_RETRIES
            }
            errors.append(error_info)
            _l1_analysis_progress[project_id]["errors"] = errors
            print(f"[L1] Document {doc_info['exhibit_id']} failed after {MAX_RETRIES} retries")

        # 添加请求间隔以避免触发速率限制
        await asyncio.sleep(0.5)

    # === 引用整合阶段 (v2.2 LLM 主导) ===
    if all_results:
        print(f"[L1] Starting quote consolidation v2.2 for {len(all_results)} documents...")
        _l1_analysis_progress[project_id]["current_doc"] = {"stage": "consolidation"}

        # Step 1: 为引用添加 bbox 信息（用于位置整合和前端高亮）
        bbox_stats = {}
        try:
            from app.db.database import SessionLocal
            db_session = SessionLocal()
            try:
                all_results, bbox_stats = enrich_all_quotes_with_bbox(all_results, db_session)
                print(f"[L1] Enriched quotes with bbox information:")
                print(f"     Matched: {bbox_stats.get('total_matched', 0)}/{bbox_stats.get('total_quotes', 0)}")
                print(f"     Match rate: {bbox_stats.get('overall_match_rate', 0)}%")
            finally:
                db_session.close()
        except Exception as e:
            print(f"[L1] Warning: Could not enrich quotes with bbox: {e}")

        # Step 2: LLM 主导整合 (带降级)
        try:
            # 检查 Ollama 是否可用
            ollama_available = False
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{settings.ollama_api_base.replace('/v1', '')}/api/tags")
                    ollama_available = response.status_code == 200
            except Exception:
                pass

            if ollama_available and LLM_PROVIDER == "ollama":
                # 使用 LLM 主导整合
                print(f"[L1] Using LLM-led consolidation (model: {settings.ollama_model})")
                _l1_analysis_progress[project_id]["current_doc"]["consolidation_mode"] = "llm_led"

                all_results, consolidation_stats = await consolidate_all_quotes_with_llm(
                    all_results,
                    call_llm,
                    project_id=project_id,
                    model=settings.ollama_model
                )

                print(f"[L1] LLM consolidation complete:")
                print(f"     Original: {consolidation_stats.get('original_count', 0)} quotes")
                print(f"     Final: {consolidation_stats.get('final_count', 0)} quotes")
                print(f"     LLM coverage: {consolidation_stats.get('llm_coverage', 0)}%")
                print(f"     Method: {consolidation_stats.get('method', 'unknown')}")
            else:
                # 降级到仅粗筛
                print(f"[L1] Ollama not available, using fallback consolidation")
                _l1_analysis_progress[project_id]["current_doc"]["consolidation_mode"] = "fallback"

                all_results, consolidation_stats = consolidate_all_document_quotes(all_results)
                consolidation_stats["warning"] = "LLM not available, quotes not reviewed"

                print(f"[L1] Fallback consolidation complete:")
                print(f"     Original: {consolidation_stats.get('total_original', 0)} quotes")
                print(f"     Final: {consolidation_stats.get('total_final', 0)} quotes")

            # 添加 bbox 统计
            consolidation_stats["bbox_stats"] = bbox_stats

            # 更新进度信息
            _l1_analysis_progress[project_id]["consolidation_stats"] = consolidation_stats

        except Exception as e:
            import traceback
            print(f"[L1] Warning: Quote consolidation failed: {e}")
            print(f"[L1] Traceback:\n{traceback.format_exc()}")
            # 出错时保留原始结果
            _l1_analysis_progress[project_id]["consolidation_stats"] = {
                "error": str(e),
                "method": "failed"
            }

    # 保存分析结果
    storage.save_l1_analysis(project_id, all_results)

    # 标记完成并清理 checkpoint
    checkpoint.mark_completed()

    # 添加统计信息
    failed_docs = checkpoint.state.get("failed_docs", []) if hasattr(checkpoint, 'state') else []

    _l1_analysis_progress[project_id]["status"] = "completed"
    _l1_analysis_progress[project_id]["current_doc"] = None
    _l1_analysis_progress[project_id]["failed_docs"] = failed_docs

    print(f"[L1] 分析完成: {len(all_results)} 文档成功, {len(failed_docs)} 文档失败")


@router.post("/l1-analyze/{project_id}")
async def l1_analyze_project(
    project_id: str,
    doc_ids: Optional[str] = None,
    force: bool = False,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """Stage 2 (L-1 专项): 整文档 L-1 标准分析（无 Chunking）- 支持断点续传

    参数:
    - project_id: 项目 ID
    - doc_ids: 可选，逗号分隔的文档 ID 列表。如果不提供，分析所有已完成 OCR 的文档
    - force: 如果为 true，强制从头开始分析（忽略断点）

    返回 202 并在后台执行分析，使用 /l1-analyze/stream/{project_id} 监控进度
    """
    global _l1_analysis_progress
    from app.services.l1_analyzer import L1AnalysisCheckpoint

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

    # 检查是否有断点可恢复
    checkpoint = L1AnalysisCheckpoint(project_id)
    has_checkpoint = checkpoint.has_valid_checkpoint() and not force

    if has_checkpoint:
        # 从断点恢复，使用 checkpoint 中保存的文档列表
        doc_list = checkpoint.get_doc_list()
        resume_info = checkpoint.get_resume_info()

        if not doc_list:
            # checkpoint 数据不完整，需要重新加载
            has_checkpoint = False
        else:
            print(f"[L1] 从断点恢复: 已完成 {resume_info['completed_count']}/{resume_info['total']} 文档")

    if not has_checkpoint:
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

    # 启动后台任务（支持断点续传）
    asyncio.create_task(_run_l1_analysis_background(project_id, doc_list, force_restart=force))

    return {
        "success": True,
        "message": "Resuming L1 analysis from checkpoint" if has_checkpoint else f"Started L1 analysis for {len(doc_list)} documents",
        "project_id": project_id,
        "total": len(doc_list),
        "resumed_from_checkpoint": has_checkpoint,
        "documents": [
            {"id": d["document_id"], "file_name": d["file_name"], "exhibit_id": d["exhibit_id"]}
            for d in doc_list
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


@router.get("/l1-analyze/checkpoint/{project_id}")
async def get_l1_checkpoint_status(project_id: str):
    """获取 L1 分析断点状态"""
    from app.services.l1_analyzer import L1AnalysisCheckpoint

    checkpoint = L1AnalysisCheckpoint(project_id)

    if not checkpoint.has_valid_checkpoint():
        return {
            "success": True,
            "project_id": project_id,
            "has_checkpoint": False,
            "progress": None
        }

    progress = checkpoint.get_progress()
    return {
        "success": True,
        "project_id": project_id,
        "has_checkpoint": True,
        "progress": progress
    }


@router.delete("/l1-analyze/checkpoint/{project_id}")
async def delete_l1_checkpoint(project_id: str):
    """删除 L1 分析的断点，下次分析将从头开始"""
    from app.services.l1_analyzer import L1AnalysisCheckpoint

    checkpoint = L1AnalysisCheckpoint(project_id)
    had_checkpoint = checkpoint.has_valid_checkpoint()

    checkpoint.clear()

    return {
        "success": True,
        "project_id": project_id,
        "had_checkpoint": had_checkpoint
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
    # 检查是否有 L-1 分析结果（自动合并所有分析文件）
    analysis = storage.load_l1_analysis(project_id)
    has_analysis = analysis is not None and len(analysis) > 0

    # 实时计算 analysis 中的总引用数
    analysis_total_quotes = 0
    if analysis:
        for chunk in analysis:
            analysis_total_quotes += len(chunk.get("quotes", []))

    # 检查是否有 L-1 汇总结果
    summary = storage.load_l1_summary(project_id)
    has_summary = summary is not None and summary.get('total_quotes', 0) > 0

    return {
        "has_analysis": has_analysis,
        "analysis_chunks": len(analysis) if analysis else 0,
        "analysis_total_quotes": analysis_total_quotes,  # 新增：实时计算的引用总数
        "has_summary": has_summary,
        "summary_quotes": analysis_total_quotes  # 改为使用实时数据，而不是旧 summary
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

    # 获取证据丰富度元数据（如果有）
    evidence_metadata = evidence.get("evidence_metadata", {})
    unique_exhibits = evidence_metadata.get("unique_exhibits", [])
    data_types = evidence_metadata.get("data_types_found", {})

    # 获取分层证据（跨标准聚合）
    primary_quotes = evidence.get("primary_quotes", evidence.get("quotes", []))
    supporting_quotes = evidence.get("supporting_quotes", [])
    primary_count = evidence.get("primary_quote_count", len(primary_quotes))
    supporting_count = evidence.get("supporting_quote_count", len(supporting_quotes))

    # 调试日志：打印跨标准聚合结果
    print(f"\n{'='*60}")
    print(f"[DEBUG] Section: {section_type}")
    print(f"[DEBUG] Primary quotes: {primary_count}")
    print(f"[DEBUG] Supporting quotes: {supporting_count}")
    if supporting_quotes:
        print(f"[DEBUG] Supporting quote value_types:")
        for i, sq in enumerate(supporting_quotes[:5]):  # 只打印前5条
            print(f"  [{i+1}] {sq.get('value_types', [])} - {sq.get('quote', '')[:80]}...")
    print(f"{'='*60}\n")

    prompt = f"""You are a Senior Immigration Attorney at a top-tier U.S. law firm specializing in L-1 visa petitions. Your task is to write a comprehensive, persuasive paragraph for an L-1 Petition Letter that will convince USCIS to approve the petition.

═══════════════════════════════════════════════════════════════
SECTION 1: CRITICAL LENGTH & DENSITY REQUIREMENTS
═══════════════════════════════════════════════════════════════

**MINIMUM LENGTH: 200-400 words** (CRITICAL - paragraphs under 200 words will be REJECTED)

**CONTENT DENSITY REQUIREMENTS:**
- Include AT LEAST 3 distinct factual claims, each with its own citation
- Reference AT LEAST 2 different Exhibit sources (you have {len(unique_exhibits)} available: {', '.join(unique_exhibits) if unique_exhibits else 'multiple exhibits'})
- Include AT LEAST 2 of the following data types: specific dates, percentages, dollar amounts, or employee headcounts
- Every factual claim MUST have an inline citation

═══════════════════════════════════════════════════════════════
SECTION 2: PARAGRAPH STRUCTURE TEMPLATE
═══════════════════════════════════════════════════════════════

Your paragraph MUST follow this layered structure:

**Layer 1 - Legal Conclusion Statement (1-2 sentences):**
State the legal conclusion directly, connecting to the relevant L-1 standard.
Example: "The Petitioner maintains a qualifying corporate relationship with its foreign parent company, as required under 8 CFR 214.2(l)."

**Layer 2 - Primary Evidence with Specifics (2-3 sentences):**
Present the most critical facts with specific dates, percentages, and figures.
Example: "The foreign parent, [Company Name], holds a 51% ownership stake in the Petitioner, as evidenced by the stock certificate issued on [date]. [Exhibit X: Stock Certificate]"

**Layer 3 - Supporting Business Context (2-3 sentences):**
Describe business operations, products/services, or organizational structure that strengthens the case.
Example: "The Petitioner operates as a specialized distributor of elevator components, serving over 50 commercial clients across the Northeastern United States. [Exhibit Y: Business Plan]"

**Layer 4 - Financial/Quantitative Evidence (1-2 sentences):**
Include revenue figures, employee counts, growth projections, or other quantitative data.
Example: "Since its establishment, the company has grown to employ 7 full-time staff and generated $741,227 in gross revenue for fiscal year 2024. [Exhibits A-6 & B-1: Payroll Records, Financial Statements]"

**Layer 5 - Forward-Looking or Concluding Statement (1-2 sentences):**
Reinforce the qualifying relationship with future plans or partnership context.
Example: "This ownership structure ensures continued collaboration and resource sharing between the U.S. and foreign entities, demonstrating a bona fide qualifying relationship."

═══════════════════════════════════════════════════════════════
SECTION 3: CITATION FORMAT REQUIREMENTS
═══════════════════════════════════════════════════════════════

**CORRECT Citation Formats:**
- Single exhibit: [Exhibit A-6: Payroll Journal]
- Multiple exhibits: [Exhibits A-6, B-1 & B-2: Payroll Journal, Business Plan, Organizational Chart]

**INCORRECT Formats (DO NOT USE):**
- [Exhibit B-2: Exhibit B-2.pdf] ← Never use raw filenames
- [Exhibit B-2.pdf] ← Missing descriptive title
- (Exhibit B-2) ← Wrong bracket style

**Use DESCRIPTIVE TITLES for exhibits:**
- Stock certificates → "Stock Certificate" or "Ownership Documentation"
- Business plans → "Business Plan"
- Incorporation documents → "Certificate of Incorporation"
- Financial documents → "Financial Statements" or "Tax Return"
- Payroll records → "Payroll Journal" or "Payroll Records"
- Lease agreements → "Commercial Lease Agreement"
- Organization charts → "Organizational Chart"

═══════════════════════════════════════════════════════════════
SECTION 4: LEGAL LANGUAGE REQUIREMENTS
═══════════════════════════════════════════════════════════════

**USE these professional legal phrases:**
- "duly established" (for company formation)
- "maintains a qualifying corporate relationship" (for ownership)
- "evidenced by" (for documentary proof)
- "demonstrates" / "establishing" (for conclusions)
- "in accordance with" / "as required under" (for regulatory references)
- "bona fide" (for genuine relationships)
- "requisite" (for required elements)

**AVOID:**
- Casual language or contractions
- Hedging words like "seems," "appears," "might"
- Repetitive phrasing

═══════════════════════════════════════════════════════════════
SECTION 5: AVAILABLE EVIDENCE (CROSS-STANDARD AGGREGATED)
═══════════════════════════════════════════════════════════════

**PRIMARY EVIDENCE** ({primary_count} quotes - use these to build core arguments):
{json.dumps(primary_quotes, indent=2, ensure_ascii=False)}

**SUPPORTING EVIDENCE** ({supporting_count} quotes - high-value data to enrich the paragraph):
{json.dumps(supporting_quotes, indent=2, ensure_ascii=False) if supporting_quotes else "No additional supporting evidence available."}

═══════════════════════════════════════════════════════════════
SECTION 6: EVIDENCE USAGE INSTRUCTIONS
═══════════════════════════════════════════════════════════════

**Writing Strategy:**
1. Use PRIMARY EVIDENCE to construct the core legal arguments and narrative
2. Select 2-3 high-value items from SUPPORTING EVIDENCE to enrich the paragraph with:
   - Financial figures (revenue, projections)
   - Employee headcounts (current staff, planned growth)
   - Specific products/services offered
   - Client/customer names
   - Growth projections and business milestones

**Data Usage Principles (prioritize when evidence is available):**

1. **Precision over generalization** - Use exact figures from evidence rather than rounding or summarizing (e.g., use the exact dollar amount instead of rounding to millions)

2. **Specificity over counts** - When client names, partner companies, or product names appear in evidence, list them rather than just stating a count

3. **Include staffing details** - If employee headcount (current or projected) appears in evidence, incorporate it

4. **Preserve timeline granularity** - Use year-by-year projections as stated in evidence rather than compressing into a single future date

5. **Citation diversity** - Draw from multiple different Exhibits when possible to demonstrate breadth of documentation

6. **Name concrete evidence types** - When referencing documentation, mention specific types (payroll records, bank statements, contracts) rather than "various documents"

**Task Context:**
- Section to Write: {section_type}
- Beneficiary Name: {beneficiary_name_str}
- Petitioner Name: {petitioner_name}

═══════════════════════════════════════════════════════════════
SECTION 7: OUTPUT FORMAT
═══════════════════════════════════════════════════════════════

Respond with a JSON object in this EXACT format:

{{
  "paragraph_text": "[Your 200-400 word paragraph here, with inline citations using descriptive titles. Example: {petitioner_name} maintains a qualifying corporate relationship with its foreign parent company, Fuzhou Shinestone Trade Co., Ltd., through a 51% ownership stake held by Shinestone in the Petitioner. [Exhibit B-2: Stock Certificate] The Petitioner was duly established on April 22, 2022, in the State of New York, as a corporation engaged in the wholesale distribution of elevator parts and components. [Exhibit A-1: Certificate of Incorporation] ... (continue for 200-400 words total)]",
  "citations_used": [
    {{
      "exhibit": "B-2",
      "descriptive_title": "Stock Certificate",
      "quote": "The exact quote from the evidence that supports this claim...",
      "claim": "Brief summary of the fact supported (e.g., 'Foreign parent holds 51% ownership stake')"
    }},
    {{
      "exhibit": "A-1",
      "descriptive_title": "Certificate of Incorporation",
      "quote": "The exact quote...",
      "claim": "Brief summary..."
    }}
  ]
}}

**FINAL CHECKLIST before responding:**
☐ Paragraph is 200-400 words (count carefully!)
☐ At least 3 distinct facts with citations
☐ At least 2 different Exhibits cited
☐ Citations use descriptive titles, NOT filenames
☐ Includes specific dates, percentages, or amounts
☐ Uses professional legal language
☐ Follows the 5-layer structure
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


# ============== 写作修改 API (Writing Module) ==============

class ReviseSelection(BaseModel):
    """选中文本范围"""
    text: str
    start: int
    end: int


class ReviseRequest(BaseModel):
    """修改段落请求"""
    section_type: str
    current_content: str
    instruction: str
    selection: Optional[ReviseSelection] = None


@router.post("/l1-revise/{project_id}")
async def revise_paragraph(project_id: str, data: ReviseRequest):
    """根据自然语言指令修改段落

    支持两种模式：
    1. 全文修改 - selection 为空时，根据指令修改整个段落
    2. 选中修改 - selection 不为空时，只修改选中部分
    """
    section_names = {
        "qualifying_relationship": "Qualifying Corporate Relationship",
        "qualifying_employment": "Qualifying Employment Abroad",
        "qualifying_capacity": "Qualifying Capacity",
        "doing_business": "Doing Business"
    }

    section_name = section_names.get(data.section_type, data.section_type)

    # 构建修改提示词
    if data.selection:
        prompt = f"""You are editing an L-1 petition letter paragraph.

**Section:** {section_name}

**Current Paragraph:**
{data.current_content}

**Selected Text to Modify:**
"{data.selection.text}"

**User's Instruction:**
{data.instruction}

**Your Task:**
1. Modify ONLY the selected text according to the user's instruction
2. Keep the rest of the paragraph unchanged
3. Maintain the formal, legal writing style
4. Keep all existing citations in [Exhibit X-Y: Title] format
5. Ensure the modified text flows naturally with the surrounding content

**Output Format (JSON):**
{{
  "revised_content": "The complete paragraph with the selected portion modified",
  "changes_made": "Brief description of what was changed"
}}
"""
    else:
        prompt = f"""You are editing an L-1 petition letter paragraph.

**Section:** {section_name}

**Current Paragraph:**
{data.current_content}

**User's Instruction:**
{data.instruction}

**Your Task:**
1. Modify the paragraph according to the user's instruction
2. Maintain the formal, legal writing style
3. Keep all existing citations in [Exhibit X-Y: Title] format
4. Preserve important factual information unless instructed otherwise

**Output Format (JSON):**
{{
  "revised_content": "The revised paragraph text",
  "changes_made": "Brief description of what was changed"
}}
"""

    global current_model
    result = await call_llm(prompt, model_override=current_model)

    # 保存修改后的内容
    revised_content = result.get("revised_content", data.current_content)
    changes_made = result.get("changes_made", "Content updated")

    # 加载现有写作结果获取 citations
    existing = storage.load_writing(project_id, data.section_type)
    citations = existing.get("citations", []) if existing else []

    # 保存更新后的内容
    storage.save_writing(project_id, data.section_type, revised_content, citations)

    return {
        "success": True,
        "revised_content": revised_content,
        "changes_made": changes_made
    }


@router.get("/pdf-preview/{document_id}/{page}")
async def get_pdf_preview(
    document_id: str,
    page: int,
    bbox: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取 PDF 页面预览图 (base64)

    可选参数 bbox 用于裁剪特定区域，格式为 JSON: {"x1":0,"y1":0,"x2":100,"y2":100}
    """
    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 获取文件路径
    file_path = storage.get_document_path(doc.project_id, doc.id, doc.file_name)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Document file not found")

    try:
        import fitz  # PyMuPDF
        from PIL import Image
        import io
        import base64

        # 打开 PDF
        pdf_doc = fitz.open(file_path)
        if page < 1 or page > len(pdf_doc):
            raise HTTPException(status_code=400, detail=f"Invalid page number. Document has {len(pdf_doc)} pages.")

        # 渲染页面
        pdf_page = pdf_doc[page - 1]
        mat = fitz.Matrix(1.5, 1.5)  # 150% zoom for better quality
        pix = pdf_page.get_pixmap(matrix=mat)

        # 转换为 PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # 如果有 bbox，裁剪区域
        if bbox:
            try:
                bbox_data = json.loads(bbox)
                # 缩放 bbox 坐标（考虑 zoom 因子）
                scale = 1.5
                x1 = int(bbox_data.get("x1", 0) * scale)
                y1 = int(bbox_data.get("y1", 0) * scale)
                x2 = int(bbox_data.get("x2", img.width) * scale)
                y2 = int(bbox_data.get("y2", img.height) * scale)

                # 添加 padding
                padding = 20
                x1 = max(0, x1 - padding)
                y1 = max(0, y1 - padding)
                x2 = min(img.width, x2 + padding)
                y2 = min(img.height, y2 + padding)

                img = img.crop((x1, y1, x2, y2))
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[PDF Preview] Invalid bbox format: {e}")

        # 转换为 base64
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        img_base64 = base64.b64encode(buffer.getvalue()).decode()

        pdf_doc.close()

        return {
            "image": f"data:image/png;base64,{img_base64}",
            "document_id": document_id,
            "page": page
        }

    except ImportError:
        raise HTTPException(status_code=500, detail="PDF support not available (PyMuPDF not installed)")
    except Exception as e:
        print(f"[PDF Preview] Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate preview: {str(e)}")


@router.get("/citation-index/{project_id}")
async def get_citation_index(project_id: str, db: Session = Depends(get_db)):
    """获取项目的引用索引

    返回所有 Exhibit 的文档 ID、页码和位置信息，用于快速查找 PDF 预览
    """
    # 获取项目的所有文档
    docs = db.query(Document).filter(Document.project_id == project_id).all()

    if not docs:
        return {"project_id": project_id, "citations": {}}

    citations = {}

    for doc in docs:
        if doc.exhibit_number:
            exhibit_key = doc.exhibit_number

            # 获取该文档的高亮结果（如果有）
            highlights = db.query(Highlight).filter(Highlight.document_id == doc.id).all()

            quotes = []
            for hl in highlights:
                if hl.text_content:
                    quote_data = {
                        "text": hl.text_content[:200],  # 截取前200字
                        "page": hl.page_number,
                    }
                    if hl.bbox_x1 is not None:
                        quote_data["bbox"] = {
                            "x1": hl.bbox_x1,
                            "y1": hl.bbox_y1,
                            "x2": hl.bbox_x2,
                            "y2": hl.bbox_y2
                        }
                    quotes.append(quote_data)

            # 如果没有高亮，添加基本信息
            if not quotes:
                quotes.append({
                    "text": "",
                    "page": 1
                })

            citations[exhibit_key] = {
                "document_id": doc.id,
                "file_name": doc.file_name,
                "quotes": quotes
            }

    return {
        "project_id": project_id,
        "citations": citations
    }


# ============== Material-Based Pipeline (v2.0) ==============
# New architecture: OCR → Material Splitting → Highlight Analysis → L1 Analysis → Quote Consolidation

# Progress tracking for material-based analysis
_material_analysis_progress: Dict[str, Dict[str, Any]] = {}


@router.post("/pipeline/split-materials/{project_id}")
async def split_materials_for_project(
    project_id: str,
    doc_ids: Optional[str] = None,
    use_llm: bool = True,
    db: Session = Depends(get_db)
):
    """
    Phase 1: 材料分割

    将 Exhibit PDF 拆分为独立材料（合同、邮件、发票等）

    参数:
    - project_id: 项目 ID
    - doc_ids: 可选，逗号分隔的文档 ID
    - use_llm: 是否使用 LLM 进行分割（默认 True）
    """
    # 基础查询
    query = db.query(Document).filter(
        Document.project_id == project_id,
        Document.ocr_status == OCRStatus.COMPLETED.value
    )

    if doc_ids:
        doc_id_list = [id.strip() for id in doc_ids.split(',') if id.strip()]
        if doc_id_list:
            query = query.filter(Document.id.in_(doc_id_list))

    documents = query.all()

    if not documents:
        raise HTTPException(status_code=404, detail="No documents found")

    all_materials = []
    results = []

    for doc in documents:
        exhibit_id = doc.exhibit_number or f"doc_{doc.id[:8]}"

        # 加载 OCR 页面数据
        ocr_pages = load_ocr_pages_for_document(project_id, doc.id)

        if not ocr_pages:
            results.append({
                "document_id": doc.id,
                "exhibit_id": exhibit_id,
                "error": "No OCR pages found"
            })
            continue

        # 分割材料
        try:
            # 为 LLM 分割提供 call_llm 函数
            call_llm_wrapper = None
            if use_llm:
                async def call_llm_wrapper(prompt, max_retries=2):
                    return await call_llm(prompt, max_retries=max_retries)

            materials = await split_exhibit_into_materials(
                project_id=project_id,
                exhibit_id=exhibit_id,
                document_id=doc.id,
                file_name=doc.file_name,
                ocr_pages=ocr_pages,
                call_llm_func=call_llm_wrapper,
                use_llm=use_llm
            )

            # 保存材料
            save_materials(project_id, exhibit_id, materials)

            all_materials.extend(materials)
            results.append({
                "document_id": doc.id,
                "exhibit_id": exhibit_id,
                "file_name": doc.file_name,
                "materials_count": len(materials),
                "materials": [m.to_dict() for m in materials]
            })

        except Exception as e:
            results.append({
                "document_id": doc.id,
                "exhibit_id": exhibit_id,
                "error": str(e)
            })

    return {
        "success": True,
        "project_id": project_id,
        "total_documents": len(documents),
        "total_materials": len(all_materials),
        "results": results
    }


@router.post("/pipeline/highlight-analyze/{project_id}")
async def analyze_highlights_for_project(
    project_id: str,
    exhibit_ids: Optional[str] = None,
    use_llm: bool = True,
    db: Session = Depends(get_db)
):
    """
    Phase 2: 高光分析

    对每个独立材料进行预处理和关键信息标记

    参数:
    - project_id: 项目 ID
    - exhibit_ids: 可选，逗号分隔的 Exhibit ID
    - use_llm: 是否使用 LLM（默认 True）
    """
    # 加载所有材料
    all_materials_dict = load_all_materials_for_project(project_id)

    if not all_materials_dict:
        raise HTTPException(status_code=404, detail="No materials found. Run /pipeline/split-materials first.")

    # 过滤指定的 exhibit
    if exhibit_ids:
        exhibit_id_list = [id.strip() for id in exhibit_ids.split(',') if id.strip()]
        all_materials_dict = {k: v for k, v in all_materials_dict.items() if k in exhibit_id_list}

    if not all_materials_dict:
        raise HTTPException(status_code=404, detail="No matching exhibits found")

    # 收集所有材料
    all_materials = []
    for materials in all_materials_dict.values():
        all_materials.extend(materials)

    # 准备 LLM 调用函数
    call_llm_wrapper = None
    if use_llm:
        async def call_llm_wrapper(prompt, max_retries=2):
            return await call_llm(prompt, max_retries=max_retries)

    # 分析所有材料
    highlight_results = await analyze_all_materials(
        materials=all_materials,
        call_llm_func=call_llm_wrapper,
        use_llm=use_llm
    )

    # 保存结果
    save_highlight_results(project_id, highlight_results)

    # 返回摘要
    results_summary = []
    for material_id, result in highlight_results.items():
        results_summary.append({
            "material_id": material_id,
            "document_type": result.metadata.document_type,
            "title": result.metadata.title,
            "date": result.metadata.date,
            "parties": result.metadata.parties,
            "highlight_count": len(result.highlights)
        })

    return {
        "success": True,
        "project_id": project_id,
        "total_materials": len(all_materials),
        "analyzed_count": len(highlight_results),
        "results": results_summary
    }


async def _run_material_l1_analysis_background(
    project_id: str,
    materials: list,
    highlight_results: Dict[str, HighlightResult]
):
    """后台运行材料级 L1 分析任务"""
    global _material_analysis_progress, current_model

    total = len(materials)
    _material_analysis_progress[project_id] = {
        "status": "processing",
        "phase": "l1_analysis",
        "total": total,
        "completed": 0,
        "current_material": None,
        "errors": [],
        "results": [],
        "model_used": current_model
    }

    all_results = []
    errors = []

    for idx, material in enumerate(materials):
        try:
            material_id = material.material_id

            # 更新当前处理的材料
            _material_analysis_progress[project_id]["current_material"] = {
                "material_id": material_id,
                "exhibit_id": material.exhibit_id,
                "title": material.title,
                "page_range": material.page_range
            }

            # 获取高光分析上下文
            highlight_context = None
            if material_id in highlight_results:
                highlight_context = get_highlight_context_for_l1(highlight_results[material_id])

            # 构建材料信息
            material_info = {
                "material_id": material_id,
                "exhibit_id": material.exhibit_id,
                "document_id": material.document_id,
                "file_name": material.file_name,
                "text": clean_ocr_for_llm(material.get_full_text()),
                "material_type": material.material_type,
                "title": material.title,
                "date": material.date,
                "page_range": material.page_range
            }

            # 获取文本块（v3.0 架构改进）
            text_blocks = material.get_all_text_blocks()

            # 生成 prompt（优先使用文本块格式，带高光上下文）
            if text_blocks:
                # 使用 v3.0 文本块感知 prompt
                prompt = get_l1_analysis_prompt_for_material_with_blocks(
                    material_info, text_blocks, highlight_context
                )
            else:
                # 降级到传统文本 prompt
                prompt = get_l1_analysis_prompt_for_material(material_info, highlight_context)

            # 调用 LLM
            llm_result = await call_llm(prompt, model_override=current_model, max_retries=3)

            # 解析结果
            parsed_quotes = parse_material_analysis_result(llm_result, material_info)

            # 创建分析结果对象
            analysis_result = MaterialAnalysisResult(
                material_id=material_id,
                exhibit_id=material.exhibit_id,
                document_id=material.document_id
            )
            analysis_result.add_quotes(parsed_quotes)
            analysis_result.model_used = current_model

            all_results.append(analysis_result)

            print(f"[L1-Material] {material_id}: {len(parsed_quotes)} quotes extracted")

            # 更新进度
            _material_analysis_progress[project_id]["completed"] = idx + 1
            _material_analysis_progress[project_id]["results"] = [r.to_dict() for r in all_results]

            # Rate limit
            await asyncio.sleep(0.5)

        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            print(f"[L1-Material] Error processing {material.material_id}: {e}")

            error_info = {
                "material_id": material.material_id,
                "exhibit_id": material.exhibit_id,
                "error": str(e),
                "traceback": error_traceback[:500]
            }
            errors.append(error_info)
            _material_analysis_progress[project_id]["errors"] = errors
            _material_analysis_progress[project_id]["completed"] = idx + 1

    # 引用整合阶段（按材料逐个处理）
    if all_results:
        print(f"[L1-Material] Starting per-material quote consolidation for {len(all_results)} materials...")
        _material_analysis_progress[project_id]["phase"] = "consolidation"
        _material_analysis_progress[project_id]["current_material"] = {"stage": "consolidation"}

        # 转换为材料结果格式
        material_results = []
        for result in all_results:
            material_results.append({
                "document_id": result.document_id,
                "exhibit_id": result.exhibit_id,
                "material_id": result.material_id,
                "file_name": "",
                "quotes": result.quotes
            })

        # BBox 富化（按材料）
        total_bbox_stats = {"total_matched": 0, "total_quotes": 0}
        try:
            db_session = SessionLocal()
            try:
                for mat_result in material_results:
                    document_id = mat_result.get("document_id")
                    quotes = mat_result.get("quotes", [])
                    if document_id and quotes:
                        enriched_quotes, stats = enrich_quotes_with_bbox(quotes, document_id, db_session)
                        mat_result["quotes"] = enriched_quotes
                        total_bbox_stats["total_matched"] += stats.get("matched", 0)
                        total_bbox_stats["total_quotes"] += stats.get("total", 0)

                overall_match_rate = round(
                    total_bbox_stats["total_matched"] / total_bbox_stats["total_quotes"] * 100, 1
                ) if total_bbox_stats["total_quotes"] else 0
                total_bbox_stats["overall_match_rate"] = overall_match_rate
                print(f"[L1-Material] BBox enrichment: {overall_match_rate}% match rate")
            finally:
                db_session.close()
        except Exception as e:
            print(f"[L1-Material] Warning: BBox enrichment failed: {e}")

        # LLM 整合（按材料逐个处理 - 新架构核心）
        consolidation_stats = {}
        try:
            # 检查 Ollama 可用性
            ollama_available = False
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{settings.ollama_api_base.replace('/v1', '')}/api/tags")
                    ollama_available = response.status_code == 200
            except Exception:
                pass

            if ollama_available and LLM_PROVIDER == "ollama":
                # 使用材料级 LLM 整合
                material_results, consolidation_stats = await consolidate_all_material_quotes(
                    material_results,
                    call_llm,
                    project_id=project_id,
                    model=settings.ollama_model
                )
            else:
                # 使用降级方案（无 LLM）
                from app.services.quote_consolidator import consolidate_material_quotes_sync
                total_original = 0
                total_final = 0
                for mat_result in material_results:
                    quotes = mat_result.get("quotes", [])
                    total_original += len(quotes)
                    consolidated, _ = consolidate_material_quotes_sync(
                        mat_result.get("material_id", "unknown"),
                        quotes
                    )
                    mat_result["quotes"] = consolidated
                    total_final += len(consolidated)
                consolidation_stats = {
                    "total_original": total_original,
                    "total_final": total_final,
                    "method": "material_level_fallback"
                }

            consolidation_stats["bbox_stats"] = total_bbox_stats
            _material_analysis_progress[project_id]["consolidation_stats"] = consolidation_stats

        except Exception as e:
            print(f"[L1-Material] Warning: Consolidation failed: {e}")
            import traceback
            traceback.print_exc()

        # 更新结果（整合后）
        for i, mat_result in enumerate(material_results):
            if i < len(all_results):
                all_results[i].quotes = mat_result.get("quotes", [])

    # 保存分析结果
    save_material_analysis(project_id, all_results)

    # 同时保存为旧格式以兼容现有前端
    chunk_analyses = []
    for result in all_results:
        chunk_analyses.append({
            "document_id": result.document_id,
            "exhibit_id": result.exhibit_id,
            "file_name": "",
            "quotes": result.quotes
        })
    storage.save_l1_analysis(project_id, chunk_analyses)

    # 标记完成
    _material_analysis_progress[project_id]["status"] = "completed"
    _material_analysis_progress[project_id]["current_material"] = None
    _material_analysis_progress[project_id]["phase"] = "done"


@router.post("/pipeline/l1-analyze-materials/{project_id}")
async def l1_analyze_materials(
    project_id: str,
    exhibit_ids: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Phase 3: L1 分析（材料级）

    对每个独立材料进行四维度分析，提取原文引用

    参数:
    - project_id: 项目 ID
    - exhibit_ids: 可选，逗号分隔的 Exhibit ID
    """
    global _material_analysis_progress

    # 检查是否已有分析在进行中
    if project_id in _material_analysis_progress:
        current_status = _material_analysis_progress[project_id].get("status")
        if current_status == "processing":
            return {
                "success": True,
                "message": "Material L1 analysis already in progress",
                "project_id": project_id,
                "status": "processing"
            }

    # 加载材料
    all_materials_dict = load_all_materials_for_project(project_id)

    if not all_materials_dict:
        raise HTTPException(status_code=404, detail="No materials found. Run /pipeline/split-materials first.")

    # 过滤指定的 exhibit
    if exhibit_ids:
        exhibit_id_list = [id.strip() for id in exhibit_ids.split(',') if id.strip()]
        all_materials_dict = {k: v for k, v in all_materials_dict.items() if k in exhibit_id_list}

    # 收集所有材料
    all_materials = []
    for materials in all_materials_dict.values():
        all_materials.extend(materials)

    if not all_materials:
        raise HTTPException(status_code=404, detail="No materials found")

    # 加载高光分析结果
    highlight_results = load_all_highlight_results(project_id)

    # 启动后台任务
    asyncio.create_task(_run_material_l1_analysis_background(
        project_id, all_materials, highlight_results
    ))

    return {
        "success": True,
        "message": f"Started material L1 analysis for {len(all_materials)} materials",
        "project_id": project_id,
        "total_materials": len(all_materials)
    }


@router.get("/pipeline/l1-analyze-materials/progress/{project_id}")
async def get_material_l1_analysis_progress(project_id: str):
    """获取材料级 L1 分析进度"""
    global _material_analysis_progress

    progress_data = _material_analysis_progress.get(project_id)

    if not progress_data:
        return {
            "project_id": project_id,
            "status": "idle",
            "phase": None,
            "total": 0,
            "completed": 0
        }

    return {
        "project_id": project_id,
        "status": progress_data.get("status", "unknown"),
        "phase": progress_data.get("phase", ""),
        "total": progress_data.get("total", 0),
        "completed": progress_data.get("completed", 0),
        "current_material": progress_data.get("current_material"),
        "errors": progress_data.get("errors", []),
        "model_used": progress_data.get("model_used", ""),
        "consolidation_stats": progress_data.get("consolidation_stats", {})
    }


@router.post("/pipeline/analyze/{project_id}")
async def run_full_material_pipeline(
    project_id: str,
    mode: str = "split",
    doc_ids: Optional[str] = None,
    use_llm: bool = True,
    db: Session = Depends(get_db)
):
    """
    完整材料分析流水线

    运行完整的 3 阶段流程：材料分割 → 高光分析 → L1 分析

    参数:
    - project_id: 项目 ID
    - mode: "split" (需要分割) 或 "direct" (已分割)
    - doc_ids: 可选，逗号分隔的文档 ID
    - use_llm: 是否使用 LLM（默认 True）
    """
    global _material_analysis_progress

    # 检查是否已有分析在进行中
    if project_id in _material_analysis_progress:
        current_status = _material_analysis_progress[project_id].get("status")
        if current_status == "processing":
            return {
                "success": True,
                "message": "Pipeline already in progress",
                "project_id": project_id,
                "status": "processing"
            }

    # 启动完整流程的后台任务
    asyncio.create_task(_run_full_pipeline_background(
        project_id, mode, doc_ids, use_llm, db
    ))

    return {
        "success": True,
        "message": f"Started full material pipeline (mode: {mode})",
        "project_id": project_id,
        "mode": mode
    }


async def _run_full_pipeline_background(
    project_id: str,
    mode: str,
    doc_ids: Optional[str],
    use_llm: bool,
    db: Session
):
    """后台运行完整材料分析流水线"""
    global _material_analysis_progress

    try:
        _material_analysis_progress[project_id] = {
            "status": "processing",
            "phase": "splitting",
            "total": 0,
            "completed": 0,
            "current_material": None,
            "errors": []
        }

        # Phase 1: 材料分割
        if mode == "split":
            print(f"[Pipeline] Phase 1: Material splitting...")
            _material_analysis_progress[project_id]["phase"] = "splitting"

            # 获取文档列表
            query = db.query(Document).filter(
                Document.project_id == project_id,
                Document.ocr_status == OCRStatus.COMPLETED.value
            )

            if doc_ids:
                doc_id_list = [id.strip() for id in doc_ids.split(',') if id.strip()]
                if doc_id_list:
                    query = query.filter(Document.id.in_(doc_id_list))

            documents = query.all()

            # 分割每个文档
            all_materials = []
            for doc in documents:
                exhibit_id = doc.exhibit_number or f"doc_{doc.id[:8]}"
                ocr_pages = load_ocr_pages_for_document(project_id, doc.id)

                if ocr_pages:
                    call_llm_wrapper = None
                    if use_llm:
                        async def call_llm_wrapper(prompt, max_retries=2):
                            return await call_llm(prompt, max_retries=max_retries)

                    materials = await split_exhibit_into_materials(
                        project_id=project_id,
                        exhibit_id=exhibit_id,
                        document_id=doc.id,
                        file_name=doc.file_name,
                        ocr_pages=ocr_pages,
                        call_llm_func=call_llm_wrapper,
                        use_llm=use_llm
                    )
                    save_materials(project_id, exhibit_id, materials)
                    all_materials.extend(materials)

            print(f"[Pipeline] Split into {len(all_materials)} materials")
        else:
            # 模式 B: 已分割，直接加载
            all_materials_dict = load_all_materials_for_project(project_id)
            all_materials = []
            for materials in all_materials_dict.values():
                all_materials.extend(materials)

        if not all_materials:
            _material_analysis_progress[project_id]["status"] = "failed"
            _material_analysis_progress[project_id]["errors"].append("No materials found")
            return

        _material_analysis_progress[project_id]["total"] = len(all_materials)

        # Phase 2: 高光分析
        print(f"[Pipeline] Phase 2: Highlight analysis...")
        _material_analysis_progress[project_id]["phase"] = "highlighting"

        call_llm_wrapper = None
        if use_llm:
            async def call_llm_wrapper(prompt, max_retries=2):
                return await call_llm(prompt, max_retries=max_retries)

        highlight_results = await analyze_all_materials(
            materials=all_materials,
            call_llm_func=call_llm_wrapper,
            use_llm=use_llm
        )
        save_highlight_results(project_id, highlight_results)
        print(f"[Pipeline] Highlight analysis complete: {len(highlight_results)} materials")

        # Phase 3: L1 分析
        print(f"[Pipeline] Phase 3: L1 analysis...")
        await _run_material_l1_analysis_background(
            project_id, all_materials, highlight_results
        )

    except Exception as e:
        import traceback
        print(f"[Pipeline] Error: {e}")
        print(traceback.format_exc())
        _material_analysis_progress[project_id]["status"] = "failed"
        _material_analysis_progress[project_id]["errors"].append(str(e))


@router.get("/pipeline/materials/{project_id}")
async def get_project_materials(project_id: str):
    """获取项目的所有材料"""
    all_materials_dict = load_all_materials_for_project(project_id)

    if not all_materials_dict:
        return {
            "project_id": project_id,
            "total_materials": 0,
            "exhibits": {}
        }

    exhibits = {}
    total_materials = 0

    for exhibit_id, materials in all_materials_dict.items():
        exhibits[exhibit_id] = [m.to_dict() for m in materials]
        total_materials += len(materials)

    return {
        "project_id": project_id,
        "total_materials": total_materials,
        "exhibits": exhibits
    }


@router.get("/pipeline/highlights/{project_id}")
async def get_project_highlights(project_id: str, material_id: Optional[str] = None):
    """获取项目的高光分析结果"""
    if material_id:
        result = load_highlight_result(project_id, material_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Highlight result not found for {material_id}")
        return result.to_dict()

    all_results = load_all_highlight_results(project_id)

    if not all_results:
        return {
            "project_id": project_id,
            "total": 0,
            "results": {}
        }

    return {
        "project_id": project_id,
        "total": len(all_results),
        "results": {k: v.to_dict() for k, v in all_results.items()}
    }

