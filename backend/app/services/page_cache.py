"""
PDF 页面图片缓存服务

功能：
1. 缓存 PDF 页面渲染的图片到磁盘
2. OCR 完成后预渲染所有页面
3. 文档删除时清理缓存
"""

import os
import shutil
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# 缓存根目录
CACHE_ROOT = Path("/workspace/pdf_cache")

# 确保缓存目录存在
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def get_cache_dir(document_id: str) -> Path:
    """获取文档的缓存目录"""
    return CACHE_ROOT / document_id


def get_cache_path(document_id: str, page_number: int, dpi: int = 100) -> Path:
    """获取页面缓存文件路径"""
    cache_dir = get_cache_dir(document_id)
    # 包含 DPI 信息以支持不同分辨率
    return cache_dir / f"page_{page_number}_dpi{dpi}.jpg"


def get_cached_image(document_id: str, page_number: int, dpi: int = 100) -> Optional[bytes]:
    """
    获取缓存的页面图片

    Returns:
        图片字节数据，如果缓存不存在返回 None
    """
    cache_path = get_cache_path(document_id, page_number, dpi)

    if cache_path.exists():
        try:
            with open(cache_path, 'rb') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Failed to read cache {cache_path}: {e}")
            return None

    return None


def save_to_cache(document_id: str, page_number: int, image_bytes: bytes, dpi: int = 100) -> bool:
    """
    保存页面图片到缓存

    Returns:
        是否保存成功
    """
    cache_dir = get_cache_dir(document_id)
    cache_path = get_cache_path(document_id, page_number, dpi)

    try:
        # 确保目录存在
        cache_dir.mkdir(parents=True, exist_ok=True)

        # 写入文件
        with open(cache_path, 'wb') as f:
            f.write(image_bytes)

        logger.debug(f"Cached page {page_number} for document {document_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save cache {cache_path}: {e}")
        return False


def is_document_cached(document_id: str, total_pages: int, dpi: int = 100) -> bool:
    """
    检查文档是否已完全缓存

    Returns:
        所有页面是否都已缓存
    """
    for page in range(1, total_pages + 1):
        if not get_cache_path(document_id, page, dpi).exists():
            return False
    return True


def get_cached_pages(document_id: str, dpi: int = 100) -> list[int]:
    """
    获取已缓存的页面列表

    Returns:
        已缓存的页码列表
    """
    cache_dir = get_cache_dir(document_id)
    if not cache_dir.exists():
        return []

    cached_pages = []
    for file in cache_dir.glob(f"page_*_dpi{dpi}.jpg"):
        try:
            # 从文件名提取页码: page_1_dpi100.jpg -> 1
            page_num = int(file.stem.split('_')[1])
            cached_pages.append(page_num)
        except (IndexError, ValueError):
            continue

    return sorted(cached_pages)


def delete_document_cache(document_id: str) -> bool:
    """
    删除文档的所有缓存

    Returns:
        是否删除成功
    """
    cache_dir = get_cache_dir(document_id)

    if cache_dir.exists():
        try:
            shutil.rmtree(cache_dir)
            logger.info(f"Deleted cache for document {document_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete cache {cache_dir}: {e}")
            return False

    return True  # 目录不存在也算成功


def prerender_document(document_id: str, file_bytes: bytes, total_pages: int, dpi: int = 100) -> int:
    """
    预渲染文档的所有页面到缓存

    Args:
        document_id: 文档 ID
        file_bytes: PDF 文件字节
        total_pages: 总页数
        dpi: 渲染 DPI

    Returns:
        成功渲染的页数
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF not available for prerendering")
        return 0

    rendered_count = 0

    try:
        pdf_document = fitz.open(stream=file_bytes, filetype="pdf")

        for page_number in range(1, total_pages + 1):
            # 检查是否已缓存
            if get_cache_path(document_id, page_number, dpi).exists():
                rendered_count += 1
                continue

            try:
                page = pdf_document[page_number - 1]
                zoom = dpi / 72
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("jpeg", jpg_quality=85)

                if save_to_cache(document_id, page_number, img_bytes, dpi):
                    rendered_count += 1

            except Exception as e:
                logger.error(f"Failed to render page {page_number} of {document_id}: {e}")
                continue

        pdf_document.close()
        logger.info(f"Prerendered {rendered_count}/{total_pages} pages for document {document_id}")

    except Exception as e:
        logger.error(f"Failed to prerender document {document_id}: {e}")

    return rendered_count


def get_cache_stats() -> dict:
    """
    获取缓存统计信息

    Returns:
        缓存统计：文档数、总文件数、总大小
    """
    if not CACHE_ROOT.exists():
        return {"documents": 0, "files": 0, "size_mb": 0}

    doc_count = 0
    file_count = 0
    total_size = 0

    for doc_dir in CACHE_ROOT.iterdir():
        if doc_dir.is_dir():
            doc_count += 1
            for file in doc_dir.glob("*.jpg"):
                file_count += 1
                total_size += file.stat().st_size

    return {
        "documents": doc_count,
        "files": file_count,
        "size_mb": round(total_size / (1024 * 1024), 2)
    }


def cleanup_old_cache(max_age_days: int = 7) -> int:
    """
    清理超过指定天数未访问的缓存

    Args:
        max_age_days: 最大保留天数

    Returns:
        清理的文档数
    """
    import time

    if not CACHE_ROOT.exists():
        return 0

    max_age_seconds = max_age_days * 24 * 60 * 60
    current_time = time.time()
    cleaned_count = 0

    for doc_dir in CACHE_ROOT.iterdir():
        if doc_dir.is_dir():
            # 检查目录的最后修改时间
            try:
                mtime = doc_dir.stat().st_mtime
                if current_time - mtime > max_age_seconds:
                    shutil.rmtree(doc_dir)
                    cleaned_count += 1
                    logger.info(f"Cleaned old cache: {doc_dir.name}")
            except Exception as e:
                logger.warning(f"Failed to check/clean {doc_dir}: {e}")

    return cleaned_count
