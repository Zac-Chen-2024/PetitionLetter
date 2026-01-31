"""
Quote Consolidator Service - 引用整合服务

功能:
- 基于位置信息的硬编码预整合
- 基于语义的 LLM Agent 整合
- 参考文档分页信息判断上下文连续性
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import json
import re


# =============================================
# 配置常量
# =============================================

# 位置整合阈值
Y_ADJACENT_THRESHOLD = 50      # y 坐标差值小于此值认为相邻（归一化坐标 0-1000）
X_OVERLAP_THRESHOLD = 100      # x 坐标重叠最小值
SAME_COLUMN_X_DIFF = 200       # 同一列的 x 坐标最大差值

# 句子延续特征
CONTINUATION_END_CHARS = [',', '，', ';', '；', ':', '：', '-', '–', '—']
CONTINUATION_START_LOWER = True  # 以小写字母开头表示延续

# 整合后的最大长度
MAX_CONSOLIDATED_LENGTH = 2000  # 整合后单条引用最大字符数


@dataclass
class QuoteWithPosition:
    """带位置信息的引用"""
    quote: str
    standard_key: str
    page: int
    document_id: str
    exhibit_id: str
    file_name: str
    bbox: Optional[Dict[str, int]] = None  # {"x1", "y1", "x2", "y2"}
    relevance: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quote": self.quote,
            "standard_key": self.standard_key,
            "page": self.page,
            "relevance": self.relevance,
            "source": {
                "document_id": self.document_id,
                "exhibit_id": self.exhibit_id,
                "file_name": self.file_name
            },
            "bbox": self.bbox
        }


# =============================================
# 位置预整合（硬编码规则）
# =============================================

def is_same_visual_block(q1: QuoteWithPosition, q2: QuoteWithPosition) -> bool:
    """
    判断两个引用是否属于同一视觉块（基于位置）

    规则:
    1. 必须在同一文档的同一页或相邻页
    2. y 坐标相邻（q2 紧跟在 q1 下方）
    3. x 坐标有重叠（在同一列）
    """
    # 不同文档不整合
    if q1.document_id != q2.document_id:
        return False

    # 页码差距超过1不整合
    if abs(q1.page - q2.page) > 1:
        return False

    # 如果缺少 bbox，无法判断
    if not q1.bbox or not q2.bbox:
        return False

    # 同一页：检查 y 相邻性
    if q1.page == q2.page:
        y_diff = q2.bbox["y1"] - q1.bbox["y2"]
        # q2 应该在 q1 下方，且距离不太远
        if y_diff < 0 or y_diff > Y_ADJACENT_THRESHOLD:
            return False

        # 检查 x 重叠
        x_overlap = min(q1.bbox["x2"], q2.bbox["x2"]) - max(q1.bbox["x1"], q2.bbox["x1"])
        if x_overlap < X_OVERLAP_THRESHOLD:
            return False

        return True

    # 跨页：q1 在前一页底部，q2 在后一页顶部
    if q1.page == q2.page - 1:
        # q1 应该在页面底部（y2 > 800）
        # q2 应该在页面顶部（y1 < 200）
        if q1.bbox["y2"] > 800 and q2.bbox["y1"] < 200:
            # x 坐标应该接近（同一列）
            x_diff = abs(q1.bbox["x1"] - q2.bbox["x1"])
            if x_diff < SAME_COLUMN_X_DIFF:
                return True

    return False


def is_sentence_continuation(q1: QuoteWithPosition, q2: QuoteWithPosition) -> bool:
    """
    判断 q2 是否是 q1 的句子延续

    规则:
    1. q1 以特定标点结尾（逗号、分号等）
    2. q2 以小写字母开头
    3. q1 不是完整句子（不以句号/问号/叹号结尾）
    """
    text1 = q1.quote.strip()
    text2 = q2.quote.strip()

    if not text1 or not text2:
        return False

    # q1 以完整句子结尾，不需要延续
    if text1[-1] in '.。!！?？':
        return False

    # q1 以延续标点结尾
    ends_with_continuation = text1[-1] in CONTINUATION_END_CHARS

    # q2 以小写字母开头
    starts_with_lower = text2[0].islower()

    # q1 以介词/连词结尾也是延续信号
    continuation_words = ['and', 'or', 'the', 'a', 'an', 'of', 'in', 'to', 'for', 'with', 'by']
    ends_with_continuation_word = any(text1.lower().endswith(' ' + w) for w in continuation_words)

    return ends_with_continuation or starts_with_lower or ends_with_continuation_word


def is_table_header_value_pair(q1: QuoteWithPosition, q2: QuoteWithPosition) -> bool:
    """
    判断是否是表格的 header-value 对

    规则:
    1. q1 是短文本（可能是表头/字段名）
    2. q2 是数值或短值
    3. 位置相邻
    """
    text1 = q1.quote.strip()
    text2 = q2.quote.strip()

    # q1 较短（表头通常不超过50字符）
    if len(text1) > 50:
        return False

    # q1 像字段名（不包含数字或以冒号结尾）
    is_field_name = (
        text1.endswith(':') or
        text1.endswith('：') or
        (not any(c.isdigit() for c in text1) and len(text1) < 30)
    )

    # q2 是数值
    is_numeric = bool(re.match(r'^[\d,.$%\s\-()]+$', text2.replace(',', '')))

    # 或者 q2 是短值
    is_short_value = len(text2) < 50

    return is_field_name and (is_numeric or is_short_value)


def consolidate_by_position(quotes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    基于位置信息的硬编码整合

    Args:
        quotes: 原始引用列表，每个引用需包含:
            - quote: 引用文本
            - standard_key: L-1 标准 key
            - page: 页码
            - source: {document_id, exhibit_id, file_name}
            - bbox: {x1, y1, x2, y2} (可选)

    Returns:
        整合后的引用列表
    """
    if not quotes:
        return []

    # 转换为 QuoteWithPosition 对象
    positioned_quotes = []
    for q in quotes:
        source = q.get("source", {})
        bbox = q.get("bbox")

        positioned_quotes.append(QuoteWithPosition(
            quote=q.get("quote", ""),
            standard_key=q.get("standard_key", "other"),
            page=q.get("page", 1),
            document_id=source.get("document_id", ""),
            exhibit_id=source.get("exhibit_id", ""),
            file_name=source.get("file_name", ""),
            bbox=bbox,
            relevance=q.get("relevance", "")
        ))

    # 按文档、页码、y坐标排序
    positioned_quotes.sort(key=lambda q: (
        q.document_id,
        q.page,
        q.bbox["y1"] if q.bbox else 0
    ))

    # 贪心整合
    consolidated = []
    i = 0

    while i < len(positioned_quotes):
        current = positioned_quotes[i]
        merged_text = current.quote
        merged_pages = {current.page}
        merged_relevance = [current.relevance] if current.relevance else []

        # 尝试向后合并
        j = i + 1
        while j < len(positioned_quotes):
            next_q = positioned_quotes[j]

            # 必须是同一标准
            if next_q.standard_key != current.standard_key:
                break

            # 检查是否应该合并
            should_merge = (
                is_same_visual_block(current, next_q) or
                is_sentence_continuation(current, next_q) or
                is_table_header_value_pair(current, next_q)
            )

            if should_merge:
                # 检查合并后长度
                if len(merged_text) + len(next_q.quote) + 1 > MAX_CONSOLIDATED_LENGTH:
                    break

                # 合并
                # 如果是表格 header-value，用冒号连接
                if is_table_header_value_pair(current, next_q):
                    if not merged_text.endswith(':') and not merged_text.endswith('：'):
                        merged_text += ': '
                    merged_text += next_q.quote
                else:
                    # 普通文本用空格连接
                    merged_text += ' ' + next_q.quote

                merged_pages.add(next_q.page)
                if next_q.relevance:
                    merged_relevance.append(next_q.relevance)

                # 更新 current 用于下一次比较
                current = next_q
                j += 1
            else:
                break

        # 创建整合后的引用
        first_quote = positioned_quotes[i]
        consolidated.append({
            "quote": merged_text.strip(),
            "standard_key": first_quote.standard_key,
            "page": min(merged_pages),
            "page_range": f"{min(merged_pages)}-{max(merged_pages)}" if len(merged_pages) > 1 else str(min(merged_pages)),
            "relevance": "; ".join(merged_relevance) if merged_relevance else "",
            "source": {
                "document_id": first_quote.document_id,
                "exhibit_id": first_quote.exhibit_id,
                "file_name": first_quote.file_name
            },
            "consolidated_count": j - i  # 记录合并了多少条
        })

        i = j

    return consolidated


# =============================================
# 语义整合（LLM Agent）
# =============================================

def build_consolidation_prompt(candidate_group: List[Dict[str, Any]]) -> str:
    """
    构建语义整合的 prompt

    Args:
        candidate_group: 候选整合组（位置相近的引用）

    Returns:
        LLM prompt
    """
    quotes_text = ""
    for i, q in enumerate(candidate_group):
        quotes_text += f"\n[Quote {i+1}] (Page {q.get('page', '?')})\n"
        quotes_text += f"  Text: {q.get('quote', '')}\n"
        quotes_text += f"  Category: {q.get('standard_key', 'unknown')}\n"

    prompt = f"""You are analyzing L-1 visa document quotes that may need to be consolidated.

These quotes are from the same document and appear close together (same or adjacent pages):
{quotes_text}

Analyze whether these quotes should be merged into one or kept separate.

**Merge if:**
- They describe the same fact/entity (e.g., "Gross receipts" + "$741,227" = single financial fact)
- One is incomplete without the other (e.g., sentence fragments)
- They form a logical unit (e.g., table header + values)
- They belong to the same paragraph discussing the same topic

**Keep separate if:**
- They describe different facts (e.g., revenue vs. employee count)
- They belong to different L-1 standards
- Each is self-contained and meaningful alone
- They are from different sections of the document

**Output JSON:**
{{
  "decision": "merge" | "keep_separate",
  "reason": "Brief explanation",
  "merged_quote": "The combined text if merging (preserve exact wording, connect naturally)",
  "merged_relevance": "Combined relevance explanation if merging"
}}

If keeping separate, omit merged_quote and merged_relevance fields.
"""
    return prompt


def group_candidates_for_consolidation(
    quotes: List[Dict[str, Any]],
    max_group_size: int = 5
) -> List[List[Dict[str, Any]]]:
    """
    将引用分组为候选整合组

    基于:
    - 同一文档
    - 同一或相邻页
    - 相同或相近的 L-1 标准

    Args:
        quotes: 引用列表
        max_group_size: 每组最大引用数

    Returns:
        候选组列表
    """
    if not quotes:
        return []

    # 按文档和页码分组
    doc_page_groups: Dict[str, List[Dict]] = {}

    for q in quotes:
        source = q.get("source", {})
        doc_id = source.get("document_id", "unknown")
        page = q.get("page", 1)

        # 使用文档ID和页码范围（允许相邻页）
        key = f"{doc_id}_{page // 2}"  # 每2页一组

        if key not in doc_page_groups:
            doc_page_groups[key] = []
        doc_page_groups[key].append(q)

    # 进一步按标准分组
    candidate_groups = []

    for group_quotes in doc_page_groups.values():
        # 按标准分类
        by_standard: Dict[str, List[Dict]] = {}
        for q in group_quotes:
            std = q.get("standard_key", "other")
            if std not in by_standard:
                by_standard[std] = []
            by_standard[std].append(q)

        # 每个标准内的引用形成候选组
        for std_quotes in by_standard.values():
            # 按页码排序
            std_quotes.sort(key=lambda x: (x.get("page", 0), x.get("bbox", {}).get("y1", 0) if x.get("bbox") else 0))

            # 分成小组
            for i in range(0, len(std_quotes), max_group_size):
                group = std_quotes[i:i + max_group_size]
                if len(group) >= 2:  # 至少2条才需要考虑整合
                    candidate_groups.append(group)

    return candidate_groups


async def consolidate_by_semantics(
    quotes: List[Dict[str, Any]],
    llm_client: Any,
    model: str = "qwen-turbo"
) -> List[Dict[str, Any]]:
    """
    基于语义的 LLM Agent 整合

    Args:
        quotes: 经过位置预整合的引用列表
        llm_client: LLM 客户端
        model: 使用的模型

    Returns:
        整合后的引用列表
    """
    # 分组
    candidate_groups = group_candidates_for_consolidation(quotes)

    if not candidate_groups:
        return quotes

    # 记录已处理的引用索引
    processed_indices = set()
    consolidated_quotes = []

    # 创建引用到索引的映射
    quote_to_index = {q.get("quote", ""): i for i, q in enumerate(quotes)}

    for group in candidate_groups:
        if len(group) < 2:
            continue

        # 检查是否已处理
        group_indices = [quote_to_index.get(q.get("quote", "")) for q in group]
        if any(idx in processed_indices for idx in group_indices if idx is not None):
            continue

        # 构建 prompt
        prompt = build_consolidation_prompt(group)

        try:
            # 调用 LLM
            response = await llm_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content
            result = json.loads(result_text)

            if result.get("decision") == "merge" and result.get("merged_quote"):
                # 标记已处理
                for idx in group_indices:
                    if idx is not None:
                        processed_indices.add(idx)

                # 创建合并后的引用
                first_quote = group[0]
                consolidated_quotes.append({
                    "quote": result["merged_quote"],
                    "standard_key": first_quote.get("standard_key", "other"),
                    "page": min(q.get("page", 1) for q in group),
                    "relevance": result.get("merged_relevance", ""),
                    "source": first_quote.get("source", {}),
                    "consolidated_count": len(group),
                    "consolidation_reason": result.get("reason", "")
                })

        except Exception as e:
            print(f"[QuoteConsolidator] LLM consolidation failed: {e}")
            # 失败时保留原始引用
            continue

    # 添加未处理的引用
    for i, q in enumerate(quotes):
        if i not in processed_indices:
            consolidated_quotes.append(q)

    return consolidated_quotes


# =============================================
# 完整整合流程
# =============================================

async def consolidate_quotes(
    quotes: List[Dict[str, Any]],
    llm_client: Any = None,
    use_semantic: bool = True,
    model: str = "qwen-turbo"
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    完整的引用整合流程

    Args:
        quotes: 原始引用列表
        llm_client: LLM 客户端（可选，用于语义整合）
        use_semantic: 是否使用语义整合
        model: LLM 模型名

    Returns:
        (整合后的引用列表, 统计信息)
    """
    original_count = len(quotes)

    # Step 1: 位置预整合
    position_consolidated = consolidate_by_position(quotes)
    after_position = len(position_consolidated)

    # Step 2: 语义整合（可选）
    if use_semantic and llm_client and after_position > 1:
        final_quotes = await consolidate_by_semantics(
            position_consolidated,
            llm_client,
            model
        )
    else:
        final_quotes = position_consolidated

    final_count = len(final_quotes)

    stats = {
        "original_count": original_count,
        "after_position_consolidation": after_position,
        "final_count": final_count,
        "reduction_rate": round((1 - final_count / original_count) * 100, 1) if original_count > 0 else 0
    }

    return final_quotes, stats


# =============================================
# 文档上下文工具函数
# =============================================

def get_document_page_context(
    document_id: str,
    db_session: Any
) -> Dict[str, Any]:
    """
    获取文档的页面上下文信息

    用于判断哪些页面属于同一个原始文件

    Args:
        document_id: 文档 ID
        db_session: 数据库会话

    Returns:
        文档上下文信息
    """
    from app.models.document import Document, TextBlock

    doc = db_session.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return {}

    # 获取同一 exhibit 的所有文档
    same_exhibit_docs = db_session.query(Document).filter(
        Document.project_id == doc.project_id,
        Document.exhibit_number == doc.exhibit_number
    ).order_by(Document.created_at).all() if doc.exhibit_number else [doc]

    # 构建页面映射
    page_map = {}
    global_page = 1

    for d in same_exhibit_docs:
        for local_page in range(1, (d.page_count or 1) + 1):
            page_map[f"{d.id}:{local_page}"] = {
                "global_page": global_page,
                "document_id": d.id,
                "local_page": local_page,
                "exhibit_id": d.exhibit_number,
                "file_name": d.file_name
            }
            global_page += 1

    return {
        "document_id": document_id,
        "exhibit_id": doc.exhibit_number,
        "total_pages": global_page - 1,
        "page_map": page_map,
        "related_documents": [d.id for d in same_exhibit_docs]
    }


def are_quotes_from_adjacent_pages(
    q1: Dict[str, Any],
    q2: Dict[str, Any],
    page_context: Dict[str, Any]
) -> bool:
    """
    判断两个引用是否来自相邻页面（考虑跨文档情况）

    Args:
        q1, q2: 引用
        page_context: 页面上下文

    Returns:
        是否相邻
    """
    page_map = page_context.get("page_map", {})

    source1 = q1.get("source", {})
    source2 = q2.get("source", {})

    key1 = f"{source1.get('document_id', '')}:{q1.get('page', 1)}"
    key2 = f"{source2.get('document_id', '')}:{q2.get('page', 1)}"

    info1 = page_map.get(key1)
    info2 = page_map.get(key2)

    if not info1 or not info2:
        return False

    # 全局页码相邻
    return abs(info1["global_page"] - info2["global_page"]) <= 1


# =============================================
# BBox 匹配与富化
# =============================================

def enrich_quotes_with_bbox(
    quotes: List[Dict[str, Any]],
    document_id: str,
    db_session: Any
) -> List[Dict[str, Any]]:
    """
    为引用添加 bounding box 信息

    Args:
        quotes: 引用列表
        document_id: 文档 ID
        db_session: 数据库会话

    Returns:
        带 bbox 的引用列表
    """
    from app.models.document import TextBlock
    from app.services.bbox_matcher import match_text_to_blocks

    # 获取该文档的所有 text_blocks
    text_blocks = db_session.query(TextBlock).filter(
        TextBlock.document_id == document_id
    ).order_by(TextBlock.page_number, TextBlock.block_id).all()

    if not text_blocks:
        return quotes

    enriched = []
    for q in quotes:
        quote_text = q.get("quote", "")
        page_hint = q.get("page")

        # 使用 bbox_matcher 进行匹配
        match_result = match_text_to_blocks(
            quote_text,
            text_blocks,
            page_hint=page_hint,
            similarity_threshold=0.6
        )

        if match_result.get("matched") and match_result.get("matches"):
            best_match = match_result["matches"][0]
            q_enriched = {
                **q,
                "bbox": best_match.get("bbox"),
                "page": best_match.get("page_number", page_hint),
                "match_score": best_match.get("match_score", 0)
            }
        else:
            q_enriched = {**q, "bbox": None}

        enriched.append(q_enriched)

    return enriched


def enrich_all_quotes_with_bbox(
    all_results: List[Dict[str, Any]],
    db_session: Any
) -> List[Dict[str, Any]]:
    """
    为所有文档的引用添加 bbox 信息

    Args:
        all_results: 所有文档的分析结果列表
            [{"document_id": ..., "quotes": [...]}]
        db_session: 数据库会话

    Returns:
        带 bbox 的分析结果列表
    """
    enriched_results = []

    for doc_result in all_results:
        document_id = doc_result.get("document_id")
        quotes = doc_result.get("quotes", [])

        if document_id and quotes:
            enriched_quotes = enrich_quotes_with_bbox(quotes, document_id, db_session)
            enriched_results.append({
                **doc_result,
                "quotes": enriched_quotes
            })
        else:
            enriched_results.append(doc_result)

    return enriched_results


# =============================================
# 同步版本的整合函数（用于不需要 LLM 的场景）
# =============================================

def consolidate_quotes_sync(
    quotes: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    同步版本的引用整合（只使用位置规则，不调用 LLM）

    Args:
        quotes: 原始引用列表

    Returns:
        (整合后的引用列表, 统计信息)
    """
    original_count = len(quotes)

    # 位置预整合
    consolidated = consolidate_by_position(quotes)
    final_count = len(consolidated)

    stats = {
        "original_count": original_count,
        "final_count": final_count,
        "reduction_rate": round((1 - final_count / original_count) * 100, 1) if original_count > 0 else 0,
        "method": "position_only"
    }

    return consolidated, stats


def consolidate_document_quotes(
    doc_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    整合单个文档的引用

    Args:
        doc_result: 单个文档的分析结果
            {"document_id": ..., "quotes": [...], ...}

    Returns:
        整合后的文档结果
    """
    quotes = doc_result.get("quotes", [])

    if len(quotes) <= 1:
        return doc_result

    consolidated, stats = consolidate_quotes_sync(quotes)

    return {
        **doc_result,
        "quotes": consolidated,
        "consolidation_stats": stats
    }


def consolidate_all_document_quotes(
    all_results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    整合所有文档的引用

    Args:
        all_results: 所有文档的分析结果

    Returns:
        (整合后的结果, 总体统计)
    """
    consolidated_results = []
    total_original = 0
    total_final = 0

    for doc_result in all_results:
        quotes = doc_result.get("quotes", [])
        total_original += len(quotes)

        consolidated_doc = consolidate_document_quotes(doc_result)
        consolidated_results.append(consolidated_doc)

        total_final += len(consolidated_doc.get("quotes", []))

    overall_stats = {
        "total_original": total_original,
        "total_final": total_final,
        "total_reduction": total_original - total_final,
        "reduction_rate": round((1 - total_final / total_original) * 100, 1) if total_original > 0 else 0
    }

    return consolidated_results, overall_stats
