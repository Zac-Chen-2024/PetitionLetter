"""
Token Estimator Service - Token 预估与分批逻辑

功能:
- 估算文本的 token 数量
- 估算候选组的 token 数量
- 将候选组分批以适应 LLM 上下文限制

设计决策:
- 中文约 1.5 字符/token，英文约 4 字符/token (粗略估计，但足够安全)
- 每批预留空间给系统 prompt 和响应
- 顺序处理批次，不并发（保证稳定性）
"""

import re
from typing import List, Dict, Any


# =============================================
# 配置常量
# =============================================

# 分批配置
MAX_BATCH_TOKENS = 8000       # 每批最大 token（实际内容）
MAX_BATCH_GROUPS = 20         # 每批最大组数
CONTEXT_RESERVE = 4000        # 预留给系统 prompt 和响应
PROMPT_OVERHEAD_PER_GROUP = 200  # 每组的 prompt 模板开销

# Token 估算因子
CHINESE_CHAR_FACTOR = 1.5     # 中文字符 -> token
OTHER_CHAR_FACTOR = 0.25      # 其他字符 -> token (约 4 字符/token)


# =============================================
# Token 估算函数
# =============================================

def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数

    使用粗略但安全的估算方法:
    - 中文字符: 约 1.5 token/字符
    - 英文/数字/标点: 约 0.25 token/字符 (4 字符/token)

    Args:
        text: 要估算的文本

    Returns:
        估算的 token 数量
    """
    if not text:
        return 0

    # 计算中文字符数量
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))

    # 计算其他字符数量
    other_chars = len(text) - chinese_chars

    # 估算 token 数
    tokens = int(chinese_chars * CHINESE_CHAR_FACTOR + other_chars * OTHER_CHAR_FACTOR)

    return max(1, tokens)  # 至少 1 token


def estimate_quote_tokens(quote: Dict[str, Any]) -> int:
    """
    估算单个引用的 token 数

    Args:
        quote: 引用字典，包含 "quote" 和 "relevance" 字段

    Returns:
        估算的 token 数量
    """
    total = 0

    # 引用文本
    quote_text = quote.get("quote", "")
    total += estimate_tokens(quote_text)

    # 相关性说明
    relevance = quote.get("relevance", "")
    total += estimate_tokens(relevance)

    # standard_key 等元数据开销
    total += 20

    return total


def estimate_group_tokens(group: Dict[str, Any]) -> int:
    """
    估算一个候选组的 token 数

    Args:
        group: 候选组字典，包含 "quotes" 列表

    Returns:
        估算的 token 数量（包括 prompt 开销）
    """
    total = 0

    quotes = group.get("quotes", [])
    for quote in quotes:
        total += estimate_quote_tokens(quote)

    # 加上 prompt 模板开销
    total += PROMPT_OVERHEAD_PER_GROUP

    return total


def estimate_item_tokens(item: Dict[str, Any]) -> int:
    """
    估算一个项目（候选组或独立引用）的 token 数

    Args:
        item: 项目字典

    Returns:
        估算的 token 数量
    """
    item_type = item.get("type", "group")

    if item_type == "single":
        # 独立引用
        quote = item.get("quote", {})
        return estimate_quote_tokens(quote) + PROMPT_OVERHEAD_PER_GROUP
    else:
        # 候选组
        return estimate_group_tokens(item)


# =============================================
# 分批逻辑
# =============================================

def split_into_batches(
    items: List[Dict[str, Any]],
    max_tokens: int = MAX_BATCH_TOKENS,
    max_groups: int = MAX_BATCH_GROUPS
) -> List[List[Dict[str, Any]]]:
    """
    将项目（候选组 + 独立引用）分成多批

    分批策略:
    - 每批 token 数不超过 max_tokens
    - 每批项目数不超过 max_groups
    - 尽量均匀分配

    Args:
        items: 项目列表（候选组和独立引用）
        max_tokens: 每批最大 token 数
        max_groups: 每批最大项目数

    Returns:
        批次列表，每批是一个项目列表
    """
    if not items:
        return []

    batches = []
    current_batch = []
    current_tokens = 0

    for item in items:
        item_tokens = estimate_item_tokens(item)

        # 检查是否需要开始新批次
        should_start_new_batch = (
            (current_tokens + item_tokens > max_tokens and current_batch) or
            (len(current_batch) >= max_groups)
        )

        if should_start_new_batch:
            batches.append(current_batch)
            current_batch = [item]
            current_tokens = item_tokens
        else:
            current_batch.append(item)
            current_tokens += item_tokens

    # 添加最后一批
    if current_batch:
        batches.append(current_batch)

    return batches


def estimate_batch_stats(batches: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    计算批次统计信息

    Args:
        batches: 批次列表

    Returns:
        统计信息字典
    """
    if not batches:
        return {
            "total_batches": 0,
            "total_items": 0,
            "estimated_total_tokens": 0,
            "avg_tokens_per_batch": 0,
            "batch_details": []
        }

    batch_details = []
    total_items = 0
    total_tokens = 0

    for i, batch in enumerate(batches):
        batch_tokens = sum(estimate_item_tokens(item) for item in batch)
        batch_details.append({
            "batch_index": i + 1,
            "item_count": len(batch),
            "estimated_tokens": batch_tokens
        })
        total_items += len(batch)
        total_tokens += batch_tokens

    return {
        "total_batches": len(batches),
        "total_items": total_items,
        "estimated_total_tokens": total_tokens,
        "avg_tokens_per_batch": round(total_tokens / len(batches), 0) if batches else 0,
        "batch_details": batch_details
    }


# =============================================
# 工具函数
# =============================================

def validate_batch_size(batch: List[Dict[str, Any]], max_tokens: int = MAX_BATCH_TOKENS) -> bool:
    """
    验证批次大小是否合理

    Args:
        batch: 批次
        max_tokens: 最大 token 数

    Returns:
        是否合理
    """
    total_tokens = sum(estimate_item_tokens(item) for item in batch)
    return total_tokens <= max_tokens


def get_batch_config() -> Dict[str, Any]:
    """
    获取当前批处理配置

    Returns:
        配置字典
    """
    return {
        "max_batch_tokens": MAX_BATCH_TOKENS,
        "max_batch_groups": MAX_BATCH_GROUPS,
        "context_reserve": CONTEXT_RESERVE,
        "prompt_overhead_per_group": PROMPT_OVERHEAD_PER_GROUP,
        "chinese_char_factor": CHINESE_CHAR_FACTOR,
        "other_char_factor": OTHER_CHAR_FACTOR
    }
