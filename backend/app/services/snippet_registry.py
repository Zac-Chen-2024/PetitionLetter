"""
Snippet Registry - 从 L1/EB1A 分析结果构建带 ID 的 snippet 注册表

每个 snippet 代表一个可溯源的证据片段，包含：
- 确定性 ID (基于内容生成)
- 来源信息 (exhibit_id, material_id, page)
- 文本内容
- BBox 坐标
- 关联的标准 (standard_key)
"""

import hashlib
import json
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime, timezone

# 数据存储根目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


def generate_snippet_id(exhibit_id: str, page: int, quote_text: str) -> str:
    """基于内容生成确定性 snippet_id

    使用 exhibit_id + page + quote_text 前100字符的 MD5 哈希
    这确保相同内容总是生成相同的 ID

    Args:
        exhibit_id: 展品 ID
        page: 页码
        quote_text: 引用文本

    Returns:
        格式为 "snip_{hash8}" 的 snippet ID
    """
    content = f"{exhibit_id}:{page}:{quote_text[:100]}"
    hash_str = hashlib.md5(content.encode('utf-8')).hexdigest()[:8]
    return f"snip_{hash_str}"


def build_registry(project_id: str, analyses: List[Dict]) -> List[Dict]:
    """
    从 L1/EB1A 分析结果构建 snippet 注册表

    Args:
        project_id: 项目 ID
        analyses: L1/EB1A analyzer 的输出列表，每个元素包含:
            - exhibit_id: 展品 ID
            - document_id: 文档 ID
            - quotes: [{quote, standard_key, page, bbox, matched_block_ids, source}]

    Returns:
        snippets: [{
            snippet_id,      # 唯一标识符
            document_id,     # 原始文档 ID
            exhibit_id,      # 展品 ID
            material_id,     # 材料 ID (如有)
            text,            # 引用文本
            page,            # 页码
            bbox,            # 边界框坐标 {x1, y1, x2, y2} 或 [x1, y1, x2, y2]
            standard_key,    # 关联的标准 (如 "qualifying_relationship")
            source_block_ids # 来源 text_block IDs
        }]
    """
    snippets = []
    seen_ids = set()

    for doc_analysis in analyses:
        exhibit_id = doc_analysis.get("exhibit_id", "")
        document_id = doc_analysis.get("document_id", "")

        quotes = doc_analysis.get("quotes", [])

        for q in quotes:
            quote_text = q.get("quote", "")
            page = q.get("page", 0)

            # 生成确定性 ID
            snippet_id = generate_snippet_id(exhibit_id, page, quote_text)

            # 跳过重复
            if snippet_id in seen_ids:
                continue
            seen_ids.add(snippet_id)

            # 提取 bbox (支持多种格式)
            bbox = q.get("bbox")
            if bbox is None:
                # 尝试从 source 中获取
                source = q.get("source", {})
                bbox = source.get("bbox")

            # 标准化 bbox 格式为 dict
            if isinstance(bbox, list) and len(bbox) == 4:
                bbox = {
                    "x1": bbox[0],
                    "y1": bbox[1],
                    "x2": bbox[2],
                    "y2": bbox[3]
                }

            # 提取 material_id
            source = q.get("source", {})
            material_id = source.get("material_id", "")

            snippets.append({
                "snippet_id": snippet_id,
                "document_id": document_id,
                "exhibit_id": exhibit_id,
                "material_id": material_id,
                "text": quote_text,
                "page": page,
                "bbox": bbox,
                "standard_key": q.get("standard_key", ""),
                "source_block_ids": q.get("matched_block_ids", [])
            })

    # 保存注册表
    save_registry(project_id, snippets)

    return snippets


def build_registry_from_quote_index_map(project_id: str, quote_index_map: Dict) -> List[Dict]:
    """
    从 quote_index_map 构建 snippet 注册表

    这是另一种构建方式，直接使用 relationship analysis 产出的 quote_index_map

    Args:
        project_id: 项目 ID
        quote_index_map: {idx: {exhibit_id, material_id, page, quote, standard_key, bbox}}

    Returns:
        snippets 列表
    """
    snippets = []
    seen_ids = set()

    for idx, quote_data in quote_index_map.items():
        exhibit_id = quote_data.get("exhibit_id", "")
        page = quote_data.get("page", 0)
        quote_text = quote_data.get("quote", "")

        snippet_id = generate_snippet_id(exhibit_id, page, quote_text)

        if snippet_id in seen_ids:
            continue
        seen_ids.add(snippet_id)

        # 提取 bbox
        bbox = quote_data.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            bbox = {
                "x1": bbox[0],
                "y1": bbox[1],
                "x2": bbox[2],
                "y2": bbox[3]
            }

        snippets.append({
            "snippet_id": snippet_id,
            "quote_index": int(idx),  # 保留原始索引用于关联
            "document_id": quote_data.get("document_id", ""),
            "exhibit_id": exhibit_id,
            "material_id": quote_data.get("material_id", ""),
            "text": quote_text,
            "page": page,
            "bbox": bbox,
            "standard_key": quote_data.get("standard_key", ""),
            "source_block_ids": quote_data.get("matched_block_ids", [])
        })

    # 按 quote_index 排序以保持顺序
    snippets.sort(key=lambda x: x.get("quote_index", 0))

    save_registry(project_id, snippets)
    return snippets


def get_snippets_dir(project_id: str) -> Path:
    """获取 snippets 存储目录"""
    snippets_dir = PROJECTS_DIR / project_id / "snippets"
    snippets_dir.mkdir(parents=True, exist_ok=True)
    return snippets_dir


def save_registry(project_id: str, snippets: List[Dict]):
    """保存 snippet 注册表到 JSON 文件"""
    snippets_dir = get_snippets_dir(project_id)
    registry_file = snippets_dir / "registry.json"

    data = {
        "version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "snippet_count": len(snippets),
        "snippets": snippets
    }

    with open(registry_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_registry(project_id: str) -> List[Dict]:
    """加载 snippet 注册表"""
    snippets_dir = get_snippets_dir(project_id)
    registry_file = snippets_dir / "registry.json"

    if not registry_file.exists():
        return []

    with open(registry_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get("snippets", [])


def get_snippet_by_id(project_id: str, snippet_id: str) -> Optional[Dict]:
    """根据 ID 获取单个 snippet"""
    snippets = load_registry(project_id)
    for s in snippets:
        if s.get("snippet_id") == snippet_id:
            return s
    return None


def get_snippets_by_standard(project_id: str, standard_key: str) -> List[Dict]:
    """获取某个标准下的所有 snippets"""
    snippets = load_registry(project_id)
    return [s for s in snippets if s.get("standard_key") == standard_key]


def get_snippets_by_exhibit(project_id: str, exhibit_id: str) -> List[Dict]:
    """获取某个展品下的所有 snippets"""
    snippets = load_registry(project_id)
    return [s for s in snippets if s.get("exhibit_id") == exhibit_id]


def update_snippet_standard(project_id: str, snippet_id: str, new_standard_key: str) -> Optional[Dict]:
    """更新 snippet 的 standard_key (律师手动映射)"""
    snippets = load_registry(project_id)

    for s in snippets:
        if s.get("snippet_id") == snippet_id:
            s["standard_key"] = new_standard_key
            save_registry(project_id, snippets)
            return s

    return None


def get_registry_stats(project_id: str) -> Dict:
    """获取注册表统计信息"""
    snippets = load_registry(project_id)

    if not snippets:
        return {
            "total_snippets": 0,
            "by_standard": {},
            "by_exhibit": {},
            "with_bbox": 0
        }

    by_standard = {}
    by_exhibit = {}
    with_bbox = 0

    for s in snippets:
        # 按标准统计
        std = s.get("standard_key", "unassigned")
        by_standard[std] = by_standard.get(std, 0) + 1

        # 按展品统计
        exhibit = s.get("exhibit_id", "unknown")
        by_exhibit[exhibit] = by_exhibit.get(exhibit, 0) + 1

        # 有 bbox 的统计
        if s.get("bbox"):
            with_bbox += 1

    return {
        "total_snippets": len(snippets),
        "by_standard": by_standard,
        "by_exhibit": by_exhibit,
        "with_bbox": with_bbox,
        "bbox_coverage": round(with_bbox / len(snippets) * 100, 1) if snippets else 0
    }
