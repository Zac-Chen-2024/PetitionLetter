"""
Snippet Recommender - 根据标题/描述为新 SubArgument 推荐相关 Snippets

策略：
1. 规则过滤：排除已分配的 Snippets，优先同 Argument 范围内的
2. LLM 精排：语义相关性评分
"""

import json
from typing import List, Dict, Optional, Set
from pathlib import Path
from datetime import datetime, timezone
import portalocker

from .snippet_registry import load_registry
from .llm_client import call_llm, call_llm_text


# 数据存储根目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


# ==================== 数据加载 ====================

def load_legal_arguments(project_id: str) -> Dict:
    """加载 legal_arguments.json（共享读锁）"""
    args_file = PROJECTS_DIR / project_id / "arguments" / "legal_arguments.json"
    if not args_file.exists():
        return {"arguments": [], "sub_arguments": []}

    with open(args_file, 'r', encoding='utf-8') as f:
        portalocker.lock(f, portalocker.LOCK_SH)
        try:
            return json.load(f)
        finally:
            portalocker.unlock(f)


def save_legal_arguments(project_id: str, data: Dict):
    """保存 legal_arguments.json（排他写锁）"""
    args_dir = PROJECTS_DIR / project_id / "arguments"
    args_dir.mkdir(parents=True, exist_ok=True)
    args_file = args_dir / "legal_arguments.json"

    with open(args_file, 'w', encoding='utf-8') as f:
        portalocker.lock(f, portalocker.LOCK_EX)
        try:
            json.dump(data, f, ensure_ascii=False, indent=2)
        finally:
            portalocker.unlock(f)


def get_assigned_snippet_ids(project_id: str) -> Set[str]:
    """获取已分配给 SubArguments 的所有 snippet_ids"""
    legal_args = load_legal_arguments(project_id)
    assigned = set()

    for sub_arg in legal_args.get("sub_arguments", []):
        for snippet_id in sub_arg.get("snippet_ids", []):
            assigned.add(snippet_id)

    return assigned


def get_argument_snippet_ids(project_id: str, argument_id: str) -> Set[str]:
    """获取某个 Argument 下的所有 snippet_ids（父论点范围）"""
    legal_args = load_legal_arguments(project_id)

    for arg in legal_args.get("arguments", []):
        if arg.get("id") == argument_id:
            return set(arg.get("snippet_ids", []))

    return set()


def get_argument_info(project_id: str, argument_id: str) -> Optional[Dict]:
    """获取 Argument 信息"""
    legal_args = load_legal_arguments(project_id)

    for arg in legal_args.get("arguments", []):
        if arg.get("id") == argument_id:
            return arg

    return None


# ==================== 推荐核心逻辑 ====================

async def recommend_snippets_for_subargument(
    project_id: str,
    argument_id: str,
    title: str,
    description: str = None,
    exclude_snippet_ids: List[str] = None,
    max_candidates: int = 20,
    max_results: int = 5,
    provider: str = "deepseek"
) -> List[Dict]:
    """
    为新 SubArgument 推荐相关 Snippets

    Args:
        project_id: 项目 ID
        argument_id: 父 Argument ID
        title: 新 SubArgument 的标题
        description: 可选的描述
        exclude_snippet_ids: 要排除的 snippet IDs（如已在其他 SubArgument 中）
        max_candidates: 发送给 LLM 的最大候选数
        max_results: 返回的最大推荐数

    Returns:
        推荐的 snippets 列表，每个包含：
        - snippet_id
        - text
        - exhibit_id
        - page
        - relevance_score (0-1)
        - reason (推荐理由)
    """
    # 1. 加载所有 snippets
    all_snippets = load_registry(project_id)
    if not all_snippets:
        return []

    # 2. 获取已分配的 snippet_ids
    assigned_ids = get_assigned_snippet_ids(project_id)
    exclude_set = set(exclude_snippet_ids or []) | assigned_ids

    # 3. 获取父 Argument 的 snippet 范围（优先推荐这些）
    parent_snippet_ids = get_argument_snippet_ids(project_id, argument_id)

    # 4. 获取 Argument 信息（用于 LLM 上下文）
    argument_info = get_argument_info(project_id, argument_id)
    standard_key = argument_info.get("standard_key", "") if argument_info else ""
    argument_title = argument_info.get("title", "") if argument_info else ""

    # 5. 筛选候选集
    # 策略：优先父 Argument 范围内未分配的，其次是其他未分配的
    priority_candidates = []
    other_candidates = []

    for snip in all_snippets:
        snippet_id = snip.get("snippet_id")
        if snippet_id in exclude_set:
            continue

        if snippet_id in parent_snippet_ids:
            priority_candidates.append(snip)
        else:
            other_candidates.append(snip)

    # 合并候选集，优先级高的在前
    candidates = priority_candidates + other_candidates

    # 限制候选数量
    if len(candidates) > max_candidates:
        candidates = candidates[:max_candidates]

    if not candidates:
        return []

    # 6. 调用 LLM 精排
    ranked_snippets = await llm_rank_snippets(
        title=title,
        description=description,
        standard_key=standard_key,
        argument_title=argument_title,
        candidates=candidates,
        max_results=max_results,
        provider=provider
    )

    return ranked_snippets


async def llm_rank_snippets(
    title: str,
    description: str,
    standard_key: str,
    argument_title: str,
    candidates: List[Dict],
    max_results: int = 5,
    provider: str = "deepseek"
) -> List[Dict]:
    """
    使用 LLM 对候选 Snippets 进行语义相关性排序

    Returns:
        排序后的 snippets 列表，包含 relevance_score 和 reason
    """
    # 构建候选列表文本
    snippets_formatted = []
    snippet_map = {}  # 用于快速查找

    for i, snip in enumerate(candidates):
        snippet_id = snip.get("snippet_id")
        text = snip.get("text", "")[:300]  # 截取前300字符
        exhibit_id = snip.get("exhibit_id", "")
        page = snip.get("page", 0)

        snippets_formatted.append(
            f"[{i+1}] ID: {snippet_id}\n"
            f"    Source: Exhibit {exhibit_id}, Page {page}\n"
            f"    Text: {text}"
        )
        snippet_map[snippet_id] = snip

    system_prompt = """You are an EB-1A immigration attorney selecting evidence for a legal argument.

Your task is to rank candidate snippets by their relevance to a specific sub-argument.

Respond in JSON format with the following structure:
{
  "ranked_snippets": [
    {
      "snippet_id": "snp_xxx",
      "relevance_score": 0.95,
      "reason": "Brief explanation of why this snippet is relevant"
    }
  ]
}

Only include snippets with relevance_score >= 0.5. Return at most the top 5 most relevant snippets."""

    user_prompt = f"""## Context
Standard: {standard_key}
Main Argument: {argument_title}

## Sub-Argument to Support
Title: {title}
Description: {description or 'N/A'}

## Candidate Snippets
{chr(10).join(snippets_formatted)}

## Task
Rank these snippets by their relevance to the sub-argument "{title}".
Consider how well each snippet supports or provides evidence for this specific sub-argument."""

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=1500,
            provider=provider
        )

        ranked = result.get("ranked_snippets", [])

        # 填充完整信息
        enriched_results = []
        for item in ranked[:max_results]:
            snippet_id = item.get("snippet_id")
            if snippet_id in snippet_map:
                snip = snippet_map[snippet_id]
                enriched_results.append({
                    "snippet_id": snippet_id,
                    "text": snip.get("text", ""),
                    "exhibit_id": snip.get("exhibit_id", ""),
                    "page": snip.get("page", 0),
                    "bbox": snip.get("bbox"),
                    "relevance_score": item.get("relevance_score", 0.5),
                    "reason": item.get("reason", "")
                })

        return enriched_results

    except Exception as e:
        print(f"LLM ranking failed: {e}")
        # 降级：返回前 N 个候选（无排序）
        return [
            {
                "snippet_id": snip.get("snippet_id"),
                "text": snip.get("text", ""),
                "exhibit_id": snip.get("exhibit_id", ""),
                "page": snip.get("page", 0),
                "bbox": snip.get("bbox"),
                "relevance_score": 0.5,
                "reason": "Fallback recommendation (LLM unavailable)"
            }
            for snip in candidates[:max_results]
        ]


# ==================== SubArgument 创建 ====================

def create_subargument(
    project_id: str,
    argument_id: str,
    title: str,
    purpose: str,
    relationship: str,
    snippet_ids: List[str]
) -> Dict:
    """
    创建新的 SubArgument 并持久化

    Returns:
        新创建的 SubArgument 对象
    """
    import uuid

    # 加载现有数据
    legal_args = load_legal_arguments(project_id)

    # 生成新 SubArgument
    new_subarg = {
        "id": f"subarg-{uuid.uuid4().hex[:8]}",
        "argument_id": argument_id,
        "title": title,
        "purpose": purpose,
        "relationship": relationship,
        "snippet_ids": snippet_ids,
        "is_ai_generated": False,  # 用户手动创建
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    # 添加到 sub_arguments 列表
    if "sub_arguments" not in legal_args:
        legal_args["sub_arguments"] = []
    legal_args["sub_arguments"].append(new_subarg)

    # 更新父 Argument 的 sub_argument_ids
    for arg in legal_args.get("arguments", []):
        if arg["id"] == argument_id:
            if "sub_argument_ids" not in arg:
                arg["sub_argument_ids"] = []
            arg["sub_argument_ids"].append(new_subarg["id"])
            break

    # 保存
    save_legal_arguments(project_id, legal_args)

    return new_subarg


# ==================== Relationship 推断 ====================

async def infer_relationship(
    project_id: str,
    argument_id: str,
    subargument_title: str,
    provider: str = "deepseek"
) -> str:
    """
    根据子论点标题推断与父论点的关系

    与 subargument_generator.py 保持一致，由 LLM 自由生成 2-5 个词的关系描述

    Returns:
        relationship 字符串（如 "Proves leadership role", "Quantifies contributions" 等）
    """
    # 获取父 Argument 信息
    argument_info = get_argument_info(project_id, argument_id)
    if not argument_info:
        return "Supports main argument"  # 默认

    argument_title = argument_info.get("title", "")
    standard_key = argument_info.get("standard_key", "")

    # 与 subargument_generator.py 的 prompt 风格保持一致
    system_prompt = """You are an expert EB-1A immigration attorney.
Your task is to describe how a sub-argument supports its parent argument.

The relationship should be a short phrase (2-5 words) in English that explains
how this sub-argument contributes to proving the main argument.

Examples:
- "Proves leadership role"
- "Quantifies contributions"
- "Demonstrates industry recognition"
- "Shows organizational impact"
- "Establishes expert status"

Output ONLY the relationship phrase, nothing else."""

    user_prompt = f"""Standard: {standard_key}
Main Argument: {argument_title}
Sub-Argument Title: {subargument_title}

What is the relationship? (2-5 words)"""

    try:
        result = await call_llm_text(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=30,
            provider=provider
        )

        # 清理：移除引号和多余空格
        relationship = result.strip().strip('"\'').strip()

        # 如果为空或太长，使用默认值
        if not relationship or len(relationship) > 50:
            relationship = "Supports main argument"

        return relationship

    except Exception as e:
        print(f"Infer relationship failed: {e}")
        return "Supports main argument"  # 降级默认值
