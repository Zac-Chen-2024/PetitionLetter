"""
Petition Writer V3 - SubArgument 感知的写作服务

核心改进：
1. 基于 SubArgument 结构生成内容（而非直接从 Snippet）
2. 输出包含完整溯源链：句子 → SubArgument → Argument → Standard
3. 使用 DeepSeek 生成，增强后端验证

数据流：
Standard → Arguments → SubArguments → Snippets
    ↓
LLM 按 SubArgument 结构生成
    ↓
输出：{text, snippet_ids, subargument_id, argument_id, exhibit_refs}[]
"""

import json
from typing import List, Dict, Optional, Any
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from .llm_client import call_deepseek, call_deepseek_text
from .snippet_registry import load_registry
import re


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
    argument_ids: List[str] = None
) -> Dict:
    """
    加载用于写作的 SubArgument 上下文

    Args:
        project_id: 项目 ID
        standard_key: 标准 key (如 "membership", "leading_role")
        argument_ids: 可选，指定要生成的 Argument IDs

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
            "name": EB1A_STANDARDS.get(standard_key, standard_key),
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


async def generate_structured_paragraph(
    context: Dict,
    additional_instructions: str = None
) -> Dict:
    """
    基于 SubArgument 结构生成段落

    使用一步生成策略，要求 LLM 同时输出内容和溯源信息。
    DeepSeek 不支持 strict schema，需要在 Prompt 中强调格式。

    Returns:
        {
            "argument_id": str,
            "opening_sentence": {"text": str, "snippet_ids": []},
            "subargument_paragraphs": [
                {
                    "subargument_id": str,
                    "sentences": [
                        {"text": str, "snippet_ids": [...], "exhibit_refs": [...]}
                    ]
                }
            ],
            "closing_sentence": {"text": str}
        }
    """
    standard = context.get("standard", {})
    arguments = context.get("arguments", [])

    if not arguments:
        return {"error": "No arguments provided"}

    # 目前只处理第一个 Argument（后续可扩展为多个）
    argument = arguments[0]
    evidence_context = _build_writing_prompt(context)

    system_prompt = """You are a Senior Immigration Attorney at a top-tier law firm writing an EB-1A petition letter.
You write persuasive, well-structured legal arguments with precise evidence citations.
Your writing follows professional legal drafting conventions with rich detail and compelling narrative."""

    user_prompt = f"""Write a comprehensive paragraph for the "{standard.get('name', '')}" criterion ({standard.get('legal_ref', '')}).

EVIDENCE STRUCTURE:
{evidence_context}

WRITING REQUIREMENTS:

1. OPENING SENTENCE (CRITICAL):
   - MUST explicitly cite the regulation: "{standard.get('legal_ref', '')}"
   - State the main legal conclusion clearly
   - Example: "The Beneficiary satisfies {standard.get('legal_ref', '')} by demonstrating..."

2. FOR EACH SubArgument, write 3-5 RICH sentences that:
   - Provide CONTEXT and BACKGROUND (organization history, significance, industry standing)
   - Include SPECIFIC EVIDENCE with direct citations
   - When evidence contains important testimony or official language, use BLOCK QUOTES:
     > "[Exact quote from the document]" [Exhibit X, p.Y]
   - Use COMPARATIVE ARGUMENTS when relevant ("The Association's membership includes [other distinguished person] who [achievement]...")
   - Build LAYERED ARGUMENTS ("Not only... but also... Moreover...")
   - Reference exhibits naturally with page numbers: [Exhibit C-2, p.3]

3. CLOSING SENTENCE:
   - Reinforce why this clearly meets the legal standard
   - Use confident, conclusive language

4. ADVANCED TECHNIQUES:
   - Add organizational/media BACKGROUND: founding year, circulation, awards received
   - Include NUMERICAL EVIDENCE: membership numbers, circulation figures, years of operation
   - Use AUTHORITY ENDORSEMENTS: "reviewed and approved by [Title] [Name]"
   - Employ COMPARATIVE EVIDENCE: other notable members, industry benchmarks

{f"ADDITIONAL INSTRUCTIONS: {additional_instructions}" if additional_instructions else ""}

OUTPUT FORMAT (JSON):
Return a JSON object with this EXACT structure:
{{
    "argument_id": "{argument.get('id', '')}",
    "opening_sentence": {{
        "text": "opening sentence text with explicit legal citation",
        "snippet_ids": []
    }},
    "subargument_paragraphs": [
        {{
            "subargument_id": "subarg-xxx",
            "sentences": [
                {{
                    "text": "sentence text with [Exhibit X, p.Y] citations. May include block quotes: > \\"exact quote\\" [Exhibit X, p.Y]",
                    "snippet_ids": ["snip_xxx", "snip_yyy"],
                    "exhibit_refs": ["X-Y"]
                }}
            ]
        }}
    ],
    "closing_sentence": {{
        "text": "closing sentence text"
    }}
}}

CRITICAL RULES:
1. ONLY use snippet_ids from the evidence provided above
2. Keep SubArgument boundaries clear - each subargument_paragraphs entry corresponds to ONE SubArgument
3. Every factual claim must reference at least one snippet_id
4. Use professional legal tone with rich, persuasive language
5. Generate 3-5 sentences per SubArgument (NOT just 1-2)
6. Include at least one block quote per SubArgument when source material contains direct testimony
7. Return ONLY valid JSON, no markdown or extra text
8. OUTPUT MUST BE 100% ENGLISH. If source evidence contains non-English text (Chinese, etc.), TRANSLATE it to English. Do NOT copy non-English characters. Use English translations only (e.g., "The Paper" not "澎湃新闻", "China Sports Daily" not "中国体育报")."""

    result = await call_deepseek(
        prompt=user_prompt,
        system_prompt=system_prompt,
        json_schema={},  # DeepSeek 会使用 json_object 模式
        temperature=0.5,
        max_tokens=4000
    )

    return result


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

        llm_result = await call_deepseek_text(
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

async def write_petition_section_v3(
    project_id: str,
    standard_key: str,
    argument_ids: List[str] = None,
    additional_instructions: str = None
) -> Dict:
    """
    V3 版本的写作入口

    Returns:
        {
            "success": bool,
            "section": str,
            "paragraph_text": str,
            "sentences": [...],
            "provenance_index": {...},
            "validation": {
                "total_sentences": int,
                "traced_sentences": int,
                "warnings": [...]
            }
        }
    """
    # 1. 加载 SubArgument 上下文
    context = load_subargument_context(project_id, standard_key, argument_ids)

    if not context.get("arguments"):
        return {
            "success": False,
            "error": f"No arguments found for standard: {standard_key}",
            "section": standard_key,
            "paragraph_text": "",
            "sentences": []
        }

    # 2. 生成结构化段落
    llm_output = await generate_structured_paragraph(context, additional_instructions)

    if "error" in llm_output:
        return {
            "success": False,
            "error": llm_output.get("error"),
            "section": standard_key,
            "paragraph_text": "",
            "sentences": []
        }

    # 2.5 确保输出为100%英文（后处理翻译）
    llm_output = await ensure_english_output(llm_output)

    # 3. 验证和修正溯源
    validation_result = validate_provenance(llm_output, context)
    validated_output = validation_result.get("fixed_output", llm_output)

    # 4. 扁平化句子列表
    sentences = flatten_sentences(validated_output, context)

    # 4.5 确保扁平化后的句子也是100%英文（安全网）
    # Note: LLM translation already happened in ensure_english_output
    # This is just a final safety net to remove any remaining Chinese
    for sentence in sentences:
        if "text" in sentence and _contains_non_ascii(sentence["text"]):
            sentence["text"] = _remove_remaining_chinese(sentence["text"])

    # 5. 构建溯源索引
    provenance_index = build_provenance_index(validated_output, context)

    # 6. 组装段落文本
    paragraph_text = " ".join(s["text"] for s in sentences)

    # 7. 统计
    total_sentences = len(sentences)
    traced_sentences = sum(1 for s in sentences if s.get("snippet_ids") or s.get("subargument_id"))

    return {
        "success": True,
        "section": standard_key,
        "paragraph_text": paragraph_text,
        "sentences": sentences,
        "provenance_index": provenance_index,
        "validation": {
            "total_sentences": total_sentences,
            "traced_sentences": traced_sentences,
            "warnings": validation_result.get("warnings", [])
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

    timestamp = datetime.now()
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

    result = await call_deepseek(
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
