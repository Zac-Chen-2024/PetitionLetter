"""
BBox Matcher Service - Quote 到 BBox 的匹配服务

功能:
- 将 LLM 提取的 quote 文本与 OCR 识别的 text_blocks 进行匹配
- 返回匹配到的 BBox 坐标，用于前端高亮显示

匹配策略:
1. 归一化处理: 统一空白符、标点、去除 HTML 标签
2. 精确子串匹配: quote 是否是某个 block 的子串
3. 模糊匹配: 使用 difflib 计算相似度
4. 跨块匹配: 合并相邻块进行匹配
"""

import re
import unicodedata
from html import unescape
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher
from sqlalchemy.orm import Session

from app.models.document import TextBlock


def normalize_text(text: str) -> str:
    """
    归一化文本，用于匹配比较

    - 去除 HTML 标签
    - 转换 HTML 实体
    - 转换为小写
    - 统一全角/半角字符
    - 去除多余空白
    - 统一标点符号
    """
    if not text:
        return ""

    # 去除 HTML 标签 (将标签替换为空格，避免相邻文本黏连)
    text = re.sub(r'<[^>]+>', ' ', text)

    # 处理 HTML 实体 (&quot; &amp; &lt; &gt; etc.)
    text = unescape(text)

    # Unicode 归一化 (NFKC: 兼容性分解后再组合)
    text = unicodedata.normalize('NFKC', text)

    # 转小写
    text = text.lower()

    # 统一常见标点
    punct_map = {
        '，': ',',
        '。': '.',
        '：': ':',
        '；': ';',
        '"': '"',
        '"': '"',
        ''': "'",
        ''': "'",
        '（': '(',
        '）': ')',
        '【': '[',
        '】': ']',
        '、': ',',
    }
    for cn, en in punct_map.items():
        text = text.replace(cn, en)

    # 去除多余空白 (包括换行符)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def calculate_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度 (0-1)

    使用 SequenceMatcher，适合处理 OCR 可能的小错误
    """
    if not text1 or not text2:
        return 0.0

    return SequenceMatcher(None, text1, text2).ratio()


def find_substring_match(quote: str, block_text: str) -> Optional[Tuple[int, int]]:
    """
    查找 quote 在 block_text 中的位置

    返回: (start, end) 或 None
    """
    quote_norm = normalize_text(quote)
    block_norm = normalize_text(block_text)

    if quote_norm in block_norm:
        start = block_norm.find(quote_norm)
        return (start, start + len(quote_norm))

    return None


def match_quote_to_blocks(
    quote_text: str,
    document_id: str,
    db: Session,
    page_hint: Optional[int] = None,
    similarity_threshold: float = 0.7
) -> List[Dict[str, Any]]:
    """
    将 quote 文本匹配到 text_blocks

    Args:
        quote_text: 要匹配的引用文本
        document_id: 文档 ID
        db: 数据库会话
        page_hint: 可选的页码提示（优先搜索该页）
        similarity_threshold: 相似度阈值 (0-1)

    Returns:
        匹配结果列表:
        [
            {
                "block_id": "p1_b3",
                "page_number": 1,
                "text_content": "原始文本...",
                "bbox": {"x1": 10, "y1": 20, "x2": 100, "y2": 50},
                "match_type": "exact" | "fuzzy" | "partial",
                "match_score": 0.95
            }
        ]
    """
    if not quote_text or not quote_text.strip():
        return []

    # 查询该文档的所有 text_blocks
    query = db.query(TextBlock).filter(TextBlock.document_id == document_id)

    # 如果有页码提示，按页码排序（优先匹配该页）
    if page_hint:
        # 先查该页，再查其他页
        blocks = query.order_by(
            (TextBlock.page_number != page_hint).asc(),
            TextBlock.page_number.asc()
        ).all()
    else:
        blocks = query.order_by(TextBlock.page_number, TextBlock.block_id).all()

    if not blocks:
        return []

    quote_norm = normalize_text(quote_text)
    matches = []

    # 策略 1: 精确子串匹配
    for block in blocks:
        block_text = block.text_content or ""
        if find_substring_match(quote_text, block_text):
            matches.append({
                "block_id": block.block_id,
                "page_number": block.page_number,
                "text_content": block.text_content,
                "bbox": {
                    "x1": block.bbox_x1,
                    "y1": block.bbox_y1,
                    "x2": block.bbox_x2,
                    "y2": block.bbox_y2
                },
                "match_type": "exact",
                "match_score": 1.0
            })

    # 如果精确匹配成功，直接返回
    if matches:
        return matches

    # 策略 2: 模糊匹配单个块
    block_scores = []
    for block in blocks:
        block_text = block.text_content or ""
        block_norm = normalize_text(block_text)

        if not block_norm:
            continue

        # 计算相似度
        similarity = calculate_similarity(quote_norm, block_norm)

        # 也检查 quote 是否是 block 的一部分（部分匹配）
        partial_score = 0.0
        if len(quote_norm) < len(block_norm):
            # quote 可能是 block 的一部分
            if quote_norm in block_norm:
                partial_score = len(quote_norm) / len(block_norm)

        max_score = max(similarity, partial_score)

        if max_score >= similarity_threshold:
            block_scores.append({
                "block": block,
                "score": max_score,
                "match_type": "fuzzy" if similarity > partial_score else "partial"
            })

    # 按分数排序
    block_scores.sort(key=lambda x: x["score"], reverse=True)

    # 返回最佳匹配
    for item in block_scores[:3]:  # 最多返回 3 个候选
        block = item["block"]
        matches.append({
            "block_id": block.block_id,
            "page_number": block.page_number,
            "text_content": block.text_content,
            "bbox": {
                "x1": block.bbox_x1,
                "y1": block.bbox_y1,
                "x2": block.bbox_x2,
                "y2": block.bbox_y2
            },
            "match_type": item["match_type"],
            "match_score": round(item["score"], 3)
        })

    # 策略 3: 跨块匹配（如果单块匹配效果不好）
    if not matches or (matches and matches[0]["match_score"] < 0.8):
        cross_matches = try_cross_block_match(quote_norm, blocks, similarity_threshold)
        if cross_matches:
            # 合并跨块匹配结果
            for cm in cross_matches:
                if cm["match_score"] > (matches[0]["match_score"] if matches else 0):
                    matches.insert(0, cm)

    return matches


def try_cross_block_match(
    quote_norm: str,
    blocks: List[TextBlock],
    similarity_threshold: float
) -> List[Dict[str, Any]]:
    """
    尝试跨块匹配：合并相邻的块进行匹配

    适用于 quote 跨越多个 text_block 的情况
    """
    if len(blocks) < 2:
        return []

    results = []

    # 按页分组
    blocks_by_page = {}
    for block in blocks:
        page = block.page_number
        if page not in blocks_by_page:
            blocks_by_page[page] = []
        blocks_by_page[page].append(block)

    # 对每页的块按 block_id 排序
    for page, page_blocks in blocks_by_page.items():
        page_blocks.sort(key=lambda b: b.block_id)

        # 尝试合并 2-3 个相邻块
        for window_size in [2, 3]:
            for i in range(len(page_blocks) - window_size + 1):
                window = page_blocks[i:i + window_size]

                # 合并文本
                combined_text = " ".join([
                    normalize_text(b.text_content or "") for b in window
                ])

                if not combined_text:
                    continue

                # 计算相似度
                similarity = calculate_similarity(quote_norm, combined_text)

                # 也检查子串匹配
                if quote_norm in combined_text:
                    similarity = max(similarity, 0.9)

                if similarity >= similarity_threshold:
                    # 计算合并后的 bbox（取所有块的外包围盒）
                    min_x1 = min(b.bbox_x1 for b in window if b.bbox_x1 is not None)
                    min_y1 = min(b.bbox_y1 for b in window if b.bbox_y1 is not None)
                    max_x2 = max(b.bbox_x2 for b in window if b.bbox_x2 is not None)
                    max_y2 = max(b.bbox_y2 for b in window if b.bbox_y2 is not None)

                    results.append({
                        "block_id": f"{window[0].block_id}~{window[-1].block_id}",
                        "page_number": page,
                        "text_content": " ".join([b.text_content or "" for b in window]),
                        "bbox": {
                            "x1": min_x1,
                            "y1": min_y1,
                            "x2": max_x2,
                            "y2": max_y2
                        },
                        "match_type": "cross_block",
                        "match_score": round(similarity, 3),
                        "blocks_merged": [b.block_id for b in window]
                    })

    # 按分数排序
    results.sort(key=lambda x: x["match_score"], reverse=True)

    return results[:2]  # 最多返回 2 个跨块匹配结果


def batch_match_quotes(
    quotes: List[Dict[str, Any]],
    document_id: str,
    db: Session,
    similarity_threshold: float = 0.7
) -> List[Dict[str, Any]]:
    """
    批量匹配多个 quotes

    Args:
        quotes: quote 列表，每个元素包含 {"quote": "...", "page": 1}
        document_id: 文档 ID
        db: 数据库会话
        similarity_threshold: 相似度阈值

    Returns:
        匹配结果列表:
        [
            {
                "quote": "原文引用...",
                "page_hint": 1,
                "matches": [...匹配结果...]
            }
        ]
    """
    results = []

    for q in quotes:
        quote_text = q.get("quote", "")
        page_hint = q.get("page")

        matches = match_quote_to_blocks(
            quote_text=quote_text,
            document_id=document_id,
            db=db,
            page_hint=page_hint,
            similarity_threshold=similarity_threshold
        )

        results.append({
            "quote": quote_text,
            "page_hint": page_hint,
            "matches": matches,
            "matched": len(matches) > 0
        })

    return results


def match_text_to_blocks(
    search_text: str,
    text_blocks: List[TextBlock],
    page_hint: Optional[int] = None,
    similarity_threshold: float = 0.6
) -> Dict[str, Any]:
    """
    将搜索文本匹配到 text_blocks（内存版本，不需要数据库查询）

    Args:
        search_text: 要匹配的文本
        text_blocks: TextBlock 对象列表
        page_hint: 可选的页码提示
        similarity_threshold: 相似度阈值

    Returns:
        {
            "matched": True/False,
            "matches": [
                {
                    "block_id": "p1_b3",
                    "page_number": 1,
                    "bbox": {"x1": 10, "y1": 20, "x2": 100, "y2": 50},
                    "match_type": "exact"|"fuzzy"|"partial",
                    "match_score": 0.95
                }
            ]
        }
    """
    if not search_text or not search_text.strip():
        return {"matched": False, "matches": []}

    if not text_blocks:
        return {"matched": False, "matches": []}

    search_norm = normalize_text(search_text)
    matches = []

    # 如果有页码提示，先排序块
    blocks = list(text_blocks)
    if page_hint:
        blocks.sort(key=lambda b: (b.page_number != page_hint, b.page_number))

    # 策略 1: 精确子串匹配
    for block in blocks:
        block_text = block.text_content or ""
        if find_substring_match(search_text, block_text):
            matches.append({
                "block_id": block.block_id,
                "page_number": block.page_number,
                "text_content": block.text_content,
                "bbox": {
                    "x1": block.bbox_x1,
                    "y1": block.bbox_y1,
                    "x2": block.bbox_x2,
                    "y2": block.bbox_y2
                },
                "match_type": "exact",
                "match_score": 1.0
            })

    if matches:
        return {"matched": True, "matches": matches}

    # 策略 2: 模糊匹配单个块
    block_scores = []
    for block in blocks:
        block_text = block.text_content or ""
        block_norm = normalize_text(block_text)

        if not block_norm:
            continue

        similarity = calculate_similarity(search_norm, block_norm)

        # 也检查部分匹配
        partial_score = 0.0
        if len(search_norm) < len(block_norm) and search_norm in block_norm:
            partial_score = len(search_norm) / len(block_norm)

        max_score = max(similarity, partial_score)

        if max_score >= similarity_threshold:
            block_scores.append({
                "block": block,
                "score": max_score,
                "match_type": "fuzzy" if similarity > partial_score else "partial"
            })

    block_scores.sort(key=lambda x: x["score"], reverse=True)

    for item in block_scores[:3]:
        block = item["block"]
        matches.append({
            "block_id": block.block_id,
            "page_number": block.page_number,
            "text_content": block.text_content,
            "bbox": {
                "x1": block.bbox_x1,
                "y1": block.bbox_y1,
                "x2": block.bbox_x2,
                "y2": block.bbox_y2
            },
            "match_type": item["match_type"],
            "match_score": round(item["score"], 3)
        })

    # 策略 3: 跨块匹配
    if not matches or (matches and matches[0]["match_score"] < 0.8):
        cross_matches = try_cross_block_match(search_norm, blocks, similarity_threshold)
        for cm in cross_matches:
            if cm["match_score"] > (matches[0]["match_score"] if matches else 0):
                matches.insert(0, cm)

    return {"matched": len(matches) > 0, "matches": matches}


# ============== 测试函数 ==============

def test_normalize():
    """测试归一化函数"""
    test_cases = [
        ("Hello  World", "hello world"),
        ("中文，测试。", "中文,测试."),
        ("Mixed 中英文", "mixed 中英文"),
        ("  多余   空格  ", "多余 空格"),
    ]

    print("归一化测试:")
    for original, expected in test_cases:
        result = normalize_text(original)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{original}' -> '{result}' (expected: '{expected}')")


def test_similarity():
    """测试相似度计算"""
    test_cases = [
        ("hello world", "hello world", 1.0),
        ("hello world", "hello  world", 0.9),  # 近似
        ("abc", "xyz", 0.0),
    ]

    print("\n相似度测试:")
    for text1, text2, expected_min in test_cases:
        score = calculate_similarity(normalize_text(text1), normalize_text(text2))
        status = "✓" if score >= expected_min else "✗"
        print(f"  {status} '{text1}' vs '{text2}' = {score:.2f} (min: {expected_min})")


if __name__ == "__main__":
    test_normalize()
    test_similarity()
