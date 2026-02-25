"""
Petition Writer V3 - OCR 回溯写作

核心改进（v3.1 — OCR Traceback）：
1. snippet 是索引指针，写作时回溯 OCR 原文
2. 写作粒度从 per-SubArgument 提升到 per-Argument
3. LLM 看到完整 OCR 页面，从中提取所有细节

数据流：
Argument → SubArgument结构(大纲) + snippet指针
         → 加载所有引用exhibit的OCR完整页面
         → LLM按大纲、看原文、写深度论证

输出：{text, snippet_ids, subargument_id, argument_id, exhibit_refs}[]
"""

import json
import logging
from typing import List, Dict, Optional, Any
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

from .llm_client import call_llm, call_llm_text
from .snippet_registry import load_registry
from .standards_registry import get_standard_name
import re

logger = logging.getLogger(__name__)


# ============================================
# Snippet ID 映射工具
# ============================================

def _parse_old_snippet_id(old_id: str) -> Optional[Dict]:
    """
    解析旧格式 snippet ID

    旧格式: snp_C2_p2_p2_b5_eadb0715
    解析为: {exhibit_id: "C2", page: 2, block: "b5", block_full: "p2_b5", hash: "eadb0715"}
    """
    if not old_id or not old_id.startswith("snp_"):
        return None

    # 格式: snp_{exhibit}_{pX}_{pY}_{bZ}_{hash}
    # 例如: snp_C2_p2_p2_b5_eadb0715
    parts = old_id.split("_")
    if len(parts) < 6:
        return None

    try:
        exhibit_id = parts[1]  # C2
        page_part1 = parts[2]  # p2
        page_part2 = parts[3]  # p2
        block_part = parts[4]  # b5
        hash_part = parts[5]   # eadb0715

        # 提取页码数字
        page = int(page_part1[1:]) if page_part1.startswith("p") else 0

        # 构建完整的 block_id (格式: p2_b5)
        block_full = f"{page_part2}_{block_part}"

        return {
            "exhibit_id": exhibit_id,
            "page": page,
            "block": block_part,
            "block_full": block_full,
            "hash": hash_part
        }
    except (IndexError, ValueError):
        return None


def _map_old_snippet_id_to_new(
    old_id: str,
    snippet_registry: List[Dict]
) -> Optional[Dict]:
    """
    将旧格式 snippet ID 映射到新的 registry snippet

    Args:
        old_id: 旧格式 ID (如 "snp_C2_p2_p2_b5_eadb0715")
        snippet_registry: 注册表中的 snippets 列表

    Returns:
        匹配的 registry snippet dict，或 None
    """
    # 如果已经是新格式，直接查找
    if old_id.startswith("snip_"):
        for snip in snippet_registry:
            if snip.get("snippet_id") == old_id:
                return snip
        return None

    # 解析旧格式
    parsed = _parse_old_snippet_id(old_id)
    if not parsed:
        return None

    # 在 registry 中查找匹配
    # 匹配条件: exhibit_id 相同 且 source_block_ids 包含 block_full
    for snip in snippet_registry:
        if snip.get("exhibit_id") != parsed["exhibit_id"]:
            continue

        source_blocks = snip.get("source_block_ids", [])
        if parsed["block_full"] in source_blocks:
            return snip

    return None


def _build_snippet_lookup(snippet_registry: List[Dict]) -> Dict:
    """
    构建双向查找表

    Returns:
        {
            "by_new_id": {"snip_xxx": snippet_dict},
            "by_exhibit_block": {("C2", "p2_b5"): snippet_dict}
        }
    """
    by_new_id = {}
    by_exhibit_block = {}

    for snip in snippet_registry:
        new_id = snip.get("snippet_id", "")
        by_new_id[new_id] = snip

        exhibit_id = snip.get("exhibit_id", "")
        for block_id in snip.get("source_block_ids", []):
            key = (exhibit_id, block_id)
            by_exhibit_block[key] = snip

    return {
        "by_new_id": by_new_id,
        "by_exhibit_block": by_exhibit_block
    }


# ============================================
# 常量定义
# ============================================

DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"

# EB-1A 标准名称映射
EB1A_STANDARDS = {
    "awards": "Awards",
    "membership": "Membership in Associations",
    "press": "Published Material",
    "published_material": "Published Material",
    "judging": "Judging",
    "original_contribution": "Original Contribution",
    "original_contributions": "Original Contribution",
    "scholarly_articles": "Scholarly Articles",
    "exhibitions": "Artistic Exhibitions",
    "leading_role": "Leading or Critical Role",
    "high_salary": "High Salary",
    "commercial_success": "Commercial Success"
}

# 法规引用
LEGAL_REFS = {
    "awards": "8 C.F.R. §204.5(h)(3)(i)",
    "membership": "8 C.F.R. §204.5(h)(3)(ii)",
    "press": "8 C.F.R. §204.5(h)(3)(iii)",
    "published_material": "8 C.F.R. §204.5(h)(3)(iii)",
    "judging": "8 C.F.R. §204.5(h)(3)(iv)",
    "original_contribution": "8 C.F.R. §204.5(h)(3)(v)",
    "original_contributions": "8 C.F.R. §204.5(h)(3)(v)",
    "scholarly_articles": "8 C.F.R. §204.5(h)(3)(vi)",
    "exhibitions": "8 C.F.R. §204.5(h)(3)(vii)",
    "leading_role": "8 C.F.R. §204.5(h)(3)(viii)",
    "high_salary": "8 C.F.R. §204.5(h)(3)(ix)",
    "commercial_success": "8 C.F.R. §204.5(h)(3)(x)"
}


def _get_standard_display_name(standard_key: str) -> str:
    """Get display name for a standard key, trying registry first then legacy dict."""
    # Try all project types via registry
    for ptype in ("EB-1A", "NIW"):
        name = get_standard_name(ptype, standard_key)
        if name != standard_key:
            return name
    # Fallback to legacy dict
    return EB1A_STANDARDS.get(standard_key, standard_key)


# ============================================
# Exhibit OCR 缓存和加载
# ============================================

_exhibit_cache: Dict[str, Dict] = {}


def _load_exhibit_json(project_id: str, exhibit_id: str) -> Optional[Dict]:
    """
    加载并缓存 exhibit JSON，避免同一 exhibit 被多个 argument 重复读取。

    Returns:
        exhibit dict with {exhibit_id, pages: [{page_number, text_blocks, markdown_text}], ...}
        or None if file not found
    """
    cache_key = f"{project_id}:{exhibit_id}"
    if cache_key in _exhibit_cache:
        return _exhibit_cache[cache_key]

    path = PROJECTS_DIR / project_id / "documents" / f"{exhibit_id}.json"
    if not path.exists():
        logger.warning(f"Exhibit file not found: {path}")
        return None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _exhibit_cache[cache_key] = data
        return data
    except Exception as e:
        logger.warning(f"Failed to load exhibit {exhibit_id}: {e}")
        return None


def _extract_page_text(exhibit_data: Dict, page_numbers: set) -> str:
    """
    从 exhibit JSON 中提取指定页面的文本内容。

    对于每个请求的页面，也包含相邻页（page±1）以提供上下文。

    Returns:
        格式化的页面文本 "[Page N]\n{text_content}\n..."
    """
    if not exhibit_data or not exhibit_data.get("pages"):
        return ""

    # Expand page set to include adjacent pages for context
    expanded_pages = set()
    for p in page_numbers:
        expanded_pages.add(max(1, p - 1))
        expanded_pages.add(p)
        expanded_pages.add(p + 1)

    page_texts = []
    for page in exhibit_data.get("pages", []):
        pn = page.get("page_number", 0)
        if pn not in expanded_pages:
            continue

        # Collect text from all text blocks on this page
        blocks = page.get("text_blocks", [])
        block_texts = []
        for block in blocks:
            text = block.get("text_content", "").strip()
            if text and block.get("block_type") != "image":
                block_texts.append(text)

        if block_texts:
            page_text = "\n".join(block_texts)
            page_texts.append(f"[Page {pn}]\n{page_text}")

    return "\n\n".join(page_texts)


def load_exhibit_pages_for_argument(
    project_id: str,
    argument: Dict,
    all_snippets: Dict
) -> Dict[str, str]:
    """
    收集 argument 引用的所有 exhibit 的 OCR 页面原文。

    Args:
        project_id: 项目 ID
        argument: argument dict with sub_arguments, each with snippets
        all_snippets: snippet_id → snippet dict (from load_subargument_context output)

    Returns:
        {exhibit_id: formatted_text}  按 exhibit 分组的完整页面文本
    """
    # Step 1: Collect all referenced exhibit_ids and their page numbers
    exhibit_pages: Dict[str, set] = defaultdict(set)

    for subarg in argument.get("sub_arguments", []):
        for snip in subarg.get("snippets", []):
            exhibit_id = snip.get("exhibit", "")
            page = snip.get("page", 0)
            if exhibit_id and page > 0:
                exhibit_pages[exhibit_id].add(page)

    # Step 2: Load exhibit JSONs and extract page text
    exhibit_texts: Dict[str, str] = {}
    for exhibit_id, pages in exhibit_pages.items():
        exhibit_data = _load_exhibit_json(project_id, exhibit_id)
        if not exhibit_data:
            continue

        text = _extract_page_text(exhibit_data, pages)
        if text:
            exhibit_texts[exhibit_id] = text
            logger.info(
                f"Loaded OCR for Exhibit {exhibit_id}: "
                f"{len(pages)} referenced pages, {len(text)} chars"
            )

    return exhibit_texts


# ============================================
# 数据加载函数
# ============================================

def load_legal_arguments(project_id: str) -> Optional[Dict]:
    """加载 legal_arguments.json"""
    legal_file = PROJECTS_DIR / project_id / "arguments" / "legal_arguments.json"
    if legal_file.exists():
        with open(legal_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def load_subargument_context(
    project_id: str,
    standard_key: str,
    argument_ids: List[str] = None,
    subargument_ids: List[str] = None
) -> Dict:
    """
    加载用于写作的 SubArgument 上下文

    Args:
        project_id: 项目 ID
        standard_key: 标准 key (如 "membership", "leading_role")
        argument_ids: 可选，指定要生成的 Argument IDs
        subargument_ids: 可选，指定要生成的 SubArgument IDs（更细粒度）

    Returns:
        {
            "standard": {"key": str, "name": str, "legal_ref": str},
            "arguments": [
                {
                    "id": str,
                    "title": str,
                    "sub_arguments": [
                        {
                            "id": str,
                            "title": str,
                            "purpose": str,
                            "relationship": str,
                            "snippets": [
                                {"id": str, "exhibit": str, "text": str, "page": int}
                            ]
                        }
                    ]
                }
            ]
        }
    """
    # 加载数据
    legal_args = load_legal_arguments(project_id)
    if not legal_args:
        return {"standard": None, "arguments": []}

    snippet_registry = load_registry(project_id)

    # If registry is empty, fall back to combined extraction data
    if not snippet_registry:
        combined_file = PROJECTS_DIR / project_id / "extraction" / "combined_extraction.json"
        if combined_file.exists():
            with open(combined_file, 'r', encoding='utf-8') as f:
                combined_data = json.load(f)
            snippet_registry = combined_data.get("snippets", [])

    # 构建双向查找表（支持新旧两种 ID 格式）
    snippet_lookup = _build_snippet_lookup(snippet_registry)
    snippet_map = snippet_lookup["by_new_id"]

    arguments = legal_args.get("arguments", [])
    sub_arguments = legal_args.get("sub_arguments", [])

    # 构建 SubArgument 索引
    subarg_map = {sa["id"]: sa for sa in sub_arguments}

    # 过滤该 Standard 的 Arguments
    filtered_args = [
        a for a in arguments
        if a.get("standard_key") == standard_key
    ]

    # 如果指定了 argument_ids，进一步过滤
    if argument_ids:
        filtered_args = [a for a in filtered_args if a.get("id") in argument_ids]

    # 构建输出结构
    result_arguments = []
    for arg in filtered_args:
        arg_subargs = []
        for subarg_id in arg.get("sub_argument_ids", []):
            # 如果指定了 subargument_ids，只处理指定的
            if subargument_ids and subarg_id not in subargument_ids:
                continue

            subarg = subarg_map.get(subarg_id)
            if not subarg:
                continue

            # 加载该 SubArgument 的 Snippets
            snippets = []
            for snip_id in subarg.get("snippet_ids", []):
                # 支持新旧两种 ID 格式
                snip = snippet_map.get(snip_id)
                if not snip:
                    # 尝试映射旧格式 ID
                    snip = _map_old_snippet_id_to_new(snip_id, snippet_registry)

                if snip:
                    # 使用实际的 registry ID（新格式）供 LLM 引用
                    actual_id = snip.get("snippet_id", snip_id)
                    snippets.append({
                        "id": actual_id,
                        "original_id": snip_id,  # 保留原始 ID 以便调试
                        "exhibit": snip.get("exhibit_id", "Unknown"),
                        "text": snip.get("text", "")[:500],  # 限制长度
                        "page": snip.get("page", 0)
                    })

            arg_subargs.append({
                "id": subarg_id,
                "title": subarg.get("title", ""),
                "purpose": subarg.get("purpose", ""),
                "relationship": subarg.get("relationship", ""),
                "snippets": snippets
            })

        result_arguments.append({
            "id": arg.get("id"),
            "title": arg.get("title", ""),
            "sub_arguments": arg_subargs
        })

    return {
        "standard": {
            "key": standard_key,
            "name": _get_standard_display_name(standard_key),
            "legal_ref": LEGAL_REFS.get(standard_key, "")
        },
        "arguments": result_arguments
    }


# ============================================
# LLM 生成函数
# ============================================

def _build_writing_prompt(context: Dict) -> str:
    """构建写作 Prompt"""
    standard = context.get("standard", {})
    arguments = context.get("arguments", [])

    if not arguments:
        return ""

    # 构建 Argument 和 SubArgument 描述
    args_text = []
    for arg in arguments:
        arg_lines = [f"\n## Argument: {arg['title']}"]

        for subarg in arg.get("sub_arguments", []):
            subarg_lines = [
                f"\n### SubArgument [{subarg['id']}]: {subarg['title']}",
                f"Purpose: {subarg['purpose']}",
                f"Relationship: {subarg['relationship']}",
                "Evidence:"
            ]

            for snip in subarg.get("snippets", []):
                subarg_lines.append(
                    f"  - [{snip['id']}] (Exhibit {snip['exhibit']}, p.{snip['page']}): "
                    f'"{snip["text"][:200]}..."' if len(snip["text"]) > 200 else f'"{snip["text"]}"'
                )

            arg_lines.extend(subarg_lines)

        args_text.append("\n".join(arg_lines))

    return "\n".join(args_text)


# ============================================
# 三步流水线：分拆生成 → 润色整合 → 首尾生成
# ============================================

async def _step1_generate_subargument_body(
    standard: Dict,
    argument_title: str,
    subargument: Dict,
    additional_instructions: str = None
) -> List[Dict]:
    """
    Step 1: 为单个 SubArgument 生成 3-5 句正文。

    每个 SubArgument 独立调用 LLM，保证 100% 覆盖率。

    Returns:
        [{"text": str, "snippet_ids": [...], "exhibit_refs": [...]}]
    """
    # 构建该 SubArgument 的证据文本（给足内容，不过分截断）
    evidence_lines = []
    snippet_ids_list = []
    for snip in subargument.get("snippets", []):
        text = snip["text"][:600] + "..." if len(snip["text"]) > 600 else snip["text"]
        evidence_lines.append(
            f'  SNIPPET {snip["id"]} (Exhibit {snip["exhibit"]}, p.{snip["page"]}):\n    "{text}"'
        )
        snippet_ids_list.append(snip["id"])
    evidence_text = "\n\n".join(evidence_lines) if evidence_lines else "(no evidence provided)"
    snippet_ids_str = ", ".join(f'"{sid}"' for sid in snippet_ids_list)

    system_prompt = """You are a Senior Immigration Attorney at a top-tier law firm drafting an immigration petition letter.

ABSOLUTE RULES:
1. Every fact, date, name, number MUST come from the EVIDENCE snippets. NEVER invent or infer facts.
2. Always write in THIRD PERSON about the Beneficiary ("the Beneficiary", "Mr./Ms. [Name]"). Never use "I" or "we".
3. Do NOT copy snippet text verbatim. Instead, ARGUE: state a legal point, then cite the evidence that supports it.
4. Use direct quotes sparingly — only the most impactful short phrases, embedded naturally in your argument."""

    user_prompt = f"""Draft 2-4 sentences for this sub-argument in a petition letter.

SUB-ARGUMENT: {subargument['title']}
PARENT ARGUMENT: {argument_title}

EVIDENCE SNIPPETS:
{evidence_text}

{f"ADDITIONAL INSTRUCTIONS: {additional_instructions}" if additional_instructions else ""}

WRITING STYLE — Each sentence must follow this pattern:
  [Legal argumentative claim] + [evidence from snippet with Exhibit citation]

  GOOD: "The organization's longstanding commitment to excellence is evidenced by its receipt of [Award Name] on multiple occasions [Exhibit X, p.Y]."
  BAD:  "[Organization] wins [Award]." (raw snippet headline, no argumentation)

  GOOD: "The Beneficiary's formal authority within [Organization] is confirmed by her role as legal representative [Exhibit X, p.Y]."
  BAD:  "I serve as the legal representative of [Organization]." (first person, raw snippet copy)

RULES:
1. Use ONLY facts from the snippets above. Do NOT invent dates, statistics, or names.
2. Each sentence must cite [Exhibit X, p.Y] and reference snippet_id(s). Valid IDs: [{snippet_ids_str}]
3. Embed 1-2 short direct quotes from snippets naturally within sentences (do NOT use block quote format).
4. Professional legal tone, 100% English (translate non-English source text).
5. Write 2-4 sentences — match the evidence available. No filler.

Return JSON:
{{
  "sentences": [
    {{
      "text": "Argumentative sentence with evidence [Exhibit X, p.Y].",
      "snippet_ids": ["{snippet_ids_list[0] if snippet_ids_list else 'snip_xxx'}"],
      "exhibit_refs": ["X-Y"]
    }}
  ]
}}

Return ONLY valid JSON, no markdown."""

    result = await call_llm(
        prompt=user_prompt,
        system_prompt=system_prompt,
        json_schema={},
        temperature=0.3,
        max_tokens=4000
    )

    if "error" in result:
        return []

    sentences = result.get("sentences", [])

    # 校验 snippet_ids：只保留该 SubArgument 实际有的 snippet
    valid_ids = {s["id"] for s in subargument.get("snippets", [])}
    import logging
    _logger = logging.getLogger(__name__)
    for sent in sentences:
        raw_ids = sent.get("snippet_ids", [])
        sent["snippet_ids"] = [sid for sid in raw_ids if sid in valid_ids]
        if raw_ids and not sent["snippet_ids"]:
            _logger.warning(f"Step1 snippet_ids ALL invalid: raw={raw_ids}, valid={valid_ids}")
        sent["exhibit_refs"] = sent.get("exhibit_refs", [])

    return sentences


async def _step1_generate_argument_body(
    standard: Dict,
    argument: Dict,
    exhibit_texts: Dict[str, str],
    additional_instructions: str = None
) -> List[Dict]:
    """
    Step 1 (v3.1): 为整个 Argument 生成 body，LLM 看到完整 OCR 原文。

    写作粒度从 per-SubArgument 提升到 per-Argument：
    - SubArgument 结构作为论证大纲
    - snippet 摘要作为"重点标记"
    - 完整 OCR 页面作为原始素材

    Args:
        standard: {key, name, legal_ref}
        argument: argument dict with sub_arguments (each with snippets)
        exhibit_texts: {exhibit_id: formatted OCR text} from load_exhibit_pages_for_argument
        additional_instructions: optional extra instructions

    Returns:
        [{"subargument_id": str, "sentences": [{"text", "snippet_ids", "exhibit_refs"}]}]
    """
    sub_arguments = argument.get("sub_arguments", [])
    if not sub_arguments:
        return []

    # Build sub-argument outline with snippet pointers
    outline_parts = []
    all_snippet_ids = set()
    for i, subarg in enumerate(sub_arguments, 1):
        lines = [
            f"  {i}. [{subarg['id']}] {subarg.get('title', '')}",
            f"     Purpose: {subarg.get('purpose', '')}",
            f"     Key evidence pointers:"
        ]
        for snip in subarg.get("snippets", []):
            text_preview = snip["text"][:200] + "..." if len(snip["text"]) > 200 else snip["text"]
            lines.append(
                f'       - [{snip["id"]}] Exhibit {snip["exhibit"]}, p.{snip["page"]}: "{text_preview}"'
            )
            all_snippet_ids.add(snip["id"])
        outline_parts.append("\n".join(lines))

    outline_text = "\n\n".join(outline_parts)

    # Build source materials section
    source_parts = []
    for exhibit_id, text in sorted(exhibit_texts.items()):
        source_parts.append(f"--- Exhibit {exhibit_id} ---\n{text}")
    source_text = "\n\n".join(source_parts)

    # Build subargument_id list for JSON example
    subarg_ids = [sa["id"] for sa in sub_arguments]
    subarg_json_example = ",\n    ".join(
        f'{{"subargument_id": "{sid}", "sentences": [{{"text": "...", "snippet_ids": ["..."], "exhibit_refs": ["..."]}}]}}'
        for sid in subarg_ids[:2]
    )
    if len(subarg_ids) > 2:
        subarg_json_example += ",\n    ..."

    system_prompt = """You are a Senior Immigration Attorney at a top-tier law firm drafting an EB-1A petition letter.

ARGUMENTATION METHOD — For each piece of evidence, build a COMPLETE argument chain:
1. FACT: State what the applicant did / what happened (cite Exhibit)
2. AUTHORITY: Prove the organization/award/journal is prestigious — state WHO runs it, WHEN it was founded, and WHY it is recognized (cite Exhibit)
3. RIGOR: Describe the evaluation/selection process — how are candidates nominated, who reviews, what criteria are used (cite Exhibit)
4. SCALE/RARITY: Provide numbers — how many applied/competed, how few won, compute percentages when both numerator and denominator are available (cite Exhibit)
5. PEER COMPARISON: Name specific co-recipients, fellow members, or past winners mentioned in the source materials to show the caliber of the peer group (cite Exhibit). Use ONLY names found in source materials.

Not every evidence needs all 5 layers, but the strongest arguments have most of them.

DEFENSIVE ARGUMENTATION: If any evidence could be perceived as a weakness (e.g., a lower prize tier, a regional rather than international scope), proactively address it by contextualizing — explain the award structure, the total number of tiers, and what percentage of candidates reach that tier. Do NOT ignore potential weaknesses; reframe them as strengths using facts from the source materials.

ABSOLUTE RULES:
1. Every fact MUST come from the SOURCE MATERIALS below. NEVER invent facts.
2. Extract ALL relevant numbers, dates, names, and statistics from the source materials.
3. Write in THIRD PERSON about "the Beneficiary".
4. Each sentence must cite [Exhibit X, p.Y].
5. Professional legal argumentative tone, 100% English."""

    user_prompt = f"""Draft the body paragraphs for this argument in a petition letter.

STANDARD: {standard.get('name', '')} ({standard.get('legal_ref', '')})
ARGUMENT: {argument.get('title', '')}

SUB-ARGUMENTS (use as structural outline — write one paragraph per sub-argument):
{outline_text}

=== SOURCE MATERIALS (full text — extract ALL relevant details) ===

{source_text}

=== END SOURCE MATERIALS ===

{f"ADDITIONAL INSTRUCTIONS: {additional_instructions}" if additional_instructions else ""}

INSTRUCTIONS:
- Write one paragraph (3-6 sentences) per Sub-Argument listed above
- The "Key evidence pointers" highlight the most important evidence, but you SHOULD
  also extract additional supporting details from the source materials (numbers,
  evaluation criteria, peer names, organization credentials, etc.)
- Build argument chains: fact → authority → rigor → scale → peer comparison
- Every sentence must cite [Exhibit X, p.Y]
- Use exact numbers and names from the source materials
- Professional legal tone, 100% English (translate any non-English source text)
- Do NOT copy source text verbatim — ARGUE: state a legal point, then cite supporting evidence

Return JSON:
{{
  "sub_argument_paragraphs": [
    {subarg_json_example}
  ]
}}

CRITICAL: Return ALL {len(subarg_ids)} sub-argument paragraphs. subargument_id values MUST be exactly: {subarg_ids}
Return ONLY valid JSON, no markdown."""

    # Token budget: system ~800 + outline ~1500 + source ~15000-20000 + output ~8000 = well within 128K
    result = await call_llm(
        prompt=user_prompt,
        system_prompt=system_prompt,
        json_schema={},
        temperature=0.3,
        max_tokens=8000
    )

    if "error" in result:
        logger.error(f"Step1 (argument-level) LLM error: {result['error']}")
        return []

    paragraphs = result.get("sub_argument_paragraphs", [])

    # Validate and normalize output
    valid_subarg_ids = {sa["id"] for sa in sub_arguments}
    # Build per-subarg snippet id sets for validation
    subarg_snippet_map = {}
    for sa in sub_arguments:
        sa_snip_ids = {s["id"] for s in sa.get("snippets", [])}
        subarg_snippet_map[sa["id"]] = sa_snip_ids

    validated_paragraphs = []
    for para in paragraphs:
        subarg_id = para.get("subargument_id", "")
        if subarg_id not in valid_subarg_ids:
            logger.warning(f"Step1 returned unknown subargument_id: {subarg_id}")
            continue

        sentences = para.get("sentences", [])
        for sent in sentences:
            # Keep all snippet_ids from this argument (not just this subargument)
            # since the LLM has visibility of all evidence now
            raw_ids = sent.get("snippet_ids", [])
            sent["snippet_ids"] = [sid for sid in raw_ids if sid in all_snippet_ids]
            sent["exhibit_refs"] = sent.get("exhibit_refs", [])

        validated_paragraphs.append({
            "subargument_id": subarg_id,
            "title": next(
                (sa.get("title", "") for sa in sub_arguments if sa["id"] == subarg_id),
                ""
            ),
            "sentences": sentences
        })

    # Check for missing subarguments — warn but don't fail
    returned_ids = {p["subargument_id"] for p in validated_paragraphs}
    missing = valid_subarg_ids - returned_ids
    if missing:
        logger.warning(f"Step1 missing subarguments: {missing}")

    return validated_paragraphs


async def _step2_polish_argument(
    standard: Dict,
    argument: Dict,
    subargument_bodies: List[Dict]
) -> List[Dict]:
    """
    Step 2: 将同一 Argument 下多个 SubArgument 的段落润色整合。

    LLM 添加过渡句、调整语序，但必须保持 SubArgument 分组结构和引用。

    Args:
        subargument_bodies: [{"subargument_id": str, "sentences": [...]}]

    Returns:
        润色后的 subargument_bodies（同结构）
    """
    if len(subargument_bodies) <= 1:
        # 只有一个 SubArgument，不需要润色过渡
        return subargument_bodies

    # 构建输入文本（包含 snippet_ids 以便 LLM 知道它们）
    input_blocks = []
    subarg_ids = []
    for body in subargument_bodies:
        subarg_id = body["subargument_id"]
        subarg_ids.append(subarg_id)
        title = body.get("title", "")
        sentences_text = "\n".join(
            f'    - "{s["text"]}"' for s in body["sentences"]
        )
        input_blocks.append(f'  SubArgument [{subarg_id}] "{title}":\n{sentences_text}')

    input_text = "\n\n".join(input_blocks)

    system_prompt = """You are a Senior Immigration Attorney polishing a petition letter section for coherence.
Your task is to add smooth transitions between sub-argument paragraphs while preserving ALL factual content, evidence citations, and direct quotes exactly as written."""

    user_prompt = f"""Polish the following sub-argument paragraphs for the "{standard.get('name', '')}" section.

CURRENT TEXT (grouped by SubArgument):

{input_text}

INSTRUCTIONS:
1. Add transition phrases BETWEEN SubArgument groups ("Furthermore,", "In addition to the above,", "Moreover,", etc.)
2. PRESERVE all [Exhibit X, p.Y] citations and direct quotes EXACTLY — do not change any facts, dates, names, or numbers
3. MUST keep the same SubArgument grouping — do NOT merge or split SubArguments
4. MUST keep the same number of sentences per SubArgument group
5. Only change: word order, transition words, connective phrases. Do NOT add new facts.
6. 100% English output

Return JSON with the SAME structure:
{{
  "subargument_paragraphs": [
    {{
      "subargument_id": "{subarg_ids[0]}",
      "sentences": [
        {{"text": "polished sentence...", "snippet_ids": ["snip_xxx"], "exhibit_refs": ["X-Y"]}}
      ]
    }},
    {{
      "subargument_id": "{subarg_ids[1] if len(subarg_ids) > 1 else 'subarg-yyy'}",
      "sentences": [
        {{"text": "Furthermore, polished sentence...", "snippet_ids": ["snip_yyy"], "exhibit_refs": ["X-Y"]}}
      ]
    }}
  ]
}}

CRITICAL: Return ALL {len(subarg_ids)} SubArgument groups. Do NOT skip any.
Return ONLY valid JSON."""

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            json_schema={},
            temperature=0.3,
            max_tokens=8192
        )

        polished = result.get("subargument_paragraphs", [])

        # 验证润色结果：如果 SubArgument 数量不对，回退到原始版本
        if len(polished) != len(subargument_bodies):
            import logging
            logging.getLogger(__name__).warning(
                f"Polish returned {len(polished)} subargs, expected {len(subargument_bodies)}. Using originals."
            )
            return subargument_bodies

        # 将原始的 subargument_id、title、snippet_ids、exhibit_refs 覆盖回去（不信任 LLM）
        for i, body in enumerate(polished):
            body["subargument_id"] = subargument_bodies[i]["subargument_id"]
            body["title"] = subargument_bodies[i].get("title", "")
            # 恢复原始 snippet_ids 和 exhibit_refs（按句子索引一一对应）
            original_sents = subargument_bodies[i].get("sentences", [])
            polished_sents = body.get("sentences", [])
            for j, psent in enumerate(polished_sents):
                if j < len(original_sents):
                    psent["snippet_ids"] = original_sents[j].get("snippet_ids", [])
                    psent["exhibit_refs"] = original_sents[j].get("exhibit_refs", [])

        return polished

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Polish failed, using originals: {e}")
        return subargument_bodies


async def _step3_generate_section_frame(
    standard: Dict,
    arguments: List[Dict]
) -> Dict:
    """
    Step 3: 生成段落的 opening 和 closing 句子。

    看到所有 Argument + SubArgument 的标题来写全局性的首尾。

    Returns:
        {"opening_text": str, "closing_text": str}
    """
    # 构建 Argument/SubArgument 概要
    summary_lines = []
    for arg in arguments:
        summary_lines.append(f"  Argument: {arg.get('title', '')}")
        for sa in arg.get("sub_arguments", []):
            summary_lines.append(f"    - {sa.get('title', '')}")
    summary_text = "\n".join(summary_lines)

    system_prompt = """You are a Senior Immigration Attorney writing an EB-1A petition letter."""

    user_prompt = f"""Write an opening sentence and a closing sentence for the "{standard.get('name', '')}" ({standard.get('legal_ref', '')}) section of a petition letter.

The section contains these arguments and sub-arguments:
{summary_text}

OPENING SENTENCE:
- MUST explicitly cite the regulation: "{standard.get('legal_ref', '')}"
- Briefly introduce the scope — do NOT include specific facts, dates, or names (the body handles that)
- Keep it to ONE concise sentence

CLOSING SENTENCE:
- Summarize the argument scope in ONE sentence
- Confident, conclusive legal language
- Do NOT introduce any new facts not covered in the body

Return JSON:
{{
  "opening_text": "The Beneficiary satisfies {standard.get('legal_ref', '')} by demonstrating...",
  "closing_text": "In sum, the foregoing evidence clearly establishes..."
}}

100% English. Return ONLY valid JSON."""

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            json_schema={},
            temperature=0.4,
            max_tokens=1000
        )
        return {
            "opening_text": result.get("opening_text", ""),
            "closing_text": result.get("closing_text", "")
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Section frame generation failed: {e}")
        legal_ref = standard.get('legal_ref', '')
        name = standard.get('name', '')
        return {
            "opening_text": f"The Beneficiary satisfies {legal_ref} ({name}) as demonstrated by the following evidence.",
            "closing_text": "In sum, the foregoing evidence clearly establishes that the Beneficiary meets this criterion."
        }


def _contains_non_ascii(text: str) -> bool:
    """Check if text contains non-ASCII characters (Chinese, etc.)"""
    if not text:
        return False
    return any(ord(char) > 127 for char in text)


# Note: Removed hardcoded CHINESE_TO_ENGLISH mapping to avoid overfitting.
# The system relies on:
# 1. Prompt Rule 8 requiring 100% English output
# 2. LLM translation as fallback (via _translate_to_english)
# 3. _remove_remaining_chinese() as final safety net


def _remove_remaining_chinese(text: str) -> str:
    """Remove any remaining Chinese characters after known replacements."""
    if not text:
        return text

    # Remove characters that are clearly Chinese (CJK unified ideographs range)
    # Range: \u4e00-\u9fff covers most common Chinese characters
    cleaned = re.sub(r'[\u4e00-\u9fff]+', '', text)

    # Clean up any leftover empty parentheses
    cleaned = re.sub(r'\(\s*\)', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)  # Normalize spaces

    return cleaned.strip()


async def _translate_to_english(text: str) -> str:
    """
    Translate non-English text to English using LLM.
    Generic solution - no hardcoded mappings.
    """
    if not _contains_non_ascii(text):
        return text

    # Try LLM translation
    try:
        prompt = f"""Translate the following text to English.
IMPORTANT:
1. Keep all exhibit citations (e.g., [Exhibit C-2, p.3]) exactly as they are
2. Keep all formatting including block quotes (> "...")
3. Translate ONLY the non-English text to English
4. Do NOT add any explanations, just return the translated text

Text to translate:
{text}"""

        llm_result = await call_llm_text(
            prompt=prompt,
            system_prompt="You are a professional translator. Translate to English while preserving legal document formatting.",
            temperature=0.3,
            max_tokens=2000
        )

        if llm_result and not _contains_non_ascii(llm_result):
            return llm_result.strip()
    except Exception as e:
        print(f"[ensure_english] LLM translation failed: {e}")

    # Fallback: Remove remaining Chinese characters
    return _remove_remaining_chinese(text)


async def ensure_english_output(llm_output: Dict) -> Dict:
    """
    Post-process LLM output to ensure 100% English.
    Translates any remaining non-English text while preserving structure.
    """
    if not llm_output:
        return llm_output

    # Check and translate opening sentence
    if "opening_sentence" in llm_output:
        opening = llm_output["opening_sentence"]
        if isinstance(opening, dict) and "text" in opening:
            if _contains_non_ascii(opening["text"]):
                opening["text"] = await _translate_to_english(opening["text"])

    # Check and translate subargument paragraphs
    if "subargument_paragraphs" in llm_output:
        for para in llm_output["subargument_paragraphs"]:
            if "sentences" in para:
                for sentence in para["sentences"]:
                    if "text" in sentence and _contains_non_ascii(sentence["text"]):
                        sentence["text"] = await _translate_to_english(sentence["text"])

    # Check and translate closing sentence
    if "closing_sentence" in llm_output:
        closing = llm_output["closing_sentence"]
        if isinstance(closing, dict) and "text" in closing:
            if _contains_non_ascii(closing["text"]):
                closing["text"] = await _translate_to_english(closing["text"])

    return llm_output


# ============================================
# 验证和修正函数
# ============================================

def validate_provenance(
    llm_output: Dict,
    context: Dict
) -> Dict:
    """
    验证 LLM 输出的溯源信息

    Returns:
        {
            "is_valid": bool,
            "errors": [...],
            "warnings": [...],
            "fixed_output": {...}
        }
    """
    errors = []
    warnings = []

    # 构建有效的 snippet_id 集合（支持新旧两种格式）
    valid_snippet_ids = set()
    subarg_snippet_map = {}  # subargument_id -> set of snippet_ids
    original_to_new = {}  # old_id -> new_id 映射

    for arg in context.get("arguments", []):
        for subarg in arg.get("sub_arguments", []):
            subarg_id = subarg["id"]
            snippet_ids = set()
            for s in subarg.get("snippets", []):
                new_id = s["id"]
                snippet_ids.add(new_id)
                # 如果有原始 ID，也添加映射
                if s.get("original_id") and s["original_id"] != new_id:
                    original_to_new[s["original_id"]] = new_id
                    valid_snippet_ids.add(s["original_id"])

            subarg_snippet_map[subarg_id] = snippet_ids
            valid_snippet_ids.update(snippet_ids)

    # 验证 subargument_paragraphs
    fixed_paragraphs = []
    for para in llm_output.get("subargument_paragraphs", []):
        subarg_id = para.get("subargument_id", "")

        # 检查 subargument_id 是否有效
        if subarg_id not in subarg_snippet_map:
            warnings.append(f"Unknown subargument_id: {subarg_id}")
            continue

        valid_for_subarg = subarg_snippet_map.get(subarg_id, set())
        fixed_sentences = []

        for sent in para.get("sentences", []):
            snippet_ids = sent.get("snippet_ids", [])

            # 标准化 snippet_ids（将旧格式转换为新格式）
            normalized_ids = []
            for sid in snippet_ids:
                if sid in original_to_new:
                    normalized_ids.append(original_to_new[sid])
                else:
                    normalized_ids.append(sid)

            # 过滤无效的 snippet_ids
            valid_ids = [sid for sid in normalized_ids if sid in valid_snippet_ids]
            invalid_ids = [sid for sid in normalized_ids if sid not in valid_snippet_ids]

            if invalid_ids:
                warnings.append(f"Removed invalid snippet_ids: {invalid_ids}")

            # 检查 snippet 是否属于该 SubArgument
            out_of_scope = [sid for sid in valid_ids if sid not in valid_for_subarg]
            if out_of_scope:
                warnings.append(
                    f"Snippet {out_of_scope} referenced but not in SubArgument {subarg_id}"
                )

            fixed_sentences.append({
                "text": sent.get("text", ""),
                "snippet_ids": valid_ids,
                "exhibit_refs": sent.get("exhibit_refs", [])
            })

        fixed_paragraphs.append({
            "subargument_id": subarg_id,
            "sentences": fixed_sentences
        })

    # 构建修正后的输出
    fixed_output = {
        "argument_id": llm_output.get("argument_id", ""),
        "opening_sentence": llm_output.get("opening_sentence", {"text": "", "snippet_ids": []}),
        "subargument_paragraphs": fixed_paragraphs,
        "closing_sentence": llm_output.get("closing_sentence", {"text": ""})
    }

    is_valid = len(errors) == 0

    return {
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "fixed_output": fixed_output
    }


def build_provenance_index(
    validated_output: Dict,
    context: Dict
) -> Dict:
    """
    构建溯源索引

    Returns:
        {
            "by_subargument": {"subarg-xxx": [0, 1, 2], ...},
            "by_argument": {"arg-xxx": [0, 1, 2, 3], ...},
            "by_snippet": {"snp_xxx": [0, 2], ...}
        }
    """
    by_subargument = defaultdict(list)
    by_argument = defaultdict(list)
    by_snippet = defaultdict(list)

    argument_id = validated_output.get("argument_id", "")
    sentence_index = 0

    # Opening sentence
    opening = validated_output.get("opening_sentence", {})
    if opening.get("text"):
        by_argument[argument_id].append(sentence_index)
        sentence_index += 1

    # SubArgument paragraphs
    for para in validated_output.get("subargument_paragraphs", []):
        subarg_id = para.get("subargument_id", "")

        for sent in para.get("sentences", []):
            by_subargument[subarg_id].append(sentence_index)
            by_argument[argument_id].append(sentence_index)

            for snip_id in sent.get("snippet_ids", []):
                by_snippet[snip_id].append(sentence_index)

            sentence_index += 1

    # Closing sentence
    closing = validated_output.get("closing_sentence", {})
    if closing.get("text"):
        by_argument[argument_id].append(sentence_index)

    return {
        "by_subargument": dict(by_subargument),
        "by_argument": dict(by_argument),
        "by_snippet": dict(by_snippet)
    }


def flatten_sentences(
    validated_output: Dict,
    context: Dict
) -> List[Dict]:
    """
    将结构化输出扁平化为句子列表

    Returns:
        [
            {
                "text": str,
                "snippet_ids": [...],
                "subargument_id": str,
                "argument_id": str,
                "exhibit_refs": [...],
                "sentence_type": "opening" | "body" | "closing"
            }
        ]
    """
    argument_id = validated_output.get("argument_id", "")
    sentences = []

    # Opening sentence
    opening = validated_output.get("opening_sentence", {})
    if opening.get("text"):
        sentences.append({
            "text": opening.get("text", ""),
            "snippet_ids": opening.get("snippet_ids", []),
            "subargument_id": None,
            "argument_id": argument_id,
            "exhibit_refs": [],
            "sentence_type": "opening"
        })

    # SubArgument paragraphs
    for para in validated_output.get("subargument_paragraphs", []):
        subarg_id = para.get("subargument_id", "")

        for sent in para.get("sentences", []):
            sentences.append({
                "text": sent.get("text", ""),
                "snippet_ids": sent.get("snippet_ids", []),
                "subargument_id": subarg_id,
                "argument_id": argument_id,
                "exhibit_refs": sent.get("exhibit_refs", []),
                "sentence_type": "body"
            })

    # Closing sentence
    closing = validated_output.get("closing_sentence", {})
    if closing.get("text"):
        sentences.append({
            "text": closing.get("text", ""),
            "snippet_ids": [],
            "subargument_id": None,
            "argument_id": argument_id,
            "exhibit_refs": [],
            "sentence_type": "closing"
        })

    return sentences


# ============================================
# 主入口函数
# ============================================

def _build_provenance_from_sentences(sentences: List[Dict]) -> Dict:
    """
    从扁平句子列表构建溯源索引。

    与 build_provenance_index() 不同，此函数直接从句子列表读取
    argument_id（支持多 Argument 场景），不依赖单一顶层 argument_id。
    """
    by_subargument = defaultdict(list)
    by_argument = defaultdict(list)
    by_snippet = defaultdict(list)

    for idx, sent in enumerate(sentences):
        subarg_id = sent.get("subargument_id")
        if subarg_id:
            by_subargument[subarg_id].append(idx)

        arg_id = sent.get("argument_id")
        if arg_id:
            by_argument[arg_id].append(idx)

        for snip_id in sent.get("snippet_ids", []):
            by_snippet[snip_id].append(idx)

    return {
        "by_subargument": dict(by_subargument),
        "by_argument": dict(by_argument),
        "by_snippet": dict(by_snippet)
    }


async def write_petition_section_v3(
    project_id: str,
    standard_key: str,
    argument_ids: List[str] = None,
    subargument_ids: List[str] = None,
    additional_instructions: str = None
) -> Dict:
    """
    V3.1 版本的写作入口 — OCR 回溯三步流水线

    Step 1: 逐 Argument 生成正文（LLM 看到完整 OCR 原文 + SubArgument 大纲）
    Step 2: 逐 Argument 润色整合（加过渡句，保持连贯性）
    Step 3: 生成全局 Opening/Closing（引用法规 + 总结）

    Args:
        project_id: 项目 ID
        standard_key: 标准 key (如 "membership", "leading_role")
        argument_ids: 可选，指定要生成的 Argument IDs
        subargument_ids: 可选，指定要生成的 SubArgument IDs（用于局部重新生成）
        additional_instructions: 可选，额外指令
    """
    # 0. 加载上下文
    context = load_subargument_context(project_id, standard_key, argument_ids, subargument_ids)

    if not context.get("arguments"):
        return {
            "success": False,
            "error": f"No arguments found for standard: {standard_key}",
            "section": standard_key,
            "paragraph_text": "",
            "sentences": []
        }

    all_arguments = context["arguments"]
    standard = context["standard"]
    all_warnings = []

    # Build snippet map for OCR loading
    snippet_map = {}
    for arg in all_arguments:
        for sa in arg.get("sub_arguments", []):
            for snip in sa.get("snippets", []):
                snippet_map[snip["id"]] = snip

    # ========== Step 1: 逐 Argument 生成正文（OCR 回溯） ==========
    per_argument_bodies: List[List[Dict]] = []  # [[{subargument_id, title, sentences}]]
    per_argument_refs: List[Dict] = []

    for argument in all_arguments:
        arg_id = argument.get("id", "")
        sub_arguments = argument.get("sub_arguments", [])

        if not sub_arguments:
            all_warnings.append(f"Skipped argument {arg_id}: no sub_arguments")
            continue

        # Load OCR pages for all exhibits referenced by this argument
        exhibit_texts = load_exhibit_pages_for_argument(project_id, argument, snippet_map)
        logger.info(
            f"Step1: Generating body for argument {arg_id} "
            f"({len(sub_arguments)} subargs, {len(exhibit_texts)} exhibits loaded)"
        )

        # Generate body at argument level with full OCR context
        arg_bodies = await _step1_generate_argument_body(
            standard=standard,
            argument=argument,
            exhibit_texts=exhibit_texts,
            additional_instructions=additional_instructions
        )

        if not arg_bodies:
            all_warnings.append(f"No content generated for argument {arg_id}")
            continue

        # 确保英文
        for body in arg_bodies:
            for sent in body.get("sentences", []):
                if _contains_non_ascii(sent.get("text", "")):
                    sent["text"] = await _translate_to_english(sent["text"])
                    if _contains_non_ascii(sent["text"]):
                        sent["text"] = _remove_remaining_chinese(sent["text"])

        per_argument_bodies.append(arg_bodies)
        per_argument_refs.append(argument)

    if not per_argument_bodies:
        return {
            "success": False,
            "error": f"No content generated for standard: {standard_key}",
            "section": standard_key,
            "paragraph_text": "",
            "sentences": []
        }

    # ========== Step 2: 逐 Argument 润色整合 ==========
    polished_bodies: List[List[Dict]] = []

    for i, arg_bodies in enumerate(per_argument_bodies):
        argument_ref = per_argument_refs[i]
        logger.info(f"Step2: Polishing argument group {i+1}/{len(per_argument_bodies)} ({len(arg_bodies)} subargs, arg={argument_ref.get('id', '')})")

        polished = await _step2_polish_argument(
            standard=standard,
            argument=argument_ref,
            subargument_bodies=arg_bodies
        )

        # 确保润色后的文本也是英文
        for body in polished:
            for sent in body.get("sentences", []):
                if _contains_non_ascii(sent.get("text", "")):
                    sent["text"] = _remove_remaining_chinese(sent["text"])

        polished_bodies.append(polished)

    # ========== Step 3: 生成 Opening/Closing ==========
    logger.info("Step3: Generating opening/closing")
    frame = await _step3_generate_section_frame(
        standard=standard,
        arguments=all_arguments
    )

    # 确保英文
    for key in ("opening_text", "closing_text"):
        if _contains_non_ascii(frame.get(key, "")):
            frame[key] = _remove_remaining_chinese(frame[key])

    # ========== 组装最终句子列表 ==========
    all_sentences = []

    # Opening
    all_sentences.append({
        "text": frame["opening_text"],
        "snippet_ids": [],
        "subargument_id": None,
        "argument_id": all_arguments[0].get("id", ""),
        "exhibit_refs": [],
        "sentence_type": "opening"
    })

    # Body: 按 Argument → SubArgument 顺序
    for arg_idx, arg_polished in enumerate(polished_bodies):
        arg_id = per_argument_refs[arg_idx].get("id", "") if arg_idx < len(per_argument_refs) else ""

        for body in arg_polished:
            subarg_id = body["subargument_id"]
            for sent in body.get("sentences", []):
                all_sentences.append({
                    "text": sent.get("text", ""),
                    "snippet_ids": sent.get("snippet_ids", []),
                    "subargument_id": subarg_id,
                    "argument_id": arg_id,
                    "exhibit_refs": sent.get("exhibit_refs", []),
                    "sentence_type": "body"
                })

    # Closing
    all_sentences.append({
        "text": frame["closing_text"],
        "snippet_ids": [],
        "subargument_id": None,
        "argument_id": all_arguments[-1].get("id", ""),
        "exhibit_refs": [],
        "sentence_type": "closing"
    })

    # 溯源校验：重新校验 snippet_ids 合法性
    valid_snippet_ids = set()
    for arg in all_arguments:
        for sa in arg.get("sub_arguments", []):
            for snip in sa.get("snippets", []):
                valid_snippet_ids.add(snip["id"])

    for sent in all_sentences:
        original_ids = sent.get("snippet_ids", [])
        valid_ids = [sid for sid in original_ids if sid in valid_snippet_ids]
        if len(valid_ids) != len(original_ids):
            all_warnings.append(f"Removed invalid snippet_ids from sentence")
        sent["snippet_ids"] = valid_ids

    # 构建溯源索引
    provenance_index = _build_provenance_from_sentences(all_sentences)

    # 组装段落文本
    paragraph_text = " ".join(s["text"] for s in all_sentences)

    # 统计
    total_sentences = len(all_sentences)
    traced_sentences = sum(
        1 for s in all_sentences
        if s.get("snippet_ids") or s.get("subargument_id")
    )

    return {
        "success": True,
        "section": standard_key,
        "paragraph_text": paragraph_text,
        "sentences": all_sentences,
        "provenance_index": provenance_index,
        "validation": {
            "total_sentences": total_sentences,
            "traced_sentences": traced_sentences,
            "warnings": all_warnings
        }
    }


# ============================================
# 存储函数
# ============================================

def save_writing_v3(
    project_id: str,
    section: str,
    result: Dict
) -> str:
    """保存 V3 写作结果"""
    project_dir = PROJECTS_DIR / project_id
    writing_dir = project_dir / "writing_v3"
    writing_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    version_id = timestamp.strftime("%Y%m%d_%H%M%S")

    data = {
        "version_id": version_id,
        "timestamp": timestamp.isoformat(),
        **result
    }

    filename = f"writing_{section}_{version_id}.json"
    with open(writing_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return version_id


def load_latest_writing_v3(
    project_id: str,
    section: str
) -> Optional[Dict]:
    """加载最新的 V3 写作结果"""
    writing_dir = PROJECTS_DIR / project_id / "writing_v3"
    if not writing_dir.exists():
        return None

    files = sorted(writing_dir.glob(f"writing_{section}_*.json"), reverse=True)
    if not files:
        return None

    with open(files[0], 'r', encoding='utf-8') as f:
        return json.load(f)


# ============================================
# SubArgument 变更级联函数
# ============================================

def remove_subargument_from_writing(
    project_id: str, subargument_id: str, standard_key: str
) -> Dict:
    """
    从 writing_v3 文件中移除 SubArgument 的句子，重建索引，保存新版本。

    Returns:
        {
          "changed": bool,
          "removed_indices": [int],
          "new_sentences": [...],
          "new_paragraph_text": str
        }
    """
    existing = load_latest_writing_v3(project_id, standard_key)
    if not existing:
        return {"changed": False, "removed_indices": [], "new_sentences": [], "new_paragraph_text": ""}

    sentences = existing.get("sentences", [])
    if not sentences:
        return {"changed": False, "removed_indices": [], "new_sentences": [], "new_paragraph_text": ""}

    # Find indices of sentences belonging to this SubArgument
    removed_indices = [
        i for i, s in enumerate(sentences)
        if s.get("subargument_id") == subargument_id
    ]

    if not removed_indices:
        return {"changed": False, "removed_indices": [], "new_sentences": sentences, "new_paragraph_text": existing.get("paragraph_text", "")}

    # Filter out removed sentences
    new_sentences = [s for i, s in enumerate(sentences) if i not in removed_indices]

    # Rebuild provenance_index
    new_provenance = {"by_subargument": {}, "by_argument": {}, "by_snippet": {}}
    for idx, sent in enumerate(new_sentences):
        subarg_id = sent.get("subargument_id")
        if subarg_id:
            new_provenance["by_subargument"].setdefault(subarg_id, []).append(idx)
        arg_id = sent.get("argument_id")
        if arg_id:
            new_provenance["by_argument"].setdefault(arg_id, []).append(idx)
        for snip_id in sent.get("snippet_ids", []):
            new_provenance["by_snippet"].setdefault(snip_id, []).append(idx)

    # Rebuild paragraph text
    new_paragraph_text = " ".join(s["text"] for s in new_sentences)

    # Rebuild validation
    total = len(new_sentences)
    traced = sum(1 for s in new_sentences if s.get("snippet_ids") or s.get("subargument_id"))

    # Build updated result for saving
    updated_result = {
        "section": standard_key,
        "paragraph_text": new_paragraph_text,
        "sentences": new_sentences,
        "provenance_index": new_provenance,
        "validation": {
            "total_sentences": total,
            "traced_sentences": traced,
            "warnings": []
        }
    }

    # Save new version
    save_writing_v3(project_id, standard_key, updated_result)

    return {
        "changed": True,
        "removed_indices": removed_indices,
        "new_sentences": new_sentences,
        "new_paragraph_text": new_paragraph_text
    }


async def analyze_change_impact(
    project_id: str, standard_key: str,
    change_type: str,  # "deletion" | "addition"
    affected_subargument_id: str,
    affected_title: str = ""
) -> Dict:
    """
    分析 SubArgument 变更对整段文章的间接影响。

    调用 LLM，传入当前文章全文 + 变更描述，
    让 LLM 识别哪些句子需要调整。

    Returns:
        {
          "suggestions": [
            {
              "sentence_index": 0,
              "original_text": "...",
              "suggested_text": "...",
              "reason": "..."
            }
          ]
        }
    """
    existing = load_latest_writing_v3(project_id, standard_key)
    if not existing:
        return {"suggestions": []}

    sentences = existing.get("sentences", [])
    if not sentences:
        return {"suggestions": []}

    # Build indexed text for LLM
    indexed_lines = []
    for i, s in enumerate(sentences):
        stype = s.get("sentence_type", "body")
        indexed_lines.append(f"[{i}] ({stype}) {s['text']}")
    indexed_text = "\n".join(indexed_lines)

    action = "deleted from" if change_type == "deletion" else "added to"

    system_prompt = """You are a legal document editor. Analyze how a structural change to a petition letter section affects the remaining text. Return ONLY valid JSON."""

    user_prompt = f"""A sub-argument was just {action} this petition letter section.

CURRENT TEXT (after mechanical {change_type}):
{indexed_text}

CHANGE DESCRIPTION:
- {change_type.capitalize()}d SubArgument: "{affected_title}"
- SubArgument ID: {affected_subargument_id}

TASK: Identify sentences that need adjustment due to this change.
Check for:
1. Opening paragraph references to deleted content (e.g., count changes like "three aspects" → "two aspects")
2. Closing paragraph summaries that reference removed points
3. Transition sentences ("Furthermore...", "In addition...") that now dangle
4. Cross-references to removed exhibits

Return JSON:
{{
  "suggestions": [
    {{
      "sentence_index": 0,
      "original_text": "exact current text",
      "suggested_text": "revised text",
      "reason": "brief explanation"
    }}
  ]
}}
Only return suggestions where changes are actually needed. Return empty array if no changes needed."""

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            json_schema={},
            temperature=0.3,
            max_tokens=2000
        )

        suggestions = result.get("suggestions", [])

        # Validate suggestion indices
        valid_suggestions = []
        for s in suggestions:
            idx = s.get("sentence_index")
            if isinstance(idx, int) and 0 <= idx < len(sentences):
                valid_suggestions.append(s)

        return {"suggestions": valid_suggestions}

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"analyze_change_impact failed: {e}")
        return {"suggestions": []}


# ============================================
# AI 辅助编辑函数
# ============================================

async def edit_text_with_instruction(
    project_id: str,
    original_text: str,
    instruction: str,
    conversation_history: List[Dict] = None
) -> Dict:
    """
    使用 AI 根据指令编辑文本

    支持多轮对话，根据用户指令修改选中的文本。

    Args:
        project_id: 项目 ID
        original_text: 原始文本
        instruction: 用户编辑指令
        conversation_history: 对话历史 [{"role": str, "content": str}]

    Returns:
        {
            "revised_text": str,
            "explanation": str
        }
    """
    # 构建对话上下文
    history_text = ""
    if conversation_history:
        for msg in conversation_history:
            role = "用户" if msg["role"] == "user" else "助手"
            history_text += f"\n{role}: {msg['content']}"

    system_prompt = """You are an expert legal writing editor specializing in EB-1A immigration petitions.
Your task is to revise the provided text according to the user's instructions while:
1. Maintaining professional legal tone
2. Preserving factual accuracy and evidence citations
3. Keeping the revised text similar in length unless instructed otherwise
4. Ensuring proper grammar and clarity"""

    user_prompt = f"""ORIGINAL TEXT:
"{original_text}"

{f"CONVERSATION HISTORY:{history_text}" if history_text else ""}

CURRENT INSTRUCTION: {instruction}

Please revise the text according to the instruction. Return a JSON object:
{{
    "revised_text": "the revised text",
    "explanation": "brief explanation of changes made"
}}

Return ONLY valid JSON, no markdown or extra text."""

    result = await call_llm(
        prompt=user_prompt,
        system_prompt=system_prompt,
        json_schema={},
        temperature=0.3,
        max_tokens=2000
    )

    if "error" in result:
        return {
            "revised_text": original_text,
            "explanation": f"Error: {result.get('error')}"
        }

    return {
        "revised_text": result.get("revised_text", original_text),
        "explanation": result.get("explanation", "")
    }
