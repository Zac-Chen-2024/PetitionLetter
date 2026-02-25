"""
Data Importer - 从 OCR 数据目录导入项目和文档

功能：
- scan_data_directory() - 扫描 data/ 目录获取所有人名
- create_project_from_data() - 从数据创建项目
- import_exhibits() - 导入所有 exhibits
- ocr_blocks_to_snippets() - 将 text_blocks 转换为 snippets
- normalize_bbox() - 坐标归一化
"""

import json
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone

from .snippet_registry import generate_snippet_id, save_registry

# 数据目录
# BASE_DIR 指向 backend/, 项目根目录在上一级
BASE_DIR = Path(__file__).parent.parent.parent
PROJECT_ROOT = BASE_DIR.parent  # 项目根目录 (PetitionLetter/)
DATA_DIR = PROJECT_ROOT / "data"  # 原始 OCR 数据目录
PROJECTS_DIR = BASE_DIR / "data" / "projects"  # 项目数据存储在 backend/data/projects/

# 假设的页面尺寸（用于坐标归一化）
# 从 OCR 数据看，坐标范围约 0-900，接近 1000
ASSUMED_PAGE_WIDTH = 1000
ASSUMED_PAGE_HEIGHT = 1000


def scan_data_directory() -> List[Dict]:
    """
    扫描 data/ 目录获取所有可导入的数据

    Returns:
        List of {
            "name": 人名,
            "path": 目录路径,
            "exhibit_count": exhibit 数量,
            "page_count": 总页数
        }
    """
    results = []

    if not DATA_DIR.exists():
        return results

    for item in DATA_DIR.iterdir():
        # 跳过 projects 目录和非目录项
        if item.name == "projects" or not item.is_dir():
            continue

        # 统计 exhibit 和页面数量
        exhibit_count = 0
        page_count = 0

        for exhibit_dir in item.iterdir():
            if exhibit_dir.is_dir():
                exhibit_count += 1
                for f in exhibit_dir.glob("page_*.json"):
                    page_count += 1

        if exhibit_count > 0:
            results.append({
                "name": item.name,
                "path": str(item),
                "exhibit_count": exhibit_count,
                "page_count": page_count
            })

    return results


def sanitize_project_id(name: str) -> str:
    """将人名转换为有效的项目 ID"""
    # 转小写，空格替换为下划线，移除特殊字符
    project_id = name.lower()
    project_id = re.sub(r'\s+', '_', project_id)
    project_id = re.sub(r'[^a-z0-9_]', '', project_id)
    return project_id


def normalize_bbox(bbox: Dict, page_width: int = ASSUMED_PAGE_WIDTH, page_height: int = ASSUMED_PAGE_HEIGHT) -> Dict:
    """
    将绝对像素坐标归一化到 0-1000 范围

    Args:
        bbox: {"x1": int, "y1": int, "x2": int, "y2": int} 或 list
        page_width: 页面宽度
        page_height: 页面高度

    Returns:
        归一化后的 bbox dict
    """
    # 处理 list 格式
    if isinstance(bbox, list) and len(bbox) == 4:
        bbox = {"x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3]}

    if not bbox or not isinstance(bbox, dict):
        return None

    # 如果坐标已经在 0-1000 范围内，不需要归一化
    max_coord = max(bbox.get("x2", 0), bbox.get("y2", 0))
    if max_coord <= 1000:
        # 坐标看起来已经归一化或接近归一化
        return {
            "x1": int(bbox.get("x1", 0)),
            "y1": int(bbox.get("y1", 0)),
            "x2": int(bbox.get("x2", 0)),
            "y2": int(bbox.get("y2", 0))
        }

    # 需要归一化
    return {
        "x1": int(bbox["x1"] * 1000 / page_width),
        "y1": int(bbox["y1"] * 1000 / page_height),
        "x2": int(bbox["x2"] * 1000 / page_width),
        "y2": int(bbox["y2"] * 1000 / page_height)
    }


def read_page_json(page_path: Path) -> Optional[Dict]:
    """读取单个页面的 JSON 文件"""
    try:
        with open(page_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading {page_path}: {e}")
        return None


def import_exhibit(exhibit_dir: Path) -> Dict:
    """
    导入单个 exhibit 的所有页面

    Args:
        exhibit_dir: exhibit 目录路径 (如 A1, B1, etc.)

    Returns:
        {
            "exhibit_id": str,
            "pages": [{page_number, text_blocks, markdown_text}],
            "total_blocks": int
        }
    """
    exhibit_id = exhibit_dir.name
    pages = []
    total_blocks = 0

    # 获取所有 page_*.json 文件并排序
    page_files = sorted(
        exhibit_dir.glob("page_*.json"),
        key=lambda p: int(re.search(r'page_(\d+)', p.name).group(1))
    )

    for page_file in page_files:
        page_data = read_page_json(page_file)
        if page_data:
            page_number = page_data.get("page_number", 0)
            text_blocks = page_data.get("text_blocks", [])
            total_blocks += len(text_blocks)

            pages.append({
                "page_number": page_number,
                "text_blocks": text_blocks,
                "markdown_text": page_data.get("markdown_text", "")
            })

    return {
        "exhibit_id": exhibit_id,
        "pages": pages,
        "total_blocks": total_blocks
    }


def ocr_blocks_to_snippets(exhibit_id: str, pages: List[Dict]) -> List[Dict]:
    """
    将 OCR text_blocks 转换为 snippets

    Args:
        exhibit_id: exhibit ID (如 "A1")
        pages: 页面数据列表

    Returns:
        snippets 列表
    """
    snippets = []
    seen_ids = set()

    for page in pages:
        page_number = page.get("page_number", 0)
        text_blocks = page.get("text_blocks", [])

        for block in text_blocks:
            text_content = block.get("text_content", "").strip()

            # 跳过空内容或太短的内容
            if len(text_content) < 5:
                continue

            # 生成 snippet ID
            snippet_id = generate_snippet_id(exhibit_id, page_number, text_content)

            # 跳过重复
            if snippet_id in seen_ids:
                continue
            seen_ids.add(snippet_id)

            # 处理 bbox
            bbox = block.get("bbox")
            if bbox:
                bbox = normalize_bbox(bbox)

            snippets.append({
                "snippet_id": snippet_id,
                "document_id": f"doc_{exhibit_id}",
                "exhibit_id": exhibit_id,
                "material_id": "",
                "text": text_content,
                "page": page_number,
                "bbox": bbox,
                "standard_key": "",  # 待后续分析填充
                "source_block_ids": [block.get("block_id", "")],
                "block_type": block.get("block_type", "text")
            })

    return snippets


def create_project_directory(project_id: str) -> Path:
    """创建项目目录结构"""
    project_dir = PROJECTS_DIR / project_id

    # 创建必要的子目录
    (project_dir / "documents").mkdir(parents=True, exist_ok=True)
    (project_dir / "snippets").mkdir(parents=True, exist_ok=True)
    (project_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (project_dir / "writing").mkdir(parents=True, exist_ok=True)

    return project_dir


def save_project_metadata(project_id: str, metadata: Dict):
    """保存项目元数据"""
    project_dir = PROJECTS_DIR / project_id
    metadata_file = project_dir / "metadata.json"

    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def save_exhibit_document(project_id: str, exhibit_data: Dict):
    """保存 exhibit 文档数据"""
    project_dir = PROJECTS_DIR / project_id
    doc_file = project_dir / "documents" / f"{exhibit_data['exhibit_id']}.json"

    with open(doc_file, 'w', encoding='utf-8') as f:
        json.dump(exhibit_data, f, ensure_ascii=False, indent=2)


def _find_ocr_exhibit_dirs(person_dir: Path) -> List[Path]:
    """
    Find all OCR exhibit directories under person_dir.

    Handles multiple layouts:
      - data/{Name}/OCR/{ExhibitId}/page_*.json          (Yaruo Qu)
      - data/{Name}/OCR/ocr_results_l/{exhibit_id}/page_*.json  (Dehuan Liu)
      - data/{Name}/{ExhibitId}/page_*.json               (flat layout)
    """
    candidates: List[Path] = []

    # Strategy: recursively find dirs that contain page_*.json files
    ocr_dir = person_dir / "OCR"
    search_roots = []
    if ocr_dir.exists():
        search_roots.append(ocr_dir)
    else:
        search_roots.append(person_dir)

    for root in search_roots:
        for dirpath in root.rglob("*"):
            if not dirpath.is_dir():
                continue
            # A valid exhibit dir has at least one page_*.json
            if any(dirpath.glob("page_*.json")):
                candidates.append(dirpath)

    # Sort by exhibit name for deterministic order
    candidates.sort(key=lambda p: p.name.lower())
    return candidates


def import_person_data(person_name: str) -> Dict:
    """
    导入指定人的完整数据

    Args:
        person_name: 人名（如 "Yaruo Qu"）

    Returns:
        {
            "success": bool,
            "project_id": str,
            "exhibits_imported": int,
            "snippets_created": int,
            "error": str (if any)
        }
    """
    person_dir = DATA_DIR / person_name

    if not person_dir.exists():
        return {
            "success": False,
            "error": f"Directory not found: {person_dir}"
        }

    # 创建项目
    project_id = sanitize_project_id(person_name)
    project_dir = create_project_directory(project_id)

    # 统计信息
    exhibits_imported = 0
    total_blocks = 0
    exhibit_list = []

    # 自动发现 OCR exhibit 目录
    exhibit_dirs = _find_ocr_exhibit_dirs(person_dir)

    for exhibit_dir in exhibit_dirs:
        # 导入 exhibit (OCR 文档数据)
        exhibit_data = import_exhibit(exhibit_dir)

        if exhibit_data["pages"]:
            # Normalize exhibit_id to uppercase (a1 → A1)
            exhibit_data["exhibit_id"] = exhibit_data["exhibit_id"].upper()

            # 保存 exhibit 文档到 documents/ 目录
            save_exhibit_document(project_id, exhibit_data)
            exhibits_imported += 1
            total_blocks += exhibit_data["total_blocks"]

            exhibit_list.append({
                "exhibit_id": exhibit_data["exhibit_id"],
                "page_count": len(exhibit_data["pages"]),
                "block_count": exhibit_data["total_blocks"]
            })

    # NOTE: 不在此处创建 snippets。
    # Snippets 由 Extract All (unified_extractor) 通过 LLM 分析 OCR 数据后生成。

    # 保存项目元数据
    metadata = {
        "project_id": project_id,
        "person_name": person_name,
        "visa_type": "EB-1A",  # 默认 EB-1A
        "pipeline_stage": "ocr_complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(person_dir),
        "exhibits": exhibit_list,
        "stats": {
            "exhibit_count": exhibits_imported,
            "total_blocks": total_blocks,
        }
    }
    save_project_metadata(project_id, metadata)

    return {
        "success": True,
        "project_id": project_id,
        "exhibits_imported": exhibits_imported,
        "total_blocks": total_blocks,
    }


def get_import_status(project_id: str) -> Optional[Dict]:
    """获取项目导入状态"""
    project_dir = PROJECTS_DIR / project_id
    metadata_file = project_dir / "metadata.json"

    if not metadata_file.exists():
        return None

    with open(metadata_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def list_projects() -> List[Dict]:
    """列出所有已创建的项目"""
    projects = []

    if not PROJECTS_DIR.exists():
        return projects

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        metadata_file = project_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
                projects.append({
                    "project_id": metadata.get("project_id"),
                    "person_name": metadata.get("person_name"),
                    "visa_type": metadata.get("visa_type"),
                    "created_at": metadata.get("created_at"),
                    "stats": metadata.get("stats", {})
                })

    return projects
