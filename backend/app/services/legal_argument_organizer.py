"""
Legal Argument Organizer - LLM + 法律条例驱动的子论点组织器

核心原则：
1. LLM 理解 8 C.F.R. §204.5(h)(3) 各标准的法律要件
2. 智能选择最有说服力的证据组合
3. 自动过滤弱证据（如普通会员资格）
4. 输出数量与律师例文一致（~7-8个子论点）
"""

import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import uuid

from .llm_client import call_llm
from .subargument_generator import generate_sub_arguments_for_composed, GeneratedSubArgument


# ==================== 法律条例定义 ====================

LEGAL_STANDARDS = {
    "membership": {
        "citation": "8 C.F.R. §204.5(h)(3)(ii)",
        "name": "Membership in Associations",
        "requirements": """
协会会员资格必须满足以下法律要件：
1. 协会必须要求成员具有杰出成就才能加入（不是普通专业认证）
2. 需要证明协会的选择性和声望
3. 需要展示其他杰出会员作为参照（peer achievement）
4. 普通认证（如 NSCA, ACE, NASM 等）不符合要求

律师论证结构：
- 协会介绍（证明 distinguished reputation）
- 会员资格要求（证明 outstanding achievements required）
- 审核过程（证明 rigorous selection）
- 其他杰出会员（证明 selectivity through peer comparison）
""",
    },
    "published_material": {
        "citation": "8 C.F.R. §204.5(h)(3)(iii)",
        "name": "Published Material in Major Media",
        "requirements": """
媒体报道必须满足以下法律要件：
1. 媒体必须是"主要媒体"（major media）- 需证明发行量、获奖、影响力
2. 报道必须是关于申请人及其工作（about the alien and the alien's work）
3. 需要展示媒体的权威性和专业性

律师论证结构（每个媒体一个子论点）：
- 报道标题和摘要
- 媒体介绍（证明是 major media：发行量、奖项、历史地位）
""",
    },
    "original_contribution": {
        "citation": "8 C.F.R. §204.5(h)(3)(v)",
        "name": "Original Contributions of Major Significance",
        "requirements": """
原创贡献必须满足以下法律要件：
1. 贡献必须是原创的（original）
2. 贡献必须具有重大意义（major significance）
3. 需要量化影响力证据（数据、采用率、商业成功）
4. 需要独立专家推荐信佐证

律师论证结构（合并成一个整体论点）：
- 原创贡献描述（发明/创新/方法论）
- 量化影响（数据、用户数、收入、覆盖范围）
- 专家推荐信（独立第三方认可）
- 机构采用（学校、组织、政府认可）
""",
    },
    "leading_role": {
        "citation": "8 C.F.R. §204.5(h)(3)(viii)",
        "name": "Leading/Critical Role for Distinguished Organizations",
        "requirements": """
领导角色必须满足以下法律要件：
1. 角色必须是领导性或关键性的（leading or critical）
2. 组织必须具有杰出声誉（distinguished reputation）
3. 需要证明申请人的决策权和影响力

律师论证结构（每个组织一个子论点，选最强2-3个）：
- 职位和职责（证明 leading/critical role）
- 组织声誉（证明 distinguished reputation：奖项、规模、认可）
- 具体成就（证明实际贡献和影响）
""",
    },
    "awards": {
        "citation": "8 C.F.R. §204.5(h)(3)(i)",
        "name": "Nationally/Internationally Recognized Awards",
        "requirements": """
奖项必须满足以下法律要件：
1. 奖项必须具有国家或国际认可度
2. 奖项必须是针对卓越成就的（for excellence）
3. 需要证明奖项的权威性和选择性

律师论证结构（合并成一个子论点）：
- 奖项描述和获奖者身份
- 颁奖机构介绍（证明权威性）
- 奖项标准和选择性
""",
    },
}


# ==================== Prompt Templates ====================

ORGANIZE_SYSTEM_PROMPT = """You are an expert EB-1A immigration attorney with deep knowledge of 8 C.F.R. §204.5(h)(3).

Your task is to organize evidence snippets into a small number of powerful legal arguments (子论点),
following the exact structure that immigration lawyers use in petition letters.

KEY PRINCIPLES:
1. Quality over quantity - aim for ~7-8 strong arguments total, not 14+ weak ones
2. Each argument must directly address the legal requirements of its standard
3. Filter out weak evidence (e.g., ordinary professional certifications for Membership)
4. Combine related evidence into cohesive arguments
5. Follow the lawyer's argumentation structure for each standard

OUTPUT LANGUAGE: Use English for argument titles (following lawyer style), Chinese for internal notes."""

ORGANIZE_USER_PROMPT = """## Legal Standards and Requirements

{standards_text}

## Available Evidence Snippets

Total: {snippet_count} snippets

{snippets_by_standard}

## Task

Organize these snippets into ~7-8 powerful legal arguments following the lawyer's structure.

Rules:
1. Membership: Only include associations that REQUIRE outstanding achievements (filter out NSCA, ACE, etc.)
2. Published Material: One argument per major media outlet (select top 3-4 most prestigious)
3. Original Contribution: Combine ALL contribution evidence into ONE comprehensive argument
4. Leading Role: Select top 2-3 most distinguished organizations only
5. Awards: Combine into ONE argument if applicable

Return JSON:
{{
  "arguments": [
    {{
      "id": "arg-001",
      "standard": "membership",
      "title": "Ms. Qu's Membership in Shanghai Fitness Bodybuilding Association",
      "rationale": "Why this argument is strong (internal note)",
      "snippet_ids": ["snp-001", "snp-002", ...],
      "evidence_strength": "strong|medium|weak"
    }}
  ],
  "filtered_out": [
    {{
      "snippet_ids": ["snp-xxx"],
      "reason": "Ordinary certification, does not meet membership requirements"
    }}
  ],
  "summary": {{
    "total_arguments": 7,
    "by_standard": {{"membership": 1, "published_material": 3, ...}}
  }}
}}"""


@dataclass
class LegalArgument:
    """法律论点数据结构"""
    id: str
    standard: str
    title: str
    rationale: str
    snippet_ids: List[str]
    evidence_strength: str
    sub_argument_ids: List[str] = None
    subject: str = "the applicant"
    confidence: float = 0.9
    is_ai_generated: bool = True
    created_at: str = ""

    def __post_init__(self):
        if self.sub_argument_ids is None:
            self.sub_argument_ids = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self):
        """转换为前端兼容的字典格式"""
        return {
            "id": self.id,
            "standard": self.standard,
            "standard_key": self.standard,  # 前端需要 standard_key
            "title": self.title,
            "rationale": self.rationale,
            "snippet_ids": self.snippet_ids,
            "evidence_strength": self.evidence_strength,
            "sub_argument_ids": self.sub_argument_ids,
            "subject": self.subject,
            "confidence": self.confidence,
            "is_ai_generated": self.is_ai_generated,
            "created_at": self.created_at,
        }


async def organize_arguments_with_legal_framework(
    snippets: List[Dict],
    applicant_name: str = "the applicant",
    provider: str = "deepseek"
) -> Tuple[List[LegalArgument], List[Dict]]:
    """
    使用 LLM + 法律条例组织子论点

    Args:
        snippets: 所有提取的 snippets
        applicant_name: 申请人姓名
        provider: LLM provider

    Returns:
        (arguments, filtered_snippets)
    """
    print(f"[LegalOrganizer] Organizing {len(snippets)} snippets with legal framework...")

    # 按 standard 分组 snippets
    snippets_by_std = _group_snippets_by_standard(snippets)

    # 构建 prompt
    standards_text = _format_standards_text()
    snippets_text = _format_snippets_by_standard(snippets_by_std, applicant_name)

    user_prompt = ORGANIZE_USER_PROMPT.format(
        standards_text=standards_text,
        snippet_count=len(snippets),
        snippets_by_standard=snippets_text
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=ORGANIZE_SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=4000
        )

        raw_arguments = result.get('arguments', [])
        filtered_out = result.get('filtered_out', [])
        summary = result.get('summary', {})

        print(f"[LegalOrganizer] LLM organized into {len(raw_arguments)} arguments")
        print(f"[LegalOrganizer] Summary: {summary}")

        # 转换为 LegalArgument
        arguments = []
        for raw_arg in raw_arguments:
            arg = LegalArgument(
                id=raw_arg.get('id', f"arg-{uuid.uuid4().hex[:8]}"),
                standard=raw_arg.get('standard', ''),
                title=raw_arg.get('title', ''),
                rationale=raw_arg.get('rationale', ''),
                snippet_ids=raw_arg.get('snippet_ids', []),
                evidence_strength=raw_arg.get('evidence_strength', 'medium'),
                subject=applicant_name,
            )
            arguments.append(arg)

        return arguments, filtered_out

    except Exception as e:
        print(f"[LegalOrganizer] Error: {e}")
        # Fallback: 简单分组
        return _fallback_organize(snippets, applicant_name), []


def _group_snippets_by_standard(snippets: List[Dict]) -> Dict[str, List[Dict]]:
    """按 standard 分组"""
    mapping = {
        "membership": "membership",
        "membership_criteria": "membership",
        "membership_evaluation": "membership",
        "peer_achievement": "membership",
        "publication": "published_material",
        "media_coverage": "published_material",
        "source_credibility": "published_material",
        "contribution": "original_contribution",
        "quantitative_impact": "original_contribution",
        "recommendation": "original_contribution",
        "leadership": "leading_role",
        "award": "awards",
    }

    grouped = {std: [] for std in LEGAL_STANDARDS.keys()}

    for snp in snippets:
        if not snp.get('is_applicant_achievement', True):
            continue
        etype = snp.get('evidence_type', '').lower()
        standard = mapping.get(etype)
        if standard and standard in grouped:
            grouped[standard].append(snp)

    return grouped


def _format_standards_text() -> str:
    """格式化法律标准文本"""
    lines = []
    for std_key, std_info in LEGAL_STANDARDS.items():
        lines.append(f"### {std_info['name']} ({std_info['citation']})")
        lines.append(std_info['requirements'])
        lines.append("")
    return "\n".join(lines)


def _format_snippets_by_standard(grouped: Dict[str, List[Dict]], applicant_name: str) -> str:
    """格式化 snippets 按标准分组"""
    lines = []

    for std_key, snps in grouped.items():
        if not snps:
            continue
        std_info = LEGAL_STANDARDS.get(std_key, {})
        lines.append(f"### {std_info.get('name', std_key)} ({len(snps)} snippets)")

        for i, snp in enumerate(snps[:30], 1):  # Limit to 30 per standard
            sid = snp.get('snippet_id', snp.get('id', ''))
            text = snp.get('text', '')[:200]
            exhibit = snp.get('exhibit_id', '')
            subject = snp.get('subject', '')
            lines.append(f"[{sid}] (Exhibit {exhibit}, subject: {subject}) {text}...")

        if len(snps) > 30:
            lines.append(f"... and {len(snps) - 30} more snippets")
        lines.append("")

    return "\n".join(lines)


def _fallback_organize(snippets: List[Dict], applicant_name: str) -> List[LegalArgument]:
    """Fallback: 简单分组"""
    grouped = _group_snippets_by_standard(snippets)
    arguments = []

    for std_key, snps in grouped.items():
        if not snps:
            continue

        std_info = LEGAL_STANDARDS.get(std_key, {})
        snippet_ids = [s.get('snippet_id', s.get('id', '')) for s in snps]

        arg = LegalArgument(
            id=f"arg-{uuid.uuid4().hex[:8]}",
            standard=std_key,
            title=f"{applicant_name}'s {std_info.get('name', std_key)}",
            rationale="Fallback grouping",
            snippet_ids=snippet_ids,
            evidence_strength="medium",
            subject=applicant_name,
        )
        arguments.append(arg)

    return arguments


async def full_legal_pipeline(
    project_id: str,
    applicant_name: str = "Ms. Qu",
    provider: str = "deepseek"
) -> Dict[str, Any]:
    """
    完整的法律论点组织流程

    Step 1: LLM + 法律条例 → 组织子论点
    Step 2: LLM → 划分次级子论点

    Returns:
        {
            "arguments": [...],
            "sub_arguments": [...],
            "filtered": [...],
            "stats": {...}
        }
    """
    from pathlib import Path

    # 加载 snippets
    projects_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    project_dir = projects_dir / project_id

    enriched_file = project_dir / "enriched" / "enriched_snippets.json"
    if enriched_file.exists():
        with open(enriched_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        snippets = data.get('snippets', [])
    else:
        # Fallback to extraction
        snippets = []
        extraction_dir = project_dir / "extraction"
        if extraction_dir.exists():
            for f in extraction_dir.glob("*_extraction.json"):
                with open(f, 'r', encoding='utf-8') as fp:
                    d = json.load(fp)
                    snippets.extend(d.get("snippets", []))

    print(f"[LegalPipeline] Loaded {len(snippets)} snippets")

    # Step 1: 组织子论点
    print("\n[Step 1] Organizing arguments with legal framework...")
    arguments, filtered = await organize_arguments_with_legal_framework(
        snippets, applicant_name, provider
    )

    print(f"[Step 1] Generated {len(arguments)} arguments")

    # Build snippet lookup
    snippet_map = {s.get('snippet_id', s.get('id', '')): s for s in snippets}

    # Step 2: 划分次级子论点
    print("\n[Step 2] Subdividing into sub-arguments...")
    all_sub_arguments = []

    from .subargument_generator import subdivide_argument

    for arg in arguments:
        # Get snippets for this argument
        arg_snippets = [snippet_map[sid] for sid in arg.snippet_ids if sid in snippet_map]

        if not arg_snippets:
            continue

        sub_args = await subdivide_argument(
            argument={'id': arg.id, 'title': arg.title, 'standard': arg.standard},
            snippets=arg_snippets,
            provider=provider
        )

        arg.sub_argument_ids = [sa.id for sa in sub_args]
        all_sub_arguments.extend([asdict(sa) for sa in sub_args])

        await asyncio.sleep(0.2)

    print(f"[Step 2] Generated {len(all_sub_arguments)} sub-arguments")

    # 统计
    by_standard = {}
    for arg in arguments:
        std = arg.standard
        by_standard[std] = by_standard.get(std, 0) + 1

    result = {
        "arguments": [a.to_dict() for a in arguments],
        "sub_arguments": all_sub_arguments,
        "filtered": filtered,
        "stats": {
            "argument_count": len(arguments),
            "sub_argument_count": len(all_sub_arguments),
            "by_standard": by_standard,
            "avg_subargs_per_arg": len(all_sub_arguments) / len(arguments) if arguments else 0
        }
    }

    # 保存结果
    output_file = project_dir / "arguments" / "legal_arguments.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[LegalPipeline] Results saved to {output_file}")

    return result
