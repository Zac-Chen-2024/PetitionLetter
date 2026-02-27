"""
SubArgument Generator - 次级子论点生成器

基于精华子论点 (Arguments) 进行细分，生成 SubArguments。

核心原则：
1. 保持精华子论点策略不变（约14个 Arguments）
2. 对每个 Argument 的 snippets 进行 LLM 细分
3. 每个 Argument 生成 2-4 个 SubArguments
4. relationship 字段由 LLM 生成（如 "证明管理能力"）
"""

import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import uuid

from .llm_client import call_llm


# ==================== Prompt Templates ====================

SUBDIVIDE_SYSTEM_PROMPT = """You are an expert EB-1A immigration attorney. Your task is to organize evidence snippets
within an argument into logical sub-groups (sub-arguments).

Each sub-group should:
1. Have a clear theme (e.g., "Scope of Responsibilities", "Performance Achievements", "Industry Recognition")
2. Contain 1-5 related snippets
3. Have a relationship label explaining how it supports the main argument

Output in English for all titles and relationship labels."""

# ==================== Standard-specific subdivision guidance ====================

STANDARD_SUBDIVISION_GUIDANCE = {
    "awards": (
        "Split by INDIVIDUAL AWARD. Each sub-argument = one distinct award. "
        "Within each: award description → awarding body prestige → selection rigor → competitiveness → peer comparison."
    ),
    "membership": (
        "Split by INDIVIDUAL ASSOCIATION. Each sub-argument = one qualifying association. "
        "Within each: association intro → membership criteria → review process → notable members."
    ),
    "published_material": (
        "Split by INDIVIDUAL MEDIA COVERAGE. Each sub-argument = one media report about the applicant. "
        "Within each: article summary → media outlet authority → coverage scope."
    ),
    "judging": (
        "Split by INDIVIDUAL JUDGING ROLE. Each sub-argument = one judging appointment or event. "
        "Within each: role/title → organization prestige → judging scope → applicant's influence → co-judges."
    ),
    "original_contribution": (
        "Split by INDIVIDUAL CONTRIBUTION. Each sub-argument = one distinct original work or methodology. "
        "Within each: contribution description → quantified impact → expert endorsements → adoption."
    ),
    "scholarly_articles": (
        "Split by INDIVIDUAL PUBLICATION. Each sub-argument = one article or book. "
        "Within each: title + venue → journal prestige → research novelty → citation impact."
    ),
    "leading_role": (
        "Split by INDIVIDUAL ORGANIZATION. Each sub-argument = one organization. "
        "Two-tier structure: (1) organization's distinguished reputation, then (2) applicant's role and achievements."
    ),
    "high_salary": (
        "Typically NO sub-division. Keep as single unified argument. "
        "If multiple income sources exist, may split by income type (salary, consulting, royalties)."
    ),
    "display": (
        "Split by INDIVIDUAL EXHIBITION or SHOWCASE. Each sub-argument = one exhibition event. "
        "Within each: exhibition intro → prestige → applicant's work and reception."
    ),
    "commercial_success": (
        "Split by INDIVIDUAL COMMERCIAL ACHIEVEMENT. Each sub-argument = one product or commercial metric. "
        "Within each: commercial data → industry benchmark → media recognition."
    ),
}

SUBDIVIDE_USER_PROMPT = """Main Argument: {argument_title}
Standard: {standard}
Total Snippets: {snippet_count}

## How to Split Sub-Arguments for This Standard
{subdivision_guidance}

## Snippets
{snippets_formatted}

Organize these snippets into logical sub-groups following the guidance above.

Return JSON:
{{
  "sub_arguments": [
    {{
      "title": "...",
      "purpose": "...",
      "relationship": "...",
      "snippet_ids": ["S1", "S3"]
    }}
  ]
}}

RULES:
1. Follow the standard-specific splitting unit above (per-award, per-publication, per-role, etc.)
2. Each snippet must be assigned to exactly ONE sub-group
3. Use English for all title, purpose, and relationship fields
4. Relationship should be 2-5 words explaining how this supports the main argument
5. If snippets are too few (<=3), create 2 sub-groups
6. Create at least 2 sub-groups"""


@dataclass
class GeneratedSubArgument:
    """Generated sub-argument data structure"""
    id: str
    argument_id: str
    title: str
    purpose: str
    relationship: str  # LLM 生成的关系描述
    snippet_ids: List[str]
    is_ai_generated: bool = True
    status: str = "draft"
    created_at: str = ""


async def subdivide_argument(
    argument: Dict,
    snippets: List[Dict],
    provider: str = "deepseek"
) -> List[GeneratedSubArgument]:
    """
    对单个精华子论点进行细分

    Args:
        argument: 精华子论点（来自 argument_composer）
        snippets: 该 argument 关联的所有 snippets
        provider: LLM provider

    Returns:
        List of GeneratedSubArgument
    """
    if not snippets:
        return []

    argument_id = argument.get("id", f"arg-{uuid.uuid4().hex[:8]}")
    argument_title = argument.get("title", "Argument")
    standard = argument.get("standard", "")

    # 如果 snippets 太少，简单分组
    if len(snippets) <= 2:
        return [_create_single_subarg(argument_id, snippets, standard)]

    # 创建简化 ID 映射
    id_mapping = {}  # simple_id -> real_snippet_id
    snippets_lines = []

    for i, s in enumerate(snippets, 1):
        real_id = s.get('snippet_id', s.get('id', ''))
        simple_id = f"S{i}"
        id_mapping[simple_id] = real_id

        text = s.get('text', '')[:300]
        exhibit_id = s.get('exhibit_id', '')
        layer = s.get('evidence_layer', 'claim')
        snippets_lines.append(f"[{simple_id}] ({exhibit_id}, {layer}) {text}")

    snippets_formatted = "\n".join(snippets_lines)

    # Get standard-specific subdivision guidance
    guidance = STANDARD_SUBDIVISION_GUIDANCE.get(
        standard,
        "Split by distinct evidence themes or aspects."
    )

    # Build prompt
    user_prompt = SUBDIVIDE_USER_PROMPT.format(
        argument_title=argument_title,
        standard=standard,
        snippet_count=len(snippets),
        subdivision_guidance=guidance,
        snippets_formatted=snippets_formatted
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=SUBDIVIDE_SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=2000
        )

        raw_sub_args = result.get('sub_arguments', [])
        if not raw_sub_args:
            print(f"[SubArgGenerator] LLM returned no sub-arguments for {argument_title}, using fallback")
            return [_create_single_subarg(argument_id, snippets, standard)]

        # Convert to GeneratedSubArgument
        sub_arguments = []
        for raw_sa in raw_sub_args:
            # Map simple IDs to real IDs
            simple_ids = raw_sa.get('snippet_ids', [])
            real_ids = []
            for sid in simple_ids:
                normalized = sid.upper() if isinstance(sid, str) else str(sid)
                if not normalized.startswith('S'):
                    normalized = f"S{normalized}"
                if normalized in id_mapping:
                    real_ids.append(id_mapping[normalized])

            if not real_ids:
                continue

            sub_arg = GeneratedSubArgument(
                id=f"subarg-{uuid.uuid4().hex[:8]}",
                argument_id=argument_id,
                title=raw_sa.get('title', 'Evidence Group'),
                purpose=raw_sa.get('purpose', ''),
                relationship=raw_sa.get('relationship', 'Supports argument'),
                snippet_ids=real_ids,
                is_ai_generated=True,
                status="draft",
                created_at=datetime.now(timezone.utc).isoformat()
            )
            sub_arguments.append(sub_arg)

        # Check for unassigned snippets
        assigned_ids = set()
        for sa in sub_arguments:
            assigned_ids.update(sa.snippet_ids)

        unassigned = [s for s in snippets if s.get('snippet_id', s.get('id', '')) not in assigned_ids]
        if unassigned:
            # Add unassigned to a catch-all sub-argument
            catch_all = GeneratedSubArgument(
                id=f"subarg-{uuid.uuid4().hex[:8]}",
                argument_id=argument_id,
                title="Additional Evidence",
                purpose="Supplementary supporting materials",
                relationship="Additional support",
                snippet_ids=[s.get('snippet_id', s.get('id', '')) for s in unassigned],
                is_ai_generated=True,
                status="draft",
                created_at=datetime.now(timezone.utc).isoformat()
            )
            sub_arguments.append(catch_all)

        print(f"[SubArgGenerator] Subdivided '{argument_title}': {len(sub_arguments)} sub-arguments from {len(snippets)} snippets")
        return sub_arguments

    except Exception as e:
        print(f"[SubArgGenerator] Error subdividing {argument_title}: {e}")
        return [_create_single_subarg(argument_id, snippets, standard)]


def _create_single_subarg(argument_id: str, snippets: List[Dict], standard: str) -> GeneratedSubArgument:
    """Create a single sub-argument containing all snippets (fallback)"""
    snippet_ids = [s.get('snippet_id', s.get('id', '')) for s in snippets]

    # Generate relationship based on standard
    relationship_map = {
        "membership": "Proves membership qualification",
        "published_material": "Demonstrates media coverage",
        "original_contribution": "Demonstrates original contribution",
        "leading_role": "Proves leadership role",
        "awards": "Proves award achievement",
        "judging": "Proves judging activity",
        "scholarly_articles": "Demonstrates scholarly authorship",
        "display": "Shows exhibition display",
        "high_salary": "Proves high remuneration",
        "commercial_success": "Demonstrates commercial success",
    }
    relationship = relationship_map.get(standard, "Supports argument")

    return GeneratedSubArgument(
        id=f"subarg-{uuid.uuid4().hex[:8]}",
        argument_id=argument_id,
        title="Primary Evidence",
        purpose="Core evidence supporting the main argument",
        relationship=relationship,
        snippet_ids=snippet_ids,
        is_ai_generated=True,
        status="draft",
        created_at=datetime.now(timezone.utc).isoformat()
    )


async def generate_sub_arguments_for_composed(
    composed_arguments: Dict[str, List[Dict]],
    all_snippets: List[Dict],
    provider: str = "deepseek",
    progress_callback=None
) -> Tuple[List[Dict], List[Dict]]:
    """
    为所有精华子论点生成 SubArguments

    Args:
        composed_arguments: argument_composer 生成的精华子论点 {standard: [args]}
        all_snippets: 所有 snippets
        provider: LLM provider
        progress_callback: Optional progress callback

    Returns:
        (arguments_with_subarg_ids, all_sub_arguments)
    """
    # Build snippet lookup
    snippet_map = {}
    for s in all_snippets:
        sid = s.get('snippet_id', s.get('id', ''))
        if sid:
            snippet_map[sid] = s

    all_sub_arguments = []
    updated_arguments = []

    # Count total arguments for progress
    total_args = sum(len(args) for args in composed_arguments.values())
    processed = 0

    for standard, args in composed_arguments.items():
        for arg in args:
            processed += 1
            if progress_callback:
                progress_callback(processed, total_args, f"Subdividing: {arg.get('title', '')[:30]}...")

            # Collect snippets for this argument
            arg_snippet_ids = set()
            for layer in ['claim', 'proof', 'significance', 'context']:
                for item in arg.get(layer, []):
                    sid = item.get('snippet_id', '')
                    if sid:
                        arg_snippet_ids.add(sid)

            arg_snippets = [snippet_map[sid] for sid in arg_snippet_ids if sid in snippet_map]

            # Generate argument ID if not present
            arg_id = arg.get('id') or f"arg-{uuid.uuid4().hex[:8]}"
            arg['id'] = arg_id

            # Subdivide
            sub_args = await subdivide_argument(
                argument={'id': arg_id, 'title': arg.get('title', ''), 'standard': standard},
                snippets=arg_snippets,
                provider=provider
            )

            # Update argument with sub_argument_ids
            arg['sub_argument_ids'] = [sa.id for sa in sub_args]
            updated_arguments.append(arg)

            # Collect sub-arguments
            all_sub_arguments.extend([asdict(sa) for sa in sub_args])

            # Rate limiting
            await asyncio.sleep(0.2)

    print(f"[SubArgGenerator] Generated {len(all_sub_arguments)} sub-arguments for {len(updated_arguments)} arguments")
    return updated_arguments, all_sub_arguments
