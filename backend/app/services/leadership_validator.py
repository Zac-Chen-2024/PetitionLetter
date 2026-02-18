"""
Leadership Validator - LLM 判断层

使用 LLM 判断 snippet 是否真正表明申请人在某组织担任"领导/关键角色"。

判断标准 (基于 8 C.F.R. §204.5(h)(3)(viii)):
- Leading role: 创始人、CEO、总经理、法定代表人、董事长等
- Critical role: 对组织有重大影响的关键职位

NOT 领导角色:
- 演讲嘉宾 (keynote speaker) - 这是 invitation
- 合作伙伴 (partner) - 这是 cooperation
- 顾问 (advisor/consultant) - 除非有实际决策权
"""

import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from .llm_client import call_llm


@dataclass
class LeadershipJudgment:
    """领导角色判断结果"""
    is_leadership: bool
    organization_name: Optional[str]
    role_type: str  # "founder", "executive", "critical_role", "speaker", "partner", "other"
    confidence: float
    reasoning: str


# LLM 判断 Schema
LEADERSHIP_JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_leadership": {
            "type": "boolean",
            "description": "Is this evidence of a LEADING or CRITICAL role in the organization?"
        },
        "organization_name": {
            "type": ["string", "null"],
            "description": "Name of the organization where applicant has leadership role (null if not leadership)"
        },
        "role_type": {
            "type": "string",
            "enum": ["founder", "executive", "critical_role", "speaker", "partner", "advisor", "member", "other"],
            "description": "Type of role: founder/executive/critical_role = leadership; speaker/partner/advisor/member = NOT leadership"
        },
        "confidence": {
            "type": "number",
            "description": "Confidence score 0-1"
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of the judgment"
        }
    },
    "required": ["is_leadership", "organization_name", "role_type", "confidence", "reasoning"],
    "additionalProperties": False
}

LEADERSHIP_SYSTEM_PROMPT = """You are an expert immigration attorney evaluating evidence for EB-1A visa petitions.

Your task is to determine if a text snippet proves that the applicant has a LEADING or CRITICAL ROLE in an organization.

According to 8 C.F.R. §204.5(h)(3)(viii), a "leading or critical role" means:
- The person holds a position of significant authority or responsibility
- The person makes key decisions or has major impact on the organization
- Examples: Founder, CEO, President, Director, Legal Representative, Chairman

What is NOT a leading/critical role:
- Being a keynote speaker or guest speaker at an event (this is "invitation", not leadership)
- Being a partner or collaborator (this is cooperation, not leadership IN the organization)
- Being an advisor or consultant (unless they have actual decision-making power)
- Being a member of an organization (membership ≠ leadership)
- Being featured in media coverage (media coverage ≠ leadership)

Be strict: Only return is_leadership=true if the text CLEARLY shows the applicant LEADS or has a CRITICAL ROLE in the organization."""

LEADERSHIP_USER_PROMPT = """Analyze this text and determine if it shows the applicant ({applicant_name}) has a LEADING or CRITICAL ROLE in an organization.

TEXT:
{text}

CONTEXT (surrounding text):
{context}

Questions to answer:
1. Does this text show {applicant_name} LEADS an organization? (founder, CEO, director, etc.)
2. Or does it show {applicant_name} is just a speaker/partner/member/featured person?
3. If leadership, what organization and what role?

Return your judgment as JSON."""


async def validate_leadership(
    text: str,
    applicant_name: str,
    context: str = "",
    provider: str = "deepseek"
) -> LeadershipJudgment:
    """
    使用 LLM 判断 snippet 是否是领导角色证据

    Args:
        text: snippet 文本
        applicant_name: 申请人姓名
        context: 上下文 (来自 Context Enrichment)
        provider: LLM 提供商

    Returns:
        LeadershipJudgment 判断结果
    """
    user_prompt = LEADERSHIP_USER_PROMPT.format(
        applicant_name=applicant_name,
        text=text,
        context=context or "(no context available)"
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=LEADERSHIP_SYSTEM_PROMPT,
            json_schema=LEADERSHIP_JUDGMENT_SCHEMA,
            temperature=0.1,
            max_tokens=500
        )

        return LeadershipJudgment(
            is_leadership=result.get("is_leadership", False),
            organization_name=result.get("organization_name"),
            role_type=result.get("role_type", "other"),
            confidence=result.get("confidence", 0.5),
            reasoning=result.get("reasoning", "")
        )
    except Exception as e:
        print(f"[LeadershipValidator] Error: {e}")
        # 出错时返回保守判断 (不是领导角色)
        return LeadershipJudgment(
            is_leadership=False,
            organization_name=None,
            role_type="other",
            confidence=0.0,
            reasoning=f"Error during validation: {str(e)}"
        )


async def validate_leadership_batch(
    snippets: List[Dict],
    applicant_name: str,
    provider: str = "deepseek"
) -> List[Dict]:
    """
    批量验证 snippets 的领导角色

    Args:
        snippets: snippet 列表
        applicant_name: 申请人姓名
        provider: LLM 提供商

    Returns:
        添加了 leadership_judgment 的 snippets
    """
    results = []

    for i, snippet in enumerate(snippets):
        text = snippet.get("text", "")
        context_data = snippet.get("context", {})
        context = context_data.get("full_context", "") if context_data else ""

        print(f"[LeadershipValidator] Validating {i+1}/{len(snippets)}...")

        judgment = await validate_leadership(
            text=text,
            applicant_name=applicant_name,
            context=context,
            provider=provider
        )

        snippet_copy = snippet.copy()
        snippet_copy["leadership_judgment"] = {
            "is_leadership": judgment.is_leadership,
            "organization_name": judgment.organization_name,
            "role_type": judgment.role_type,
            "confidence": judgment.confidence,
            "reasoning": judgment.reasoning
        }
        results.append(snippet_copy)

    return results


def filter_leadership_snippets(
    snippets: List[Dict],
    require_judgment: bool = True
) -> List[Dict]:
    """
    过滤出真正的领导角色 snippets

    Args:
        snippets: 带有 leadership_judgment 的 snippets
        require_judgment: 是否要求必须有判断结果

    Returns:
        过滤后的 snippets
    """
    filtered = []

    for snippet in snippets:
        judgment = snippet.get("leadership_judgment", {})

        if not judgment and require_judgment:
            continue

        if judgment.get("is_leadership", False):
            filtered.append(snippet)

    return filtered
