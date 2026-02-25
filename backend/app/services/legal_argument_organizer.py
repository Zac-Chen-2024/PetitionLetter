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
from datetime import datetime, timezone
from pathlib import Path
import uuid

from .llm_client import call_llm
from .subargument_generator import generate_sub_arguments_for_composed, GeneratedSubArgument
from .standards_registry import get_standards_for_type


# ==================== EB-1A 法律条例定义 ====================

LEGAL_STANDARDS = {
    "awards": {
        "citation": "8 C.F.R. §204.5(h)(3)(i)",
        "name": "Nationally/Internationally Recognized Awards",
        "requirements": """
Legal requirements:
1. Awards must have national or international recognition
2. Awards must be for excellence in the field (not participation awards)
3. Must demonstrate the prestige and selectivity of the award

Argumentation structure (combine into ONE argument):
- Award description and recipient identity
- Awarding body's authority and reputation
- Selection criteria and competitiveness
""",
    },
    "membership": {
        "citation": "8 C.F.R. §204.5(h)(3)(ii)",
        "name": "Membership in Associations",
        "requirements": """
Legal requirements:
1. The association must require outstanding achievements for admission (not ordinary professional certification)
2. Must demonstrate the association's selectivity and distinguished reputation
3. Must show other distinguished members for peer comparison
4. Ordinary industry certifications or licenses do NOT qualify

Argumentation structure:
- Association introduction (proves distinguished reputation)
- Membership criteria (proves outstanding achievements required)
- Review process (proves rigorous selection)
- Other distinguished members (proves selectivity through peer comparison)
""",
    },
    "published_material": {
        "citation": "8 C.F.R. §204.5(h)(3)(iii)",
        "name": "Published Material in Major Media",
        "requirements": """
Legal requirements:
1. Media must be "major media" — demonstrate circulation, awards, influence
2. Coverage must be ABOUT the alien and the alien's work (not BY the alien)
3. Must demonstrate the media outlet's authority and professionalism

IMPORTANT: This is media coverage ABOUT the applicant, NOT articles written BY the applicant.
Articles authored by the applicant belong under Scholarly Articles (vi).

Argumentation structure (one sub-argument per media outlet):
- Article title and summary
- Media outlet introduction (proves major media: circulation, awards, history)
""",
    },
    "judging": {
        "citation": "8 C.F.R. §204.5(h)(3)(iv)",
        "name": "Judging the Work of Others",
        "requirements": """
Legal requirements:
1. The applicant participated individually or as part of a panel in judging the work of others in the field
2. Judging role must be based on professional expertise (invited, not obligatory)
3. Must demonstrate the authority of the judging activity (journal peer review, grant review, competition judging, etc.)

Argumentation structure (combine into ONE argument):
- Description of judging roles (journal names, conference names, funding agencies)
- Prestige of the reviewing institution/journal
- Frequency and consistency (proves ongoing invitations, not one-time)
- Invitation letters or acknowledgment as evidence
""",
    },
    "original_contribution": {
        "citation": "8 C.F.R. §204.5(h)(3)(v)",
        "name": "Original Contributions of Major Significance",
        "requirements": """
Legal requirements:
1. Contribution must be original
2. Contribution must be of major significance to the field
3. Requires quantified impact evidence (data, adoption rate, commercial success)
4. Requires independent expert recommendation letters

Argumentation structure (combine into ONE comprehensive argument):
- Description of original contribution (invention/innovation/methodology)
- Quantified impact (data, user count, revenue, coverage)
- Expert recommendation letters (independent third-party endorsement)
- Institutional adoption (schools, organizations, government recognition)
""",
    },
    "scholarly_articles": {
        "citation": "8 C.F.R. §204.5(h)(3)(vi)",
        "name": "Authorship of Scholarly Articles",
        "requirements": """
Legal requirements:
1. The applicant is the author of scholarly articles in professional or major trade publications or other major media
2. Published in professional journals or major media outlets
3. Must demonstrate the publication's impact (citation count, journal ranking, field influence)

IMPORTANT: This is articles/books authored BY the applicant.
This is DIFFERENT from Published Material (iii), which is media coverage ABOUT the applicant.

Argumentation structure:
- Journal/publication introduction (impact factor, ranking, field standing)
- Article content and contribution summary
- Citation data and scholarly impact metrics
- Comparison with other authoritative publications
""",
    },
    "display": {
        "citation": "8 C.F.R. §204.5(h)(3)(vii)",
        "name": "Display of Work at Exhibitions",
        "requirements": """
Legal requirements:
1. The applicant's work was displayed at artistic exhibitions or showcases
2. The exhibition must have professional standing and recognition
3. Applies to visual arts, performing arts, design, etc.

Argumentation structure:
- Exhibition/showcase introduction
- Exhibition's prestige and influence
- Form of display and reception of the applicant's work
""",
    },
    "leading_role": {
        "citation": "8 C.F.R. §204.5(h)(3)(viii)",
        "name": "Leading/Critical Role for Distinguished Organizations",
        "requirements": """
Legal requirements:
1. The role must be leading or critical
2. The organization must have a distinguished reputation
3. Must demonstrate the applicant's decision-making authority and influence

Argumentation structure (one sub-argument per organization, select top 2-3):
- Position and responsibilities (proves leading/critical role)
- Organization's reputation (proves distinguished reputation: awards, scale, recognition)
- Specific achievements (proves actual contribution and impact)
""",
    },
    "high_salary": {
        "citation": "8 C.F.R. §204.5(h)(3)(ix)",
        "name": "High Salary or Remuneration",
        "requirements": """
Legal requirements:
1. Salary must be significantly higher than others in the field
2. Must provide industry salary comparison data
3. Can include wages, bonuses, royalties, consulting fees, or any form of remuneration

Argumentation structure:
- Applicant's compensation data
- Industry average salary benchmark data (from authoritative statistical sources)
- Comparative analysis (proves significantly above average)
- If multiple income sources, argue each separately
""",
    },
    "commercial_success": {
        "citation": "8 C.F.R. §204.5(h)(3)(x)",
        "name": "Commercial Success in the Performing Arts",
        "requirements": """
Legal requirements:
1. Applies to the performing arts field
2. Must show box office revenue, record sales, ratings, or similar commercial data
3. Commercial success must reach a significant level in the industry

Argumentation structure:
- Commercial data (box office, sales, ratings, etc.)
- Industry benchmark comparison
- Media or industry recognition of commercial success
""",
    },
}


# ==================== Prompt Templates ====================

# ==================== NIW 法律条例定义 ====================

NIW_LEGAL_STANDARDS = {
    "prong1_merit": {
        "citation": "Matter of Dhanasar, 26 I&N Dec. 884, Prong 1",
        "name": "Substantial Merit & National Importance",
        "requirements": """
The proposed endeavor must have both substantial merit and national importance.

论证结构：
1. 描述申请人提出的 endeavor（研究方向、商业计划等）
2. 证明其具有实质性价值（substantial merit）
3. 证明其具有全国性重要意义（national importance）
4. 引用推荐信和客观证据佐证
""",
    },
    "prong2_positioned": {
        "citation": "Matter of Dhanasar, 26 I&N Dec. 884, Prong 2",
        "name": "Well Positioned to Advance the Endeavor",
        "requirements": """
The foreign national must be well positioned to advance the proposed endeavor.

论证结构：
1. 教育背景和专业资质
2. 相关领域的工作经验和成就记录
3. 已取得的进展和未来计划
4. 独特技能或知识使申请人特别适合推进此事业
""",
    },
    "prong3_balance": {
        "citation": "Matter of Dhanasar, 26 I&N Dec. 884, Prong 3",
        "name": "Balance of Equities Favors Waiver",
        "requirements": """
On balance, it would be beneficial to the United States to waive the requirements of a job offer.

论证结构：
1. 申请人的贡献对美国利益的重要性
2. 劳工证要求对此类人才的不适用性
3. 申请人的工作成果已超越特定雇主的利益
4. 国家利益优于保护美国工人的考量
""",
    },
}


# ==================== Prompt Templates ====================

ORGANIZE_SYSTEM_PROMPT = """You are an expert EB-1A immigration attorney with deep knowledge of 8 C.F.R. §204.5(h)(3).

Your task is to organize evidence snippets into powerful legal arguments,
following the exact structure that immigration lawyers use in petition letters.

KEY PRINCIPLES:
1. You MUST create at least one argument for EVERY standard that has evidence snippets provided below
2. Each argument must directly address the legal requirements of its standard
3. Filter out weak evidence (e.g., ordinary professional certifications for Membership)
4. Combine related evidence into cohesive arguments within each standard
5. Follow the argumentation structure specified for each standard
6. CRITICAL DISTINCTION — Published Material (iii) vs Scholarly Articles (vi):
   - (iii) Published Material = media coverage ABOUT the alien by others
   - (vi) Scholarly Articles = academic papers/articles authored BY the alien
   These are completely different criteria. Never confuse them.

OUTPUT LANGUAGE: ALL output must be in English. Do NOT use Chinese or any other language."""

ORGANIZE_USER_PROMPT = """## EVIDENCE SUMMARY

The following {standards_with_evidence_count} EB-1A criteria have supporting evidence.
You MUST create at least one argument for EACH of them:

{evidence_summary}

## Legal Standards and Requirements (only those with evidence)

{standards_text}

## Evidence Snippets by Standard

{snippets_by_standard}

## Task

Create arguments for ALL {standards_with_evidence_count} standards listed above. Do NOT skip any.

Per-standard rules:
- Awards (i): Combine into ONE argument
- Membership (ii): Only include associations requiring outstanding achievements (filter ordinary certifications)
- Published Material (iii): Media ABOUT the alien — one argument per major media outlet
- Judging (iv): Peer review, grant review, competition judging — combine into ONE argument
- Original Contribution (v): Combine ALL into ONE comprehensive argument
- Scholarly Articles (vi): Articles authored BY the alien — focus on journal prestige and citation impact
- Leading Role (viii): Select top 2-3 most distinguished organizations
- High Salary (ix): Only if significantly above field average

The "standard" field MUST exactly match one of: {valid_standard_keys}

Return JSON:
{{
  "arguments": [
    {{
      "id": "arg-001",
      "standard": "membership",
      "title": "[Applicant]'s Membership in [Association Name]",
      "rationale": "Why this argument is strong",
      "snippet_ids": ["snp-001", "snp-002"],
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
    "by_standard": {{"membership": 1, "scholarly_articles": 1, "judging": 1}}
  }}
}}"""


NIW_ORGANIZE_SYSTEM_PROMPT = """You are an expert NIW (National Interest Waiver) immigration attorney with deep knowledge of Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016).

Your task is to organize evidence snippets into powerful legal arguments under the Dhanasar three-prong framework.

KEY PRINCIPLES:
1. Each argument must directly address one of the three Dhanasar prongs
2. Prong 1 (Substantial Merit & National Importance): Focus on the proposed endeavor's value
3. Prong 2 (Well Positioned): Focus on qualifications, track record, and plans
4. Prong 3 (Balance): Focus on why waiving labor certification benefits the US
5. Combine related evidence into cohesive, well-supported arguments

OUTPUT LANGUAGE: Use English for argument titles (following lawyer style), Chinese for internal notes."""


NIW_ORGANIZE_USER_PROMPT = """## EVIDENCE SUMMARY

{standards_with_evidence_count} prongs have supporting evidence:

{evidence_summary}

## Dhanasar Three-Prong Framework

{standards_text}

## Evidence Snippets by Prong

{snippets_by_standard}

## Task

Organize these snippets into powerful legal arguments under the Dhanasar framework.
Aim for 3-6 arguments total, with at least one per prong.
Valid standard keys: {valid_standard_keys}

Return JSON:
{{
  "arguments": [
    {{
      "id": "arg-001",
      "standard": "prong1_merit",
      "title": "Applicant's Research in X Addresses National Need for Y",
      "rationale": "Why this argument is strong",
      "snippet_ids": ["snp-001", "snp-002"],
      "evidence_strength": "strong|medium|weak"
    }}
  ],
  "filtered_out": [
    {{
      "snippet_ids": ["snp-xxx"],
      "reason": "Not relevant to any Dhanasar prong"
    }}
  ],
  "summary": {{
    "total_arguments": 5,
    "by_standard": {{"prong1_merit": 2, "prong2_positioned": 2, "prong3_balance": 1}}
  }}
}}"""


# ==================== NIW snippet grouping ====================

NIW_EVIDENCE_TYPE_MAPPING = {
    "contribution": "prong1_merit",
    "quantitative_impact": "prong1_merit",
    "recommendation": "prong2_positioned",
    "leadership": "prong2_positioned",
    "award": "prong2_positioned",
    "membership": "prong2_positioned",
    "publication": "prong2_positioned",
    "media_coverage": "prong1_merit",
}


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
            self.created_at = datetime.now(timezone.utc).isoformat()

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
    provider: str = "deepseek",
    project_type: str = "EB-1A"
) -> Tuple[List[LegalArgument], List[Dict]]:
    """
    使用 LLM + 法律条例组织子论点

    Args:
        snippets: 所有提取的 snippets
        applicant_name: 申请人姓名
        provider: LLM provider
        project_type: "EB-1A" or "NIW"

    Returns:
        (arguments, filtered_snippets)
    """
    print(f"[LegalOrganizer] Organizing {len(snippets)} snippets with {project_type} legal framework...")

    # Select standards and prompts based on project type
    if project_type == "NIW":
        legal_stds = NIW_LEGAL_STANDARDS
        system_prompt = NIW_ORGANIZE_SYSTEM_PROMPT
        user_prompt_template = NIW_ORGANIZE_USER_PROMPT
        evidence_mapping = NIW_EVIDENCE_TYPE_MAPPING
    else:
        legal_stds = LEGAL_STANDARDS
        system_prompt = ORGANIZE_SYSTEM_PROMPT
        user_prompt_template = ORGANIZE_USER_PROMPT
        evidence_mapping = None  # uses default _group_snippets_by_standard

    # 按 standard 分组 snippets
    snippets_by_std = _group_snippets_by_standard(snippets, legal_stds, evidence_mapping)

    # 构建 prompt — only include standards that have evidence
    standards_with_evidence = {k: v for k, v in snippets_by_std.items() if v}
    standards_text = _format_standards_text(legal_stds, only_keys=set(standards_with_evidence.keys()))
    snippets_text = _format_snippets_by_standard(snippets_by_std, applicant_name, legal_stds)

    # Build evidence summary (explicit list at top of prompt)
    evidence_summary_lines = []
    for std_key, std_snps in standards_with_evidence.items():
        std_info = legal_stds.get(std_key, {})
        evidence_summary_lines.append(
            f"- **{std_info.get('name', std_key)}** ({std_info.get('citation', '')}) — {len(std_snps)} snippets → standard key: \"{std_key}\""
        )
    evidence_summary = "\n".join(evidence_summary_lines)

    # Build valid standard keys for the prompt
    valid_keys = ", ".join(f'"{k}"' for k in legal_stds.keys())

    user_prompt = user_prompt_template.format(
        standards_text=standards_text,
        snippet_count=len(snippets),
        snippets_by_standard=snippets_text,
        valid_standard_keys=valid_keys,
        standards_with_evidence_count=len(standards_with_evidence),
        evidence_summary=evidence_summary,
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=8000
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

        # Post-processing: ensure every standard with evidence gets at least one argument.
        # LLMs often ignore less common standards (judging, scholarly_articles, etc.)
        # Normalize standard keys to handle plural/singular variants
        _STANDARD_ALIASES = {
            "original_contributions": "original_contribution",
            "scholarly_article": "scholarly_articles",
            "high_salaries": "high_salary",
        }
        covered_standards = set()
        for arg in arguments:
            canonical = _STANDARD_ALIASES.get(arg.standard, arg.standard)
            covered_standards.add(canonical)
            covered_standards.add(arg.standard)  # also add the raw form

        print(f"[LegalOrganizer] Covered standards: {covered_standards}")
        stds_with_evidence = [k for k, v in snippets_by_std.items() if v]
        print(f"[LegalOrganizer] Standards with evidence: {stds_with_evidence}")

        arg_counter = len(arguments)
        for std_key, std_snippets in snippets_by_std.items():
            if not std_snippets:
                continue
            if std_key in covered_standards:
                continue
            print(f"[LegalOrganizer] FALLBACK: '{std_key}' has {len(std_snippets)} snippets but no LLM argument")
            # This standard has evidence but no LLM argument — create a fallback
            arg_counter += 1
            std_info = legal_stds.get(std_key, {})
            snippet_ids = [s.get('snippet_id', s.get('id', '')) for s in std_snippets]
            fallback_arg = LegalArgument(
                id=f"arg-{arg_counter:03d}",
                standard=std_key,
                title=f"{applicant_name}'s {std_info.get('name', std_key)}",
                rationale=f"Auto-generated fallback: LLM did not create an argument for {std_key} despite {len(std_snippets)} supporting snippets",
                snippet_ids=snippet_ids,
                evidence_strength="medium",
                subject=applicant_name,
            )
            arguments.append(fallback_arg)
            print(f"[LegalOrganizer] Added fallback argument for '{std_key}' with {len(snippet_ids)} snippets")

        return arguments, filtered_out

    except Exception as e:
        print(f"[LegalOrganizer] Error: {e}")
        # Fallback: 简单分组
        return _fallback_organize(snippets, applicant_name, legal_stds), []


# Default EB-1A evidence type mapping
# Maps extraction evidence_type → LEGAL_STANDARDS key
_EB1A_EVIDENCE_TYPE_MAPPING = {
    # (i) Awards
    "award": "awards",
    # (ii) Membership
    "membership": "membership",
    "membership_criteria": "membership",
    "membership_evaluation": "membership",
    "peer_achievement": "membership",
    "selectivity_proof": "membership",
    # (iii) Published Material — media/reports ABOUT the alien
    "media_coverage": "published_material",
    "source_credibility": "published_material",
    # (iv) Judging
    "judging": "judging",
    "peer_assessment": "judging",
    "invitation": "judging",
    # (v) Original Contribution
    "contribution": "original_contribution",
    "quantitative_impact": "original_contribution",
    "recommendation": "original_contribution",
    "impact_proof": "original_contribution",
    "scientific_research_project": "original_contribution",
    # (vi) Scholarly Articles — authored BY the alien
    "publication": "scholarly_articles",
    "scholarly_article": "scholarly_articles",
    "authorship": "scholarly_articles",
    # (viii) Leading/Critical Role
    "leadership": "leading_role",
    "organization": "leading_role",
    # (vii) Display/Exhibition
    "exhibition": "display",
    "display": "display",
    # (ix) High Salary
    "salary": "high_salary",
    "compensation": "high_salary",
    "salary_benchmark": "high_salary",
    "high_salary": "high_salary",
    # (x) Commercial Success
    "commercial": "commercial_success",
    "commercial_success": "commercial_success",
    "box_office": "commercial_success",
    "sales": "commercial_success",
}


def _group_snippets_by_standard(
    snippets: List[Dict],
    legal_stds: Dict = None,
    evidence_mapping: Dict = None
) -> Dict[str, List[Dict]]:
    """按 standard 分组"""
    if legal_stds is None:
        legal_stds = LEGAL_STANDARDS
    if evidence_mapping is None:
        evidence_mapping = _EB1A_EVIDENCE_TYPE_MAPPING

    grouped = {std: [] for std in legal_stds.keys()}

    for snp in snippets:
        if not snp.get('is_applicant_achievement', True):
            continue
        etype = snp.get('evidence_type', '').lower()
        standard = evidence_mapping.get(etype)
        if standard and standard in grouped:
            grouped[standard].append(snp)

    return grouped


def _format_standards_text(legal_stds: Dict = None, only_keys: set = None) -> str:
    """Format legal standards text, optionally filtered to only standards with evidence."""
    if legal_stds is None:
        legal_stds = LEGAL_STANDARDS
    lines = []
    for std_key, std_info in legal_stds.items():
        if only_keys and std_key not in only_keys:
            continue
        lines.append(f"### {std_info['name']} ({std_info['citation']}) [key: {std_key}]")
        lines.append(std_info['requirements'])
        lines.append("")
    return "\n".join(lines)


def _format_snippets_by_standard(grouped: Dict[str, List[Dict]], applicant_name: str, legal_stds: Dict = None) -> str:
    """格式化 snippets 按标准分组"""
    if legal_stds is None:
        legal_stds = LEGAL_STANDARDS
    lines = []

    for std_key, snps in grouped.items():
        if not snps:
            continue
        std_info = legal_stds.get(std_key, {})
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


def _fallback_organize(snippets: List[Dict], applicant_name: str, legal_stds: Dict = None) -> List[LegalArgument]:
    """Fallback: 简单分组"""
    if legal_stds is None:
        legal_stds = LEGAL_STANDARDS
    grouped = _group_snippets_by_standard(snippets, legal_stds)
    arguments = []

    for std_key, snps in grouped.items():
        if not snps:
            continue

        std_info = legal_stds.get(std_key, {})
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
    applicant_name: str = "the Applicant",
    provider: str = "deepseek",
    project_type: str = "EB-1A"
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
    combined_file = project_dir / "extraction" / "combined_extraction.json"
    if enriched_file.exists():
        with open(enriched_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        snippets = data.get('snippets', [])
    elif combined_file.exists():
        # Use combined extraction (same source as frontend API)
        with open(combined_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        snippets = data.get('snippets', [])
    else:
        # Fallback to per-exhibit extraction files
        snippets = []
        extraction_dir = project_dir / "extraction"
        if extraction_dir.exists():
            for f in extraction_dir.glob("*_extraction.json"):
                if f.name == "combined_extraction.json":
                    continue
                with open(f, 'r', encoding='utf-8') as fp:
                    d = json.load(fp)
                    snippets.extend(d.get("snippets", []))

    print(f"[LegalPipeline] Loaded {len(snippets)} snippets")

    # Resolve project_type from storage if not provided
    if not project_type or project_type == "EB-1A":
        try:
            from .storage import get_project_type
            project_type = get_project_type(project_id)
        except Exception:
            project_type = "EB-1A"

    # Step 1: 组织子论点
    print(f"\n[Step 1] Organizing arguments with {project_type} legal framework...")
    arguments, filtered = await organize_arguments_with_legal_framework(
        snippets, applicant_name, provider, project_type
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
        "main_subject": applicant_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
