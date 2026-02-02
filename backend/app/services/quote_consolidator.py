"""
Quote Consolidator Service - 引用整合服务 v2.2

架构 (LLM 主导):
1. 硬编码粗筛 - 产出候选整合组，不做最终决策
2. LLM 决策 - 所有引用都经过 LLM 检查质量
3. Token 预估与分批 - 超过上下文限制时分成多批
4. 存档机制 - 整合前后都保存数据，方便回溯

设计原则:
- 准确率和可靠程度是评价标准，不是减少数量
- 本地 Ollama 模型 (qwen3:30b-a3b)，无额外成本
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import json
import re
import asyncio


# =============================================
# 配置常量 (v2.2 放宽阈值 - 宁可多报不漏报)
# =============================================

# 位置粗筛阈值 (放宽版本)
Y_ADJACENT_THRESHOLD = 200      # y 坐标差值 (放宽到 200，原 50)
X_OVERLAP_THRESHOLD = 20        # x 坐标重叠最小值 (降低到 20，原 100)
SAME_COLUMN_X_DIFF = 400        # 同一列的 x 坐标最大差值 (放宽到 400，原 200)

# 句子延续特征
CONTINUATION_END_CHARS = [',', '，', ';', '；', ':', '：', '-', '–', '—']
CONTINUATION_START_LOWER = True

# 整合后的最大长度
MAX_CONSOLIDATED_LENGTH = 2000

# LLM 配置
LLM_MODEL = "qwen3:30b-a3b"
LLM_TEMPERATURE = 0.3
LLM_MAX_TOKENS = 16000

# 分批配置 (顺序处理，不并发)
BATCH_INTERVAL = 0.5  # 批次间隔秒数


@dataclass
class QuoteWithPosition:
    """带位置信息的引用"""
    quote: str
    standard_key: str
    page: int
    document_id: str
    exhibit_id: str
    file_name: str
    bbox: Optional[Dict[str, int]] = None
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
# Step 1.5: 包含关系预处理 (v2.3 新增)
# =============================================

def normalize_text_for_comparison(text: str) -> str:
    """标准化文本用于比较"""
    if not text:
        return ""
    # 去除多余空白、标点，转小写
    normalized = re.sub(r'\s+', ' ', text.strip().lower())
    # 去除常见标点
    normalized = re.sub(r'[,.:;!?，。：；！？\-–—\'\"()\[\]{}]', '', normalized)
    return normalized


def text_contains(longer: str, shorter: str, threshold: float = 0.9) -> bool:
    """
    检查 longer 是否包含 shorter 的内容

    Args:
        longer: 较长的文本
        shorter: 较短的文本
        threshold: 包含比例阈值（shorter 中有多少比例的词在 longer 中）

    Returns:
        True 如果 longer 包含 shorter 的大部分内容
    """
    if not shorter or not longer:
        return False

    norm_longer = normalize_text_for_comparison(longer)
    norm_shorter = normalize_text_for_comparison(shorter)

    # 如果 shorter 完全是 longer 的子串
    if norm_shorter in norm_longer:
        return True

    # 基于词的包含检测
    shorter_words = set(norm_shorter.split())
    longer_words = set(norm_longer.split())

    if not shorter_words:
        return False

    # 计算 shorter 中有多少词在 longer 中出现
    overlap = shorter_words & longer_words
    overlap_ratio = len(overlap) / len(shorter_words)

    return overlap_ratio >= threshold


def text_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度

    Returns:
        0.0 - 1.0 之间的相似度
    """
    if not text1 or not text2:
        return 0.0

    norm1 = normalize_text_for_comparison(text1)
    norm2 = normalize_text_for_comparison(text2)

    if norm1 == norm2:
        return 1.0

    words1 = set(norm1.split())
    words2 = set(norm2.split())

    if not words1 or not words2:
        return 0.0

    # Jaccard 相似度
    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def preprocess_containment_and_duplicates(
    quotes: List[Dict[str, Any]],
    similarity_threshold: float = 0.85,
    containment_threshold: float = 0.9
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    预处理：检测包含关系和重复，保留信息最完整的引用

    规则（同一 standard_key 内）：
    1. 如果 A 包含 B 的文本，删除 B，保留 A
    2. 如果 A 和 B 高度相似（>85%），保留较长的
    3. 跨材料也检测

    Args:
        quotes: 原始引用列表
        similarity_threshold: 相似度阈值，超过此值认为是重复
        containment_threshold: 包含阈值

    Returns:
        (去重后的引用列表, 统计信息)
    """
    if not quotes or len(quotes) <= 1:
        return quotes, {"removed": 0, "original": len(quotes) if quotes else 0}

    # 按 standard_key 分组
    by_standard: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for i, q in enumerate(quotes):
        std = q.get("standard_key", "other")
        if std not in by_standard:
            by_standard[std] = []
        by_standard[std].append((i, q))

    # 标记要删除的索引
    to_remove: set = set()
    merge_info: List[Dict] = []  # 记录合并信息

    for std, indexed_quotes in by_standard.items():
        n = len(indexed_quotes)
        if n <= 1:
            continue

        # 按文本长度降序排列（优先处理较长的）
        indexed_quotes.sort(key=lambda x: len(x[1].get("quote", "")), reverse=True)

        for i in range(n):
            idx_i, q_i = indexed_quotes[i]
            if idx_i in to_remove:
                continue

            text_i = q_i.get("quote", "")

            for j in range(i + 1, n):
                idx_j, q_j = indexed_quotes[j]
                if idx_j in to_remove:
                    continue

                text_j = q_j.get("quote", "")

                # 检查包含关系：较长的 text_i 是否包含较短的 text_j
                if text_contains(text_i, text_j, containment_threshold):
                    to_remove.add(idx_j)
                    merge_info.append({
                        "kept": idx_i,
                        "removed": idx_j,
                        "reason": "containment",
                        "kept_text": text_i[:50],
                        "removed_text": text_j[:50]
                    })
                    continue

                # 检查高度相似
                sim = text_similarity(text_i, text_j)
                if sim >= similarity_threshold:
                    # 保留较长的（text_i 已经更长）
                    to_remove.add(idx_j)
                    merge_info.append({
                        "kept": idx_i,
                        "removed": idx_j,
                        "reason": f"similarity_{sim:.2f}",
                        "kept_text": text_i[:50],
                        "removed_text": text_j[:50]
                    })

    # 生成去重后的列表
    deduplicated = []
    for i, q in enumerate(quotes):
        if i not in to_remove:
            # 如果这个引用保留了其他引用的信息，记录
            absorbed = [m for m in merge_info if m["kept"] == i]
            if absorbed:
                q = {
                    **q,
                    "absorbed_count": len(absorbed),
                    "absorption_reason": "containment_or_similarity"
                }
            deduplicated.append(q)

    stats = {
        "original": len(quotes),
        "removed": len(to_remove),
        "final": len(deduplicated),
        "merge_details": merge_info[:10] if merge_info else []  # 只保留前10条详情
    }

    if to_remove:
        print(f"[QuoteConsolidator] Containment pre-processing: {len(quotes)} -> {len(deduplicated)} quotes")
        print(f"[QuoteConsolidator] Removed {len(to_remove)} redundant quotes")

    return deduplicated, stats


# =============================================
# Step 2: 硬编码粗筛 (v2.2 新设计)
# =============================================

def generate_candidate_groups(
    quotes: List[Dict[str, Any]],
    max_group_size: int = 5
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    生成候选整合组（粗筛阶段）- v2.2 新设计

    设计原则:
    - 只做分组，不做合并决策
    - 宁可多报不漏报（放宽阈值）
    - 所有引用都会被保留

    Args:
        quotes: 原始引用列表
        max_group_size: 每组最大引用数

    Returns:
        (candidate_groups, single_quotes)
        - candidate_groups: 候选组列表，每组 2-5 条引用
        - single_quotes: 独立引用列表（不符合任何分组条件）
    """
    if not quotes:
        return [], []

    # 转换为 QuoteWithPosition 对象
    positioned_quotes = []
    for i, q in enumerate(quotes):
        source = q.get("source", {})
        bbox = q.get("bbox")

        positioned_quotes.append({
            "original_index": i,
            "quote_obj": QuoteWithPosition(
                quote=q.get("quote", ""),
                standard_key=q.get("standard_key", "other"),
                page=q.get("page", 1),
                document_id=source.get("document_id", ""),
                exhibit_id=source.get("exhibit_id", ""),
                file_name=source.get("file_name", ""),
                bbox=bbox,
                relevance=q.get("relevance", "")
            ),
            "original_quote": q
        })

    # 按文档、页码、y坐标排序
    positioned_quotes.sort(key=lambda q: (
        q["quote_obj"].document_id,
        q["quote_obj"].page,
        q["quote_obj"].bbox["y1"] if q["quote_obj"].bbox else 0
    ))

    # 使用 Union-Find 进行分组
    n = len(positioned_quotes)
    parent = list(range(n))

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # 检查相邻引用是否可能需要整合
    for i in range(n):
        for j in range(i + 1, min(i + 5, n)):  # 只检查相邻的几条
            qi = positioned_quotes[i]["quote_obj"]
            qj = positioned_quotes[j]["quote_obj"]

            # 不同文档不分组
            if qi.document_id != qj.document_id:
                continue

            # 不同标准不分组
            if qi.standard_key != qj.standard_key:
                continue

            # 检查是否可能需要整合
            reason, confidence = _check_grouping_reason(qi, qj)
            if reason:
                union(i, j)

    # 按组分类
    groups_map: Dict[int, List[int]] = {}
    for i in range(n):
        root = find(i)
        if root not in groups_map:
            groups_map[root] = []
        groups_map[root].append(i)

    # 分离候选组和独立引用
    candidate_groups = []
    single_quotes = []
    group_counter = 0

    for indices in groups_map.values():
        if len(indices) >= 2:
            # 候选组：分割成小组
            for chunk_start in range(0, len(indices), max_group_size):
                chunk_indices = indices[chunk_start:chunk_start + max_group_size]
                if len(chunk_indices) >= 2:
                    group_counter += 1
                    quotes_in_group = [positioned_quotes[i]["original_quote"] for i in chunk_indices]

                    # 确定分组原因和置信度
                    reason, confidence = _determine_group_reason(
                        [positioned_quotes[i]["quote_obj"] for i in chunk_indices]
                    )

                    candidate_groups.append({
                        "group_id": f"g{group_counter}",
                        "quotes": quotes_in_group,
                        "reason": reason,
                        "confidence": confidence,
                        "type": "group"
                    })
                else:
                    # 单条变成独立引用
                    for i in chunk_indices:
                        single_quotes.append({
                            "item_id": f"s{len(single_quotes) + 1}",
                            "quote": positioned_quotes[i]["original_quote"],
                            "type": "single"
                        })
        else:
            # 独立引用
            for i in indices:
                single_quotes.append({
                    "item_id": f"s{len(single_quotes) + 1}",
                    "quote": positioned_quotes[i]["original_quote"],
                    "type": "single"
                })

    return candidate_groups, single_quotes


def _check_grouping_reason(
    q1: QuoteWithPosition,
    q2: QuoteWithPosition
) -> Tuple[Optional[str], str]:
    """
    检查两个引用是否应该分到同一组

    Returns:
        (reason, confidence) 或 (None, "")
    """
    # 检查页码差距
    page_diff = abs(q1.page - q2.page)
    if page_diff > 1:
        return None, ""

    # 0. 同一 BBox (来自同一 OCR 文本块) - 最高优先级
    if q1.bbox and q2.bbox and q1.page == q2.page:
        # Check if bboxes are identical or nearly identical (same OCR text block)
        bbox_match_threshold = 10  # Allow small pixel differences
        if (abs(q1.bbox["x1"] - q2.bbox["x1"]) <= bbox_match_threshold and
            abs(q1.bbox["y1"] - q2.bbox["y1"]) <= bbox_match_threshold and
            abs(q1.bbox["x2"] - q2.bbox["x2"]) <= bbox_match_threshold and
            abs(q1.bbox["y2"] - q2.bbox["y2"]) <= bbox_match_threshold):
            return "same_text_block", "very_high"

    # 1. 同一视觉块 (基于位置)
    if q1.bbox and q2.bbox:
        if q1.page == q2.page:
            y_diff = abs(q2.bbox["y1"] - q1.bbox["y2"])
            if y_diff >= 0 and y_diff <= Y_ADJACENT_THRESHOLD:
                x_overlap = min(q1.bbox["x2"], q2.bbox["x2"]) - max(q1.bbox["x1"], q2.bbox["x1"])
                if x_overlap >= X_OVERLAP_THRESHOLD:
                    return "same_visual_block", "high"

        # 跨页情况
        if q1.page == q2.page - 1:
            if q1.bbox["y2"] > 700 and q2.bbox["y1"] < 300:
                x_diff = abs(q1.bbox["x1"] - q2.bbox["x1"])
                if x_diff < SAME_COLUMN_X_DIFF:
                    return "adjacent_page", "medium"

    # 2. 句子延续
    text1 = q1.quote.strip()
    text2 = q2.quote.strip()

    if text1 and text2:
        # q1 不以句号结尾
        if text1[-1] not in '.。!！?？':
            # q1 以延续标点结尾
            if text1[-1] in CONTINUATION_END_CHARS:
                return "sentence_continuation", "high"
            # q2 以小写开头
            if text2[0].islower():
                return "sentence_continuation", "medium"
            # q1 以介词/连词结尾
            continuation_words = ['and', 'or', 'the', 'a', 'an', 'of', 'in', 'to', 'for', 'with', 'by']
            if any(text1.lower().endswith(' ' + w) for w in continuation_words):
                return "sentence_continuation", "medium"

    # 3. 表格 header-value 对
    if _is_table_pair(q1, q2):
        return "table_pair", "high"

    return None, ""


def _is_table_pair(q1: QuoteWithPosition, q2: QuoteWithPosition) -> bool:
    """检查是否是表格 header-value 对"""
    text1 = q1.quote.strip()
    text2 = q2.quote.strip()

    if len(text1) > 50:
        return False

    is_field_name = (
        text1.endswith(':') or
        text1.endswith('：') or
        (not any(c.isdigit() for c in text1) and len(text1) < 30)
    )

    is_numeric = bool(re.match(r'^[\d,.$%\s\-()]+$', text2.replace(',', '')))
    is_short_value = len(text2) < 50

    return is_field_name and (is_numeric or is_short_value)


def _determine_group_reason(quotes: List[QuoteWithPosition]) -> Tuple[str, str]:
    """确定整个组的分组原因和置信度"""
    reasons = []
    for i in range(len(quotes) - 1):
        reason, conf = _check_grouping_reason(quotes[i], quotes[i + 1])
        if reason:
            reasons.append((reason, conf))

    if not reasons:
        return "proximity", "low"

    # 返回最常见的原因
    reason_counts: Dict[str, int] = {}
    for r, _ in reasons:
        reason_counts[r] = reason_counts.get(r, 0) + 1

    top_reason = max(reason_counts.keys(), key=lambda x: reason_counts[x])

    # 置信度取最高的
    confidences = [c for r, c in reasons if r == top_reason]
    if "very_high" in confidences:
        return top_reason, "very_high"
    elif "high" in confidences:
        return top_reason, "high"
    elif "medium" in confidences:
        return top_reason, "medium"
    else:
        return top_reason, "low"


# =============================================
# Step 4: LLM 决策 (v2.2 新设计)
# =============================================

# LLM Prompt 模板
CONSOLIDATION_PROMPT = """你是 L-1 签证文档分析专家。请审查以下所有引用项目，为每一个项目做出决策。

## 引用列表

{items_text}

## 任务

**重要**: 你必须为上面列出的每一个项目 (每个 [gX] 和 [sX]) 都返回一个决策。不要遗漏任何项目。

### 对于候选整合组 [gX]（多条引用）:

- **merge**: 描述同一个事实/实体，应合并为一条
- **keep**: 描述不同事实，各自独立完整，保持分离
- **adjust**: 有明显截断或需要补充上下文

### 对于独立引用 [sX]（单条）:

- **approve**: 引用完整、清晰、有价值
- **adjust**: 需要修正截断、补充上下文
- **reject**: 无意义、重复、或质量太差

## 输出格式

返回一个 JSON 数组，包含对每个项目的决策。数组长度必须等于输入项目数量。

```json
[
  {{"item_id": "g1", "type": "group", "decision": "merge", "reason": "简短说明", "result": {{"merged_quote": "合并后文本", "merged_relevance": "合并后相关性"}}}},
  {{"item_id": "g2", "type": "group", "decision": "keep", "reason": "描述不同事实", "result": {{}}}},
  {{"item_id": "s1", "type": "single", "decision": "approve", "reason": "引用完整清晰", "result": {{}}}}
]
```

result 字段规则:
- merge: 必须包含 merged_quote 和 merged_relevance
- adjust: 必须包含 adjusted_quote 和 adjusted_relevance
- keep/approve/reject: 为空对象 {{}}
"""


def format_items_for_prompt(items: List[Dict[str, Any]]) -> str:
    """格式化项目列表为 prompt 文本"""
    text_parts = []

    for item in items:
        item_type = item.get("type", "group")
        item_id = item.get("group_id") or item.get("item_id")

        if item_type == "group":
            quotes = item.get("quotes", [])
            text_parts.append(f"\n### [{item_id}] 候选整合组 (置信度: {item.get('confidence', 'unknown')})")
            text_parts.append(f"分组原因: {item.get('reason', 'unknown')}")

            for i, q in enumerate(quotes):
                text_parts.append(f"\n  Quote {i+1} (Page {q.get('page', '?')}):")
                text_parts.append(f"    文本: {q.get('quote', '')[:500]}")
                text_parts.append(f"    类别: {q.get('standard_key', 'unknown')}")
                if q.get("relevance"):
                    text_parts.append(f"    相关性: {q.get('relevance', '')[:200]}")

        else:  # single
            quote = item.get("quote", {})
            text_parts.append(f"\n### [{item_id}] 独立引用")
            text_parts.append(f"  Page: {quote.get('page', '?')}")
            text_parts.append(f"  文本: {quote.get('quote', '')[:500]}")
            text_parts.append(f"  类别: {quote.get('standard_key', 'unknown')}")
            if quote.get("relevance"):
                text_parts.append(f"  相关性: {quote.get('relevance', '')[:200]}")

    return "\n".join(text_parts)


async def process_consolidation_batch(
    batch: List[Dict[str, Any]],
    call_llm_func,
    model: str = LLM_MODEL
) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """
    处理一批候选组/独立引用

    Args:
        batch: 项目列表 (候选组 + 独立引用)
        call_llm_func: LLM 调用函数 (async def call_llm(prompt, model) -> dict)
        model: 使用的模型

    Returns:
        (decisions, prompt, error)
        - decisions: LLM 返回的决策列表
        - prompt: 发送给 LLM 的 prompt
        - error: 错误信息（如果有）
    """
    # 构建 prompt
    items_text = format_items_for_prompt(batch)
    prompt = CONSOLIDATION_PROMPT.format(items_text=items_text)

    try:
        # 调用 LLM
        response = await call_llm_func(prompt, model_override=model)

        # 解析响应
        if isinstance(response, dict):
            # 可能是已解析的 JSON
            if isinstance(response, list):
                decisions = response
            elif "decisions" in response:
                decisions = response["decisions"]
            else:
                # 尝试从响应中提取列表
                decisions = [response]
        elif isinstance(response, str):
            # 尝试解析 JSON
            decisions = json.loads(response)
        else:
            decisions = list(response) if hasattr(response, '__iter__') else [response]

        # 确保是列表
        if not isinstance(decisions, list):
            decisions = [decisions]

        return decisions, prompt, None

    except json.JSONDecodeError as e:
        return [], prompt, f"JSON parse error: {str(e)}"
    except Exception as e:
        return [], prompt, f"LLM call error: {str(e)}"


def apply_decisions(
    candidate_groups: List[Dict[str, Any]],
    single_quotes: List[Dict[str, Any]],
    decisions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    应用 LLM 决策，生成最终引用列表

    Args:
        candidate_groups: 候选组列表
        single_quotes: 独立引用列表
        decisions: LLM 决策列表

    Returns:
        最终引用列表
    """
    final_quotes = []

    # 建立 item_id -> decision 的映射
    decision_map = {}
    for d in decisions:
        item_id = d.get("item_id")
        if item_id:
            decision_map[item_id] = d

    # 处理候选组
    for group in candidate_groups:
        group_id = group.get("group_id")
        decision = decision_map.get(group_id, {})
        decision_type = decision.get("decision", "keep")

        if decision_type == "merge":
            # 合并
            result = decision.get("result", {})
            first_quote = group["quotes"][0]
            final_quotes.append({
                "quote": result.get("merged_quote", first_quote.get("quote", "")),
                "standard_key": first_quote.get("standard_key", "other"),
                "page": min(q.get("page", 1) for q in group["quotes"]),
                "relevance": result.get("merged_relevance", ""),
                "source": first_quote.get("source", {}),
                "consolidated_count": len(group["quotes"]),
                "consolidation_reason": decision.get("reason", ""),
                "llm_decision": "merge"
            })
        elif decision_type == "adjust":
            # 调整（通常是调整单个合并结果）
            result = decision.get("result", {})
            first_quote = group["quotes"][0]
            final_quotes.append({
                "quote": result.get("adjusted_quote", first_quote.get("quote", "")),
                "standard_key": first_quote.get("standard_key", "other"),
                "page": min(q.get("page", 1) for q in group["quotes"]),
                "relevance": result.get("adjusted_relevance", ""),
                "source": first_quote.get("source", {}),
                "consolidated_count": len(group["quotes"]),
                "consolidation_reason": decision.get("reason", ""),
                "llm_decision": "adjust"
            })
        else:
            # keep - 保留原始引用
            for q in group["quotes"]:
                final_quotes.append({
                    **q,
                    "llm_decision": "keep"
                })

    # 处理独立引用
    for single in single_quotes:
        item_id = single.get("item_id")
        quote = single.get("quote", {})
        decision = decision_map.get(item_id, {})
        decision_type = decision.get("decision", "approve")

        if decision_type == "reject":
            # 拒绝 - 不添加
            continue
        elif decision_type == "adjust":
            # 调整
            result = decision.get("result", {})
            final_quotes.append({
                "quote": result.get("adjusted_quote", quote.get("quote", "")),
                "standard_key": quote.get("standard_key", "other"),
                "page": quote.get("page", 1),
                "relevance": result.get("adjusted_relevance", quote.get("relevance", "")),
                "source": quote.get("source", {}),
                "llm_decision": "adjust"
            })
        else:
            # approve - 保留原样
            final_quotes.append({
                **quote,
                "llm_decision": "approve"
            })

    return final_quotes


# =============================================
# 完整整合流程 (v2.2)
# =============================================

async def consolidate_quotes_v2(
    quotes: List[Dict[str, Any]],
    call_llm_func,
    project_id: str = None,
    model: str = LLM_MODEL
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    v2.3 完整的引用整合流程 (LLM 主导 + 包含关系预处理)

    Args:
        quotes: 原始引用列表
        call_llm_func: LLM 调用函数
        project_id: 项目 ID（用于存档）
        model: LLM 模型名

    Returns:
        (整合后的引用列表, 统计信息)
    """
    from app.services.token_estimator import split_into_batches, estimate_batch_stats
    from app.services.consolidation_archive import ConsolidationArchive

    original_count = len(quotes)

    # 初始化存档器
    archive = None
    if project_id:
        try:
            archive = ConsolidationArchive(project_id)
            archive.save_original_quotes(quotes)
        except Exception as e:
            print(f"[QuoteConsolidator] Warning: Could not initialize archive: {e}")

    # Step 1.5: 包含关系预处理 (v2.3 新增)
    # 在同一 standard_key 内，移除被其他引用包含的重复引用
    quotes, containment_stats = preprocess_containment_and_duplicates(quotes)
    after_containment_count = len(quotes)

    if archive and containment_stats.get("removed", 0) > 0:
        try:
            archive.save_containment_preprocessing(containment_stats)
        except Exception as e:
            print(f"[QuoteConsolidator] Warning: Could not save containment stats: {e}")

    # Step 2: 硬编码粗筛
    candidate_groups, single_quotes = generate_candidate_groups(quotes)

    if archive:
        try:
            archive.save_candidate_groups(candidate_groups, single_quotes)
        except Exception as e:
            print(f"[QuoteConsolidator] Warning: Could not save candidate groups: {e}")

    # 合并候选组和独立引用为统一列表
    all_items = candidate_groups + single_quotes

    if not all_items:
        return quotes, {
            "original_count": original_count,
            "final_count": original_count,
            "method": "no_processing",
            "llm_coverage": 0
        }

    # Step 3: 分批
    batches = split_into_batches(all_items)
    batch_stats = estimate_batch_stats(batches)

    if archive:
        try:
            archive.save_batch_info(batches, batch_stats)
        except Exception as e:
            print(f"[QuoteConsolidator] Warning: Could not save batch info: {e}")

    print(f"[QuoteConsolidator] Split into {len(batches)} batches")
    print(f"[QuoteConsolidator] Total items: {len(all_items)} ({len(candidate_groups)} groups + {len(single_quotes)} singles)")

    # Step 4: LLM 决策 (逐批处理)
    all_decisions = []
    llm_errors = []

    for batch_idx, batch in enumerate(batches):
        print(f"[QuoteConsolidator] Processing batch {batch_idx + 1}/{len(batches)}...")

        decisions, prompt, error = await process_consolidation_batch(
            batch, call_llm_func, model
        )

        if archive:
            try:
                archive.save_llm_batch_response(
                    batch_idx + 1, batch, prompt, None, decisions, error
                )
            except Exception as e:
                print(f"[QuoteConsolidator] Warning: Could not save batch response: {e}")

        if error:
            llm_errors.append({"batch": batch_idx + 1, "error": error})
            print(f"[QuoteConsolidator] Batch {batch_idx + 1} error: {error}")
        else:
            all_decisions.extend(decisions)

        # 批次间隔
        if batch_idx < len(batches) - 1:
            await asyncio.sleep(BATCH_INTERVAL)

    # Step 5: 应用决策
    final_quotes = apply_decisions(candidate_groups, single_quotes, all_decisions)
    final_count = len(final_quotes)

    # 统计
    stats = {
        "original_count": original_count,
        "after_containment": after_containment_count,
        "containment_removed": original_count - after_containment_count,
        "candidate_groups": len(candidate_groups),
        "single_quotes": len(single_quotes),
        "total_batches": len(batches),
        "decisions_received": len(all_decisions),
        "llm_errors": len(llm_errors),
        "final_count": final_count,
        "reduction_rate": round((1 - final_count / original_count) * 100, 1) if original_count > 0 else 0,
        "llm_coverage": round(len(all_decisions) / len(all_items) * 100, 1) if all_items else 0,
        "method": "llm_led_v2.3"
    }

    if archive:
        try:
            archive.save_final_quotes(final_quotes, stats)
            archive.save_stats(stats)
        except Exception as e:
            print(f"[QuoteConsolidator] Warning: Could not save final results: {e}")

    return final_quotes, stats


# =============================================
# 降级方案：仅粗筛（Ollama 不可用时）
# =============================================

def consolidate_quotes_fallback(
    quotes: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    降级整合方案：仅使用硬编码规则，不调用 LLM

    用于 Ollama 服务不可用时

    Args:
        quotes: 原始引用列表

    Returns:
        (整合后的引用列表, 统计信息)
    """
    original_count = len(quotes)

    # 生成候选组
    candidate_groups, single_quotes = generate_candidate_groups(quotes)

    # 不调用 LLM，直接保留所有引用
    final_quotes = []

    # 候选组中的引用全部保留（不合并，但标记未审核）
    for group in candidate_groups:
        for q in group["quotes"]:
            final_quotes.append({
                **q,
                "llm_decision": "not_reviewed",
                "candidate_group_id": group.get("group_id"),
                "group_reason": group.get("reason")
            })

    # 独立引用全部保留
    for single in single_quotes:
        final_quotes.append({
            **single.get("quote", {}),
            "llm_decision": "not_reviewed"
        })

    stats = {
        "original_count": original_count,
        "candidate_groups": len(candidate_groups),
        "single_quotes": len(single_quotes),
        "final_count": len(final_quotes),
        "method": "fallback_no_llm",
        "llm_coverage": 0,
        "warning": "LLM not available, quotes not reviewed"
    }

    return final_quotes, stats


# =============================================
# 保留原有函数以保持兼容性
# =============================================

def is_same_visual_block(q1: QuoteWithPosition, q2: QuoteWithPosition) -> bool:
    """判断两个引用是否属于同一视觉块（基于位置）- 保留以兼容"""
    reason, _ = _check_grouping_reason(q1, q2)
    return reason == "same_visual_block"


def is_sentence_continuation(q1: QuoteWithPosition, q2: QuoteWithPosition) -> bool:
    """判断 q2 是否是 q1 的句子延续 - 保留以兼容"""
    reason, _ = _check_grouping_reason(q1, q2)
    return reason == "sentence_continuation"


def is_table_header_value_pair(q1: QuoteWithPosition, q2: QuoteWithPosition) -> bool:
    """判断是否是表格的 header-value 对 - 保留以兼容"""
    return _is_table_pair(q1, q2)


def consolidate_by_position(quotes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """基于位置信息的硬编码整合 - 保留以兼容"""
    candidate_groups, single_quotes = generate_candidate_groups(quotes)

    # 简单处理：候选组保持原样，不合并
    result = []
    for group in candidate_groups:
        result.extend(group["quotes"])
    for single in single_quotes:
        result.append(single.get("quote", {}))

    return result


# =============================================
# 文档上下文工具函数
# =============================================

def get_document_page_context(
    document_id: str,
    db_session: Any
) -> Dict[str, Any]:
    """获取文档的页面上下文信息"""
    from app.models.document import Document, TextBlock

    doc = db_session.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return {}

    same_exhibit_docs = db_session.query(Document).filter(
        Document.project_id == doc.project_id,
        Document.exhibit_number == doc.exhibit_number
    ).order_by(Document.created_at).all() if doc.exhibit_number else [doc]

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
    """判断两个引用是否来自相邻页面"""
    page_map = page_context.get("page_map", {})

    source1 = q1.get("source", {})
    source2 = q2.get("source", {})

    key1 = f"{source1.get('document_id', '')}:{q1.get('page', 1)}"
    key2 = f"{source2.get('document_id', '')}:{q2.get('page', 1)}"

    info1 = page_map.get(key1)
    info2 = page_map.get(key2)

    if not info1 or not info2:
        return False

    return abs(info1["global_page"] - info2["global_page"]) <= 1


# =============================================
# BBox 匹配与富化
# =============================================

def enrich_quotes_with_bbox(
    quotes: List[Dict[str, Any]],
    document_id: str,
    db_session: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    为引用添加 bounding box 信息

    Returns:
        (enriched_quotes, bbox_stats)
    """
    from app.models.document import TextBlock
    from app.services.bbox_matcher import match_text_to_blocks

    text_blocks = db_session.query(TextBlock).filter(
        TextBlock.document_id == document_id
    ).order_by(TextBlock.page_number, TextBlock.block_id).all()

    if not text_blocks:
        return quotes, {"matched": 0, "total": len(quotes), "match_rate": 0}

    enriched = []
    matched_count = 0

    for q in quotes:
        quote_text = q.get("quote", "")
        page_hint = q.get("page")

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
            matched_count += 1
        else:
            q_enriched = {**q, "bbox": None}

        enriched.append(q_enriched)

    stats = {
        "matched": matched_count,
        "total": len(quotes),
        "match_rate": round(matched_count / len(quotes) * 100, 1) if quotes else 0
    }

    return enriched, stats


def enrich_all_quotes_with_bbox(
    all_results: List[Dict[str, Any]],
    db_session: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """为所有文档的引用添加 bbox 信息"""
    enriched_results = []
    total_matched = 0
    total_quotes = 0

    for doc_result in all_results:
        document_id = doc_result.get("document_id")
        quotes = doc_result.get("quotes", [])

        if document_id and quotes:
            enriched_quotes, stats = enrich_quotes_with_bbox(quotes, document_id, db_session)
            enriched_results.append({
                **doc_result,
                "quotes": enriched_quotes,
                "bbox_stats": stats
            })
            total_matched += stats["matched"]
            total_quotes += stats["total"]
        else:
            enriched_results.append(doc_result)

    overall_stats = {
        "total_matched": total_matched,
        "total_quotes": total_quotes,
        "overall_match_rate": round(total_matched / total_quotes * 100, 1) if total_quotes else 0
    }

    return enriched_results, overall_stats


# =============================================
# 同步版本（兼容旧 API）
# =============================================

def consolidate_quotes_sync(
    quotes: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """同步版本的引用整合（只使用粗筛规则，不调用 LLM）"""
    return consolidate_quotes_fallback(quotes)


def consolidate_document_quotes(
    doc_result: Dict[str, Any]
) -> Dict[str, Any]:
    """整合单个文档的引用"""
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
    """整合所有文档的引用（同步版本，不使用 LLM）"""
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


# =============================================
# 异步版本的完整流程（新 API）
# =============================================

async def consolidate_all_quotes_with_llm(
    all_results: List[Dict[str, Any]],
    call_llm_func,
    project_id: str = None,
    model: str = LLM_MODEL
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    使用 LLM 整合所有文档的引用

    这是 v2.2 的主入口函数

    Args:
        all_results: 所有文档的分析结果
        call_llm_func: LLM 调用函数
        project_id: 项目 ID（用于存档）
        model: LLM 模型名

    Returns:
        (整合后的结果, 总体统计)
    """
    # 收集所有引用（保留文档来源信息）
    all_quotes = []
    doc_id_map = {}  # quote index -> doc_result index

    for doc_idx, doc_result in enumerate(all_results):
        quotes = doc_result.get("quotes", [])
        for q in quotes:
            # 确保 source 信息完整
            if "source" not in q:
                q["source"] = {
                    "document_id": doc_result.get("document_id", ""),
                    "exhibit_id": doc_result.get("exhibit_id", ""),
                    "file_name": doc_result.get("file_name", "")
                }
            else:
                # 补充缺失的字段
                if not q["source"].get("document_id"):
                    q["source"]["document_id"] = doc_result.get("document_id", "")
                if not q["source"].get("exhibit_id"):
                    q["source"]["exhibit_id"] = doc_result.get("exhibit_id", "")

            doc_id_map[len(all_quotes)] = doc_idx
            all_quotes.append(q)

    if not all_quotes:
        return all_results, {
            "total_original": 0,
            "total_final": 0,
            "method": "no_quotes"
        }

    # 调用 v2 整合
    try:
        consolidated_quotes, stats = await consolidate_quotes_v2(
            all_quotes, call_llm_func, project_id, model
        )
    except Exception as e:
        print(f"[QuoteConsolidator] LLM consolidation failed, using fallback: {e}")
        consolidated_quotes, stats = consolidate_quotes_fallback(all_quotes)

    # 按文档重新分组
    doc_quotes: Dict[int, List[Dict]] = {i: [] for i in range(len(all_results))}

    for q in consolidated_quotes:
        source = q.get("source", {})
        doc_id = source.get("document_id", "")

        # 找到对应的文档
        found = False
        for doc_idx, doc_result in enumerate(all_results):
            if doc_result.get("document_id") == doc_id:
                doc_quotes[doc_idx].append(q)
                found = True
                break

        if not found:
            # 如果找不到对应文档，放到第一个文档
            if all_results:
                doc_quotes[0].append(q)

    # 重建结果
    consolidated_results = []
    for doc_idx, doc_result in enumerate(all_results):
        consolidated_results.append({
            **doc_result,
            "quotes": doc_quotes.get(doc_idx, [])
        })

    return consolidated_results, stats


# =============================================
# Material-Level Consolidation (v2.0 新增)
# =============================================

async def consolidate_material_quotes(
    material_id: str,
    quotes: List[Dict[str, Any]],
    call_llm_func,
    project_id: str = None,
    model: str = LLM_MODEL
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    材料级引用整合

    对单个材料的引用进行整合。这是新架构的核心函数。

    Args:
        material_id: 材料 ID
        quotes: 该材料的引用列表
        call_llm_func: LLM 调用函数
        project_id: 项目 ID（用于存档）
        model: LLM 模型名

    Returns:
        (整合后的引用列表, 统计信息)
    """
    if not quotes:
        return [], {"original_count": 0, "final_count": 0, "method": "empty"}

    if len(quotes) <= 1:
        return quotes, {
            "original_count": len(quotes),
            "final_count": len(quotes),
            "method": "single_quote"
        }

    # 确保所有引用都有 material_id
    for q in quotes:
        if "source" not in q:
            q["source"] = {}
        q["source"]["material_id"] = material_id

    # 调用 v2 整合
    try:
        consolidated_quotes, stats = await consolidate_quotes_v2(
            quotes, call_llm_func,
            project_id=f"{project_id}_{material_id}" if project_id else material_id,
            model=model
        )
        return consolidated_quotes, stats
    except Exception as e:
        print(f"[QuoteConsolidator] Material {material_id} LLM consolidation failed: {e}")
        return consolidate_quotes_fallback(quotes)


async def consolidate_all_material_quotes(
    material_results: List[Dict[str, Any]],
    call_llm_func,
    project_id: str = None,
    model: str = LLM_MODEL
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    整合所有材料的引用（材料级处理）

    这是新架构的主入口，按材料逐个处理。

    Args:
        material_results: 材料分析结果列表，每个包含 material_id 和 quotes
        call_llm_func: LLM 调用函数
        project_id: 项目 ID
        model: LLM 模型名

    Returns:
        (整合后的结果列表, 总体统计)
    """
    consolidated_results = []
    total_original = 0
    total_final = 0
    material_stats = []

    for mat_result in material_results:
        material_id = mat_result.get("material_id", "unknown")
        quotes = mat_result.get("quotes", [])
        total_original += len(quotes)

        # 按材料整合
        consolidated_quotes, stats = await consolidate_material_quotes(
            material_id=material_id,
            quotes=quotes,
            call_llm_func=call_llm_func,
            project_id=project_id,
            model=model
        )

        consolidated_results.append({
            **mat_result,
            "quotes": consolidated_quotes,
            "consolidation_stats": stats
        })

        total_final += len(consolidated_quotes)
        material_stats.append({
            "material_id": material_id,
            "original": len(quotes),
            "final": len(consolidated_quotes)
        })

    overall_stats = {
        "total_original": total_original,
        "total_final": total_final,
        "total_reduction": total_original - total_final,
        "reduction_rate": round((1 - total_final / total_original) * 100, 1) if total_original > 0 else 0,
        "materials_processed": len(material_results),
        "material_stats": material_stats,
        "method": "material_level_llm"
    }

    return consolidated_results, overall_stats


def consolidate_material_quotes_sync(
    material_id: str,
    quotes: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    材料级引用整合（同步版本，不使用 LLM）

    Args:
        material_id: 材料 ID
        quotes: 该材料的引用列表

    Returns:
        (整合后的引用列表, 统计信息)
    """
    if not quotes:
        return [], {"original_count": 0, "final_count": 0, "method": "empty"}

    # 确保所有引用都有 material_id
    for q in quotes:
        if "source" not in q:
            q["source"] = {}
        q["source"]["material_id"] = material_id

    return consolidate_quotes_fallback(quotes)


def consolidate_all_material_quotes_sync(
    material_results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    整合所有材料的引用（同步版本，不使用 LLM）

    Args:
        material_results: 材料分析结果列表

    Returns:
        (整合后的结果列表, 总体统计)
    """
    consolidated_results = []
    total_original = 0
    total_final = 0

    for mat_result in material_results:
        material_id = mat_result.get("material_id", "unknown")
        quotes = mat_result.get("quotes", [])
        total_original += len(quotes)

        consolidated_quotes, stats = consolidate_material_quotes_sync(
            material_id, quotes
        )

        consolidated_results.append({
            **mat_result,
            "quotes": consolidated_quotes,
            "consolidation_stats": stats
        })

        total_final += len(consolidated_quotes)

    overall_stats = {
        "total_original": total_original,
        "total_final": total_final,
        "total_reduction": total_original - total_final,
        "reduction_rate": round((1 - total_final / total_original) * 100, 1) if total_original > 0 else 0,
        "materials_processed": len(material_results),
        "method": "material_level_fallback"
    }

    return consolidated_results, overall_stats
