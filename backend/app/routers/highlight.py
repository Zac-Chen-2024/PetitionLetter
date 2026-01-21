"""
Highlight Router - 高亮分析 API

提供文档高亮分析功能：
- 触发高亮分析
- 获取高亮结果
- 保存高亮图片
- 获取文档页面图片
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, AsyncGenerator
from sqlalchemy.orm import Session
from datetime import datetime
import json
import base64
import uuid
import asyncio

from app.db.database import get_db, SessionLocal
from app.models.document import Document, TextBlock, Highlight, HighlightStatus, OCRStatus
from app.services import highlight_service
from app.services import storage

try:
    import fitz  # PyMuPDF
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

try:
    from PIL import Image, ImageDraw
    import io
    PIL_SUPPORT = True
except ImportError:
    PIL_SUPPORT = False

router = APIRouter(prefix="/api/highlight", tags=["highlight"])


# ============== 数据模型 ==============

class HighlightResponse(BaseModel):
    id: str
    text_content: Optional[str]
    category: Optional[str]
    category_cn: Optional[str]
    importance: Optional[str]
    reason: Optional[str]
    page_number: int
    bbox: Optional[Dict[str, int]]
    source_block_ids: List[str]


class DocumentHighlightResponse(BaseModel):
    document_id: str
    file_name: str
    highlight_status: Optional[str]
    total_highlights: int
    highlights: List[HighlightResponse]


class SaveHighlightImageRequest(BaseModel):
    page_number: int
    image_base64: str


# ============== 高亮分析 API ==============

@router.post("/{document_id}")
async def trigger_highlight_analysis(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    触发文档高亮分析

    流程:
    1. 调用 OpenAI GPT-4o 分析文档重要信息
    2. 将识别的文本映射到 OCR BBox 坐标
    3. 保存高亮结果到数据库
    """
    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 检查 OCR 是否完成
    if doc.ocr_status != OCRStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"OCR not completed. Current status: {doc.ocr_status}"
        )

    # 检查是否有 text_blocks
    block_count = db.query(TextBlock).filter(TextBlock.document_id == document_id).count()
    if block_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No text blocks found. Document may not have been processed with DeepSeek-OCR."
        )

    # 检查是否已经在处理中
    if doc.highlight_status == HighlightStatus.PROCESSING.value:
        return {
            "success": True,
            "message": "Highlight analysis already in progress",
            "document_id": document_id,
            "status": "processing"
        }

    # 启动后台任务
    background_tasks.add_task(
        run_highlight_analysis_background,
        document_id
    )

    return {
        "success": True,
        "message": "Highlight analysis started",
        "document_id": document_id,
        "status": "started"
    }


def run_highlight_analysis_background(document_id: str):
    """后台执行高亮分析"""
    import asyncio

    db = SessionLocal()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                highlight_service.analyze_and_highlight(document_id, db)
            )
            print(f"[Highlight] Analysis completed for {document_id}: {result}")
        finally:
            loop.close()
    except Exception as e:
        print(f"[Highlight] ERROR for {document_id}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


@router.get("/{document_id}")
async def get_document_highlights(
    document_id: str,
    page: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    获取文档的高亮结果

    参数:
    - page: 可选，过滤指定页码的高亮
    """
    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 获取高亮
    highlights = highlight_service.get_highlights_for_document(document_id, db, page)

    return {
        "document_id": document_id,
        "file_name": doc.file_name,
        "highlight_status": doc.highlight_status,
        "total_highlights": len(highlights),
        "highlights": highlights
    }


@router.get("/by-page/{document_id}")
async def get_highlights_by_page(
    document_id: str,
    db: Session = Depends(get_db)
):
    """
    按页码分组获取高亮

    返回: {1: [highlights...], 2: [highlights...], ...}
    """
    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    by_page = highlight_service.get_highlights_by_page(document_id, db)

    return {
        "document_id": document_id,
        "file_name": doc.file_name,
        "highlight_status": doc.highlight_status,
        "page_count": doc.page_count,
        "highlights_by_page": by_page
    }


@router.get("/status/{document_id}")
async def get_highlight_status(
    document_id: str,
    db: Session = Depends(get_db)
):
    """获取高亮分析状态"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    highlight_count = db.query(Highlight).filter(Highlight.document_id == document_id).count()

    return {
        "document_id": document_id,
        "highlight_status": doc.highlight_status,
        "highlight_count": highlight_count,
        "ocr_status": doc.ocr_status,
        "has_text_blocks": db.query(TextBlock).filter(TextBlock.document_id == document_id).count() > 0
    }


@router.get("/progress/{project_id}")
async def get_project_highlight_progress(
    project_id: str,
    db: Session = Depends(get_db)
):
    """获取项目的高亮分析总体进度"""
    documents = db.query(Document).filter(Document.project_id == project_id).all()

    if not documents:
        return {
            "project_id": project_id,
            "total": 0,
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "not_started": 0,
            "progress_percent": 0,
            "documents": []
        }

    total = len(documents)
    not_started = sum(1 for d in documents if d.highlight_status is None)
    pending = sum(1 for d in documents if d.highlight_status == HighlightStatus.PENDING.value)
    processing = sum(1 for d in documents if d.highlight_status == HighlightStatus.PROCESSING.value)
    completed = sum(1 for d in documents if d.highlight_status == HighlightStatus.COMPLETED.value)
    failed = sum(1 for d in documents if d.highlight_status == HighlightStatus.FAILED.value)

    return {
        "project_id": project_id,
        "total": total,
        "not_started": not_started,
        "pending": pending,
        "processing": processing,
        "completed": completed,
        "failed": failed,
        "progress_percent": round(completed / total * 100, 1) if total > 0 else 0,
        "documents": [
            {
                "id": d.id,
                "file_name": d.file_name,
                "exhibit_number": d.exhibit_number,
                "ocr_status": d.ocr_status,
                "highlight_status": d.highlight_status,
                "page_count": d.page_count
            }
            for d in documents
        ]
    }


@router.get("/stream/{project_id}")
async def stream_highlight_progress(project_id: str, db: Session = Depends(get_db)):
    """SSE 端点：实时推送高亮分析进度

    返回 Server-Sent Events 流：
    - event: progress - 进度更新
    - event: complete - 分析全部完成
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            # 获取当前进度
            documents = db.query(Document).filter(Document.project_id == project_id).all()

            if not documents:
                yield f"event: complete\ndata: {json.dumps({'project_id': project_id, 'total': 0, 'completed': 0})}\n\n"
                break

            total = len(documents)
            not_started = sum(1 for d in documents if d.highlight_status is None)
            pending = sum(1 for d in documents if d.highlight_status == HighlightStatus.PENDING.value)
            processing = sum(1 for d in documents if d.highlight_status == HighlightStatus.PROCESSING.value)
            completed = sum(1 for d in documents if d.highlight_status == HighlightStatus.COMPLETED.value)
            failed = sum(1 for d in documents if d.highlight_status == HighlightStatus.FAILED.value)

            progress = {
                "project_id": project_id,
                "total": total,
                "not_started": not_started,
                "pending": pending,
                "processing": processing,
                "completed": completed,
                "failed": failed,
                "progress_percent": round(completed / total * 100, 1) if total > 0 else 0,
                "documents": [
                    {
                        "id": d.id,
                        "file_name": d.file_name,
                        "exhibit_number": d.exhibit_number,
                        "ocr_status": d.ocr_status,
                        "highlight_status": d.highlight_status,
                        "page_count": d.page_count
                    }
                    for d in documents
                ]
            }

            # 检查是否完成
            if processing == 0 and pending == 0:
                yield f"event: complete\ndata: {json.dumps(progress)}\n\n"
                break

            # 发送进度更新
            yield f"event: progress\ndata: {json.dumps(progress)}\n\n"

            # 刷新数据库会话
            db.expire_all()

            # 等待 1 秒
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


# ============== 文档页面图片 API ==============

# 导入缓存服务
from app.services import page_cache


@router.get("/page/{document_id}/{page_number}/image")
async def get_document_page_image(
    document_id: str,
    page_number: int,
    dpi: int = 100,  # 降低默认 DPI 加快响应
    db: Session = Depends(get_db)
):
    """
    获取文档指定页面的图片

    将 PDF 页面渲染为 JPEG 图片返回
    优先从磁盘缓存读取，缓存未命中时渲染并缓存
    """
    if not PDF_SUPPORT:
        raise HTTPException(status_code=500, detail="PDF support not available")

    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 验证页码
    if page_number < 1 or page_number > doc.page_count:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid page number. Document has {doc.page_count} pages."
        )

    # 检查文件类型
    if doc.file_name.lower().endswith('.pdf'):
        # PDF 文件：优先从缓存读取
        cached_image = page_cache.get_cached_image(document_id, page_number, dpi)
        if cached_image:
            return Response(
                content=cached_image,
                media_type="image/jpeg",
                headers={
                    "Content-Disposition": f"inline; filename=\"{doc.file_name}_page_{page_number}.jpg\"",
                    "X-Cache": "HIT"
                }
            )

        # 缓存未命中，加载文件并渲染
        file_bytes = storage.load_uploaded_file(doc.project_id, document_id)
        if not file_bytes:
            raise HTTPException(status_code=404, detail="File not found in storage")

        try:
            pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
            page = pdf_document[page_number - 1]  # 0-indexed

            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("jpeg", jpg_quality=85)

            pdf_document.close()

            # 保存到缓存
            page_cache.save_to_cache(document_id, page_number, img_bytes, dpi)

            return Response(
                content=img_bytes,
                media_type="image/jpeg",
                headers={
                    "Content-Disposition": f"inline; filename=\"{doc.file_name}_page_{page_number}.jpg\"",
                    "X-Cache": "MISS"
                }
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to render page: {str(e)}")
    else:
        # 图片文件：直接返回（只有第 1 页）
        if page_number != 1:
            raise HTTPException(status_code=400, detail="Image file only has 1 page")

        file_bytes = storage.load_uploaded_file(doc.project_id, document_id)
        if not file_bytes:
            raise HTTPException(status_code=404, detail="File not found in storage")

        content_type = "image/jpeg"
        if doc.file_name.lower().endswith('.png'):
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


# ============== 高光预览图片 API ==============

# 高光类别颜色 (RGBA)
HIGHLIGHT_COLORS = {
    'key_fact': (59, 130, 246, 80),      # blue
    'evidence': (16, 185, 129, 80),      # green
    'timeline': (245, 158, 11, 80),      # yellow/orange
    'date': (245, 158, 11, 80),          # yellow/orange (same as timeline)
    'entity': (139, 92, 246, 80),        # purple
    'financial': (236, 72, 153, 80),     # pink
    'company_name': (139, 92, 246, 80),  # purple (same as entity)
    'address': (16, 185, 129, 80),       # green (same as evidence)
    'default': (251, 191, 36, 80),       # amber
}


@router.get("/page/{document_id}/{page_number}/preview")
async def get_page_with_highlights(
    document_id: str,
    page_number: int,
    dpi: int = 150,
    db: Session = Depends(get_db)
):
    """
    获取带高光标注的页面预览图片

    将高光框直接渲染到 PDF 页面图片上返回，用于调试和预览。
    坐标转换: normalized (0-1000) -> pixel coordinates
    """
    if not PDF_SUPPORT:
        raise HTTPException(status_code=500, detail="PDF support not available")

    if not PIL_SUPPORT:
        raise HTTPException(status_code=500, detail="PIL/Pillow not available")

    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 验证页码
    if page_number < 1 or page_number > doc.page_count:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid page number. Document has {doc.page_count} pages."
        )

    # 加载原始文件
    file_bytes = storage.load_uploaded_file(doc.project_id, document_id)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File not found in storage")

    # 渲染 PDF 页面为图片
    try:
        if doc.file_name.lower().endswith('.pdf'):
            pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
            page = pdf_document[page_number - 1]

            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            img_width = pix.width
            img_height = pix.height

            pdf_document.close()
        else:
            # 图片文件
            img_bytes = file_bytes
            img = Image.open(io.BytesIO(file_bytes))
            img_width, img_height = img.size
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render page: {str(e)}")

    # 获取该页的高光数据
    highlights = highlight_service.get_highlights_for_document(document_id, db, page_number)

    # 如果没有高光，直接返回原图
    if not highlights:
        return Response(
            content=img_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition": f"inline; filename=\"{doc.file_name}_page_{page_number}_preview.png\""
            }
        )

    # 使用 Pillow 绘制高光框
    try:
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        # 创建一个透明图层用于绘制高光
        overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)

        for hl in highlights:
            bbox = hl.get('bbox')
            if not bbox:
                continue

            x1 = bbox.get('x1')
            y1 = bbox.get('y1')
            x2 = bbox.get('x2')
            y2 = bbox.get('y2')

            if x1 is None or y1 is None or x2 is None or y2 is None:
                continue

            # 转换归一化坐标 (0-1000) 到像素坐标
            px1 = int((x1 / 1000) * img_width)
            py1 = int((y1 / 1000) * img_height)
            px2 = int((x2 / 1000) * img_width)
            py2 = int((y2 / 1000) * img_height)

            # 获取颜色
            category = hl.get('category', '').lower() if hl.get('category') else ''
            color = HIGHLIGHT_COLORS.get(category, HIGHLIGHT_COLORS['default'])

            # 绘制半透明矩形
            draw.rectangle([px1, py1, px2, py2], fill=color)

            # 绘制边框 (更深的颜色)
            border_color = (color[0], color[1], color[2], 200)
            draw.rectangle([px1, py1, px2, py2], outline=border_color, width=2)

        # 合并图层
        img = Image.alpha_composite(img, overlay)

        # 转换回 RGB 并保存为 PNG
        img = img.convert('RGB')
        output = io.BytesIO()
        img.save(output, format='PNG', quality=95)
        output.seek(0)

        return Response(
            content=output.getvalue(),
            media_type="image/png",
            headers={
                "Content-Disposition": f"inline; filename=\"{doc.file_name}_page_{page_number}_preview.png\"",
                "X-Highlight-Count": str(len(highlights))
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to draw highlights: {str(e)}")


# ============== 保存高亮图片 API ==============

@router.post("/{document_id}/save")
async def save_highlighted_image(
    document_id: str,
    data: SaveHighlightImageRequest,
    db: Session = Depends(get_db)
):
    """
    保存带高亮的图片

    前端将 Canvas 导出为 base64，后端保存到存储
    """
    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 解码 base64 图片
    try:
        # 移除可能的 data URL 前缀
        image_data = data.image_base64
        if "," in image_data:
            image_data = image_data.split(",")[1]

        image_bytes = base64.b64decode(image_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image: {str(e)}")

    # 保存到存储
    try:
        file_name = f"{document_id}_page_{data.page_number}.png"
        url = storage.save_highlight_image(doc.project_id, document_id, data.page_number, image_bytes)

        # 更新文档的 highlight_image_urls
        existing_urls = {}
        if doc.highlight_image_urls:
            try:
                existing_urls = json.loads(doc.highlight_image_urls)
            except:
                pass

        existing_urls[str(data.page_number)] = url
        doc.highlight_image_urls = json.dumps(existing_urls)
        db.commit()

        return {
            "success": True,
            "document_id": document_id,
            "page_number": data.page_number,
            "url": url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}")


@router.get("/{document_id}/saved-images")
async def get_saved_highlight_images(
    document_id: str,
    db: Session = Depends(get_db)
):
    """获取已保存的高亮图片列表"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    image_urls = {}
    if doc.highlight_image_urls:
        try:
            image_urls = json.loads(doc.highlight_image_urls)
        except:
            pass

    return {
        "document_id": document_id,
        "image_urls": image_urls,
        "total_saved": len(image_urls)
    }


# ============== 批量操作 API ==============

@router.post("/batch/{project_id}")
async def trigger_batch_highlight(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """批量触发项目中所有已完成 OCR 文档的高亮分析"""
    # 查找所有已完成 OCR 且未进行高亮分析的文档
    documents = db.query(Document).filter(
        Document.project_id == project_id,
        Document.ocr_status == OCRStatus.COMPLETED.value,
        Document.highlight_status.is_(None)  # 未开始高亮
    ).all()

    # 过滤有 text_blocks 的文档
    eligible_docs = []
    for doc in documents:
        block_count = db.query(TextBlock).filter(TextBlock.document_id == doc.id).count()
        if block_count > 0:
            eligible_docs.append(doc)

    if not eligible_docs:
        return {
            "success": True,
            "message": "No eligible documents for highlight analysis",
            "total": 0
        }

    # 启动后台任务
    for doc in eligible_docs:
        doc.highlight_status = HighlightStatus.PENDING.value
        background_tasks.add_task(
            run_highlight_analysis_background,
            doc.id
        )

    db.commit()

    return {
        "success": True,
        "message": f"Started highlight analysis for {len(eligible_docs)} documents",
        "total": len(eligible_docs),
        "documents": [{"id": d.id, "file_name": d.file_name} for d in eligible_docs]
    }


# ============== 缓存管理 API ==============

@router.get("/cache/stats")
async def get_cache_stats():
    """获取页面图片缓存统计"""
    stats = page_cache.get_cache_stats()
    return {
        "success": True,
        "cache_root": str(page_cache.CACHE_ROOT),
        **stats
    }


@router.post("/cache/prerender/{document_id}")
async def prerender_document_pages(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    手动触发文档页面预渲染

    用于对已存在的文档进行预渲染（OCR 完成前上传的老文档）
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not doc.file_name.lower().endswith('.pdf'):
        return {
            "success": False,
            "message": "Only PDF documents can be prerendered"
        }

    # 检查是否已缓存
    cached_pages = page_cache.get_cached_pages(document_id)
    if len(cached_pages) >= doc.page_count:
        return {
            "success": True,
            "message": "Document already fully cached",
            "cached_pages": len(cached_pages),
            "total_pages": doc.page_count
        }

    # 后台执行预渲染
    def do_prerender():
        file_bytes = storage.load_uploaded_file(doc.project_id, document_id)
        if file_bytes:
            page_cache.prerender_document(document_id, file_bytes, doc.page_count)

    background_tasks.add_task(do_prerender)

    return {
        "success": True,
        "message": "Prerender started in background",
        "already_cached": len(cached_pages),
        "total_pages": doc.page_count
    }


@router.post("/cache/prerender-project/{project_id}")
async def prerender_project_documents(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    预渲染项目中所有 PDF 文档

    用于批量预渲染老文档
    """
    docs = db.query(Document).filter(
        Document.project_id == project_id,
        Document.ocr_status == OCRStatus.COMPLETED.value
    ).all()

    pdf_docs = [d for d in docs if d.file_name.lower().endswith('.pdf')]

    if not pdf_docs:
        return {
            "success": True,
            "message": "No PDF documents found",
            "total": 0
        }

    # 后台执行预渲染
    def do_prerender_all():
        for doc in pdf_docs:
            try:
                file_bytes = storage.load_uploaded_file(doc.project_id, doc.id)
                if file_bytes:
                    page_cache.prerender_document(doc.id, file_bytes, doc.page_count)
            except Exception as e:
                print(f"Failed to prerender {doc.id}: {e}")

    background_tasks.add_task(do_prerender_all)

    return {
        "success": True,
        "message": f"Prerender started for {len(pdf_docs)} PDF documents",
        "total": len(pdf_docs),
        "documents": [{"id": d.id, "file_name": d.file_name, "pages": d.page_count} for d in pdf_docs]
    }


@router.delete("/cache/cleanup")
async def cleanup_cache(max_age_days: int = 7):
    """
    清理过期缓存

    默认清理 7 天未访问的缓存
    """
    cleaned = page_cache.cleanup_old_cache(max_age_days)
    return {
        "success": True,
        "message": f"Cleaned {cleaned} old cache directories",
        "cleaned_count": cleaned
    }


@router.delete("/cache/{document_id}")
async def delete_document_cache(document_id: str):
    """删除指定文档的缓存"""
    success = page_cache.delete_document_cache(document_id)
    return {
        "success": success,
        "message": "Cache deleted" if success else "Failed to delete cache",
        "document_id": document_id
    }
