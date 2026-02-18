"""
Context Enrichment Service - 上下文回溯服务

为提取的 snippets 添加原始文档上下文，防止信息丢失。

主要功能：
1. 回溯原始 OCR 文档，获取 snippet 前后的 blocks
2. 为每个 snippet 添加 surrounding_context
3. 提取完整的段落上下文（不只是单个 block）
4. 支持按 exhibit 或批量处理
"""

import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass


# 数据目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


@dataclass
class ContextWindow:
    """上下文窗口"""
    before_text: str        # 前文
    target_text: str        # 目标文本
    after_text: str         # 后文
    full_context: str       # 完整上下文
    page_numbers: List[int] # 涉及的页码
    block_ids: List[str]    # 涉及的 block IDs


def load_document(project_id: str, exhibit_id: str) -> Optional[Dict]:
    """加载原始 OCR 文档"""
    doc_path = PROJECTS_DIR / project_id / "documents" / f"{exhibit_id}.json"
    if doc_path.exists():
        with open(doc_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def get_block_map(document: Dict) -> Dict[str, Tuple[int, Dict]]:
    """
    构建 block_id -> (page_number, block) 的映射

    Returns:
        {block_id: (page_number, block_data)}
    """
    block_map = {}
    pages = document.get("pages", [])

    for page in pages:
        page_num = page.get("page_number", 0)
        blocks = page.get("text_blocks", [])

        for block in blocks:
            block_id = block.get("block_id", "")
            if block_id:
                block_map[block_id] = (page_num, block)

    return block_map


def get_ordered_blocks(document: Dict) -> List[Tuple[str, int, Dict]]:
    """
    获取按顺序排列的所有 blocks

    Returns:
        [(block_id, page_number, block_data), ...]
    """
    ordered = []
    pages = document.get("pages", [])

    for page in pages:
        page_num = page.get("page_number", 0)
        blocks = page.get("text_blocks", [])

        for block in blocks:
            block_id = block.get("block_id", "")
            text = block.get("text_content", "").strip()

            # 跳过空文本或太短的文本
            if not text or len(text) < 3:
                continue

            if block_id:
                ordered.append((block_id, page_num, block))

    return ordered


def extract_context_window(
    document: Dict,
    target_block_id: str,
    window_size: int = 2,
    max_context_chars: int = 500
) -> ContextWindow:
    """
    提取 target_block_id 周围的上下文窗口

    Args:
        document: 原始 OCR 文档
        target_block_id: 目标 block ID
        window_size: 前后各取多少个 blocks
        max_context_chars: 最大上下文字符数

    Returns:
        ContextWindow 包含前后上下文
    """
    ordered_blocks = get_ordered_blocks(document)

    # 找到目标 block 的索引
    target_idx = -1
    for idx, (bid, _, _) in enumerate(ordered_blocks):
        if bid == target_block_id:
            target_idx = idx
            break

    # 如果找不到，尝试模糊匹配
    if target_idx == -1:
        for idx, (bid, _, _) in enumerate(ordered_blocks):
            # 匹配 p{n}_b{m} 格式
            if target_block_id in bid or bid in target_block_id:
                target_idx = idx
                break

    if target_idx == -1:
        # 仍然找不到，返回空上下文
        return ContextWindow(
            before_text="",
            target_text="",
            after_text="",
            full_context="",
            page_numbers=[],
            block_ids=[]
        )

    # 获取前后 blocks
    start_idx = max(0, target_idx - window_size)
    end_idx = min(len(ordered_blocks), target_idx + window_size + 1)

    before_texts = []
    after_texts = []
    target_text = ""
    page_numbers = []
    block_ids = []

    for idx in range(start_idx, end_idx):
        bid, page_num, block = ordered_blocks[idx]
        text = block.get("text_content", "").strip()

        page_numbers.append(page_num)
        block_ids.append(bid)

        if idx < target_idx:
            # 前文：截取最后 N 个字符
            if len(text) > max_context_chars // window_size:
                text = "..." + text[-(max_context_chars // window_size):]
            before_texts.append(text)
        elif idx == target_idx:
            target_text = text
        else:
            # 后文：截取前 N 个字符
            if len(text) > max_context_chars // window_size:
                text = text[:max_context_chars // window_size] + "..."
            after_texts.append(text)

    before_text = " ".join(before_texts)
    after_text = " ".join(after_texts)

    # 构建完整上下文
    full_context_parts = []
    if before_text:
        full_context_parts.append(f"[BEFORE] {before_text}")
    full_context_parts.append(f"[TARGET] {target_text}")
    if after_text:
        full_context_parts.append(f"[AFTER] {after_text}")

    full_context = "\n".join(full_context_parts)

    return ContextWindow(
        before_text=before_text,
        target_text=target_text,
        after_text=after_text,
        full_context=full_context,
        page_numbers=list(set(page_numbers)),
        block_ids=block_ids
    )


def enrich_snippet_with_context(
    snippet: Dict,
    document: Dict,
    window_size: int = 2,
    max_context_chars: int = 500
) -> Dict:
    """
    为单个 snippet 添加上下文

    Args:
        snippet: 提取的 snippet
        document: 原始 OCR 文档
        window_size: 上下文窗口大小
        max_context_chars: 最大上下文字符数

    Returns:
        添加了上下文的 snippet
    """
    block_id = snippet.get("block_id", "")

    if not block_id:
        # 没有 block_id，无法回溯
        snippet["context"] = None
        return snippet

    context_window = extract_context_window(
        document,
        block_id,
        window_size=window_size,
        max_context_chars=max_context_chars
    )

    snippet["context"] = {
        "before": context_window.before_text,
        "after": context_window.after_text,
        "full_context": context_window.full_context,
        "surrounding_pages": context_window.page_numbers,
        "surrounding_blocks": context_window.block_ids
    }

    return snippet


def enrich_exhibit_snippets(
    project_id: str,
    exhibit_id: str,
    snippets: List[Dict],
    window_size: int = 2,
    max_context_chars: int = 500
) -> List[Dict]:
    """
    为一个 exhibit 的所有 snippets 添加上下文

    Args:
        project_id: 项目 ID
        exhibit_id: Exhibit ID
        snippets: 该 exhibit 的 snippets
        window_size: 上下文窗口大小
        max_context_chars: 最大上下文字符数

    Returns:
        添加了上下文的 snippets
    """
    # 加载原始文档
    document = load_document(project_id, exhibit_id)
    if not document:
        print(f"[ContextEnrichment] Document not found: {exhibit_id}")
        return snippets

    enriched = []
    for snippet in snippets:
        enriched_snippet = enrich_snippet_with_context(
            snippet.copy(),
            document,
            window_size=window_size,
            max_context_chars=max_context_chars
        )
        enriched.append(enriched_snippet)

    return enriched


def enrich_all_snippets(
    project_id: str,
    snippets: List[Dict],
    window_size: int = 2,
    max_context_chars: int = 500,
    save_result: bool = True
) -> Dict:
    """
    为项目中所有 snippets 添加上下文

    Args:
        project_id: 项目 ID
        snippets: 所有 snippets
        window_size: 上下文窗口大小
        max_context_chars: 最大上下文字符数
        save_result: 是否保存结果

    Returns:
        {
            "snippets": [...],
            "stats": {...}
        }
    """
    # 按 exhibit 分组
    by_exhibit = {}
    for snippet in snippets:
        exhibit_id = snippet.get("exhibit_id", "")
        if exhibit_id not in by_exhibit:
            by_exhibit[exhibit_id] = []
        by_exhibit[exhibit_id].append(snippet)

    print(f"[ContextEnrichment] Processing {len(snippets)} snippets from {len(by_exhibit)} exhibits...")

    all_enriched = []
    enriched_count = 0
    failed_count = 0

    for exhibit_id, exhibit_snippets in by_exhibit.items():
        enriched = enrich_exhibit_snippets(
            project_id,
            exhibit_id,
            exhibit_snippets,
            window_size=window_size,
            max_context_chars=max_context_chars
        )

        for s in enriched:
            if s.get("context") and s["context"].get("full_context"):
                enriched_count += 1
            else:
                failed_count += 1

        all_enriched.extend(enriched)

    print(f"[ContextEnrichment] Enriched {enriched_count}/{len(snippets)} snippets")

    result = {
        "snippets": all_enriched,
        "stats": {
            "total": len(snippets),
            "enriched": enriched_count,
            "failed": failed_count
        }
    }

    # 保存结果
    if save_result:
        enriched_dir = PROJECTS_DIR / project_id / "enriched"
        enriched_dir.mkdir(parents=True, exist_ok=True)

        enriched_file = enriched_dir / "enriched_snippets.json"
        with open(enriched_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"[ContextEnrichment] Saved to {enriched_file}")

    return result


def load_enriched_snippets(project_id: str) -> Optional[Dict]:
    """加载已添加上下文的 snippets"""
    enriched_file = PROJECTS_DIR / project_id / "enriched" / "enriched_snippets.json"
    if enriched_file.exists():
        with open(enriched_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


# ==================== Context-Aware Analysis ====================

def analyze_snippet_context(snippet: Dict) -> Dict:
    """
    分析 snippet 的上下文，识别可能遗漏的信息

    这个函数帮助识别 snippet 是否需要更多上下文来正确分类

    Returns:
        {
            "needs_context": bool,
            "context_type": str,  # "event_details", "organization_context", "date_context", etc.
            "missing_info": [str],
            "recommendation": str
        }
    """
    context = snippet.get("context", {})
    text = snippet.get("text", "")
    evidence_type = snippet.get("evidence_type", "")

    # 检查是否有上下文
    if not context or not context.get("full_context"):
        return {
            "needs_context": True,
            "context_type": "missing",
            "missing_info": ["No context available"],
            "recommendation": "Re-extract with context enrichment"
        }

    full_context = context.get("full_context", "")
    missing_info = []

    # 检查邀请类证据是否有完整信息
    if evidence_type in ["invitation", "speaking"]:
        invitation_keywords = ["invite", "invitation", "speaker", "keynote", "guest"]
        if any(kw in text.lower() for kw in invitation_keywords):
            # 检查是否有活动名称
            event_patterns = ["conference", "symposium", "summit", "event", "forum", "expo"]
            has_event = any(p in full_context.lower() for p in event_patterns)
            if not has_event:
                missing_info.append("Event/conference name")

            # 检查是否有日期
            import re
            date_pattern = r'\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}'
            if not re.search(date_pattern, full_context):
                missing_info.append("Event date")

    # 检查领导角色证据是否有组织上下文
    if evidence_type in ["leadership", "leading_role"]:
        org_patterns = ["company", "organization", "association", "club", "foundation"]
        has_org_context = any(p in full_context.lower() for p in org_patterns)
        if not has_org_context:
            missing_info.append("Organization details")

    # 检查奖项证据是否有评选标准
    if evidence_type in ["award", "prize"]:
        criteria_patterns = ["criteria", "selected", "evaluated", "judged", "competition"]
        has_criteria = any(p in full_context.lower() for p in criteria_patterns)
        if not has_criteria:
            missing_info.append("Selection criteria")

    needs_context = len(missing_info) > 0
    context_type = "complete" if not needs_context else _infer_context_type(missing_info)

    return {
        "needs_context": needs_context,
        "context_type": context_type,
        "missing_info": missing_info,
        "recommendation": "Consider extracting additional context" if needs_context else "Context sufficient"
    }


def _infer_context_type(missing_info: List[str]) -> str:
    """推断缺失的上下文类型"""
    if "Event" in str(missing_info) or "date" in str(missing_info).lower():
        return "event_details"
    if "Organization" in str(missing_info):
        return "organization_context"
    if "criteria" in str(missing_info).lower():
        return "evaluation_criteria"
    return "general"


# ==================== Integration with Argument Composer ====================

def get_context_for_composition(
    project_id: str,
    snippet: Dict,
    include_surrounding: bool = True
) -> str:
    """
    获取用于论点组合的完整上下文

    这个函数为 argument_composer 提供增强的上下文

    Args:
        project_id: 项目 ID
        snippet: 提取的 snippet
        include_surrounding: 是否包含周围上下文

    Returns:
        用于论点组合的完整文本
    """
    text = snippet.get("text", "")

    if not include_surrounding:
        return text

    context = snippet.get("context")

    # 如果 snippet 没有上下文，尝试动态加载
    if not context:
        exhibit_id = snippet.get("exhibit_id", "")
        block_id = snippet.get("block_id", "")

        if exhibit_id and block_id:
            document = load_document(project_id, exhibit_id)
            if document:
                context_window = extract_context_window(document, block_id)
                context = {
                    "before": context_window.before_text,
                    "after": context_window.after_text,
                    "full_context": context_window.full_context
                }

    if context:
        # 构建增强文本
        parts = []

        before = context.get("before", "")
        if before:
            parts.append(f"[Context before: {before}]")

        parts.append(text)

        after = context.get("after", "")
        if after:
            parts.append(f"[Context after: {after}]")

        return " ".join(parts)

    return text
