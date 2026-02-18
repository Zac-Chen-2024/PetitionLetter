"""
Evidence Grouping Agent - 证据分组服务

基于 Relationship Analysis 结果，将碎片化的 snippets 分组为可用于论点组合的证据集群。

核心功能：
1. 按申请人-实体关系分组 snippets
2. 识别每个证据集群对应的 EB-1A 标准
3. 为 Standard-Specific Agents 准备输入

设计原则：
- 使用 LLM 判断，不用硬编码规则
- 基于关系分析结果，而不是简单的关键词匹配
- 支持 snippet 属于多个集群（一个 snippet 可能同时支持多个论点）
"""

import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .llm_client import call_llm


# EB-1A 标准与关系类型的映射
STANDARD_RELATIONSHIP_MAP = {
    "leading_role": ["founder_of", "executive_at", "employee_at"],  # 需要验证 employee_at 的具体职位
    "membership": ["member_of"],
    "published_material": ["featured_in"],
    "awards": ["awarded_by"],
    "original_contribution": ["founder_of", "contributed_to"],  # founder_of 也可能证明原创贡献
}

# 排除的关系类型（不直接对应任何标准）
NON_QUALIFYING_RELATIONSHIPS = ["invited_by", "partner_with", "recommended_by"]


@dataclass
class EvidenceCluster:
    """证据集群"""
    cluster_id: str
    entity_name: str
    relationship_type: str
    suggested_standard: str  # leading_role, membership, published_material, etc.
    snippet_ids: List[str] = field(default_factory=list)
    confidence: float = 0.5
    reasoning: str = ""
    qualifies: bool = True  # 是否符合该标准的要求


EVIDENCE_GROUPING_SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cluster_id": {
                        "type": "string",
                        "description": "Unique ID for this cluster"
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "The organization/entity this cluster is about"
                    },
                    "suggested_standard": {
                        "type": "string",
                        "enum": ["leading_role", "membership", "published_material", "awards", "original_contribution", "none"],
                        "description": "Which EB-1A standard this evidence supports"
                    },
                    "snippet_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of snippet IDs in this cluster"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Why these snippets are grouped together"
                    }
                },
                "required": ["cluster_id", "entity_name", "suggested_standard", "snippet_ids", "reasoning"]
            }
        }
    },
    "required": ["clusters"]
}

EVIDENCE_GROUPING_SYSTEM_PROMPT = """You are an expert immigration attorney organizing evidence for an EB-1A visa petition.

Your task is to group evidence snippets into meaningful clusters that can be used to build arguments for specific EB-1A criteria.

EB-1A CRITERIA:
1. **leading_role**: Evidence of leading or critical role in organizations with distinguished reputation
   - Applicant must be FOUNDER, CEO, DIRECTOR, or hold executive position
   - Being invited to speak or having partnerships does NOT qualify

2. **membership**: Membership in associations requiring outstanding achievements
   - Must show membership certificate AND selection criteria

3. **published_material**: Published material about the applicant in major media
   - Must be ABOUT the applicant, not BY the applicant

4. **awards**: Nationally/internationally recognized prizes or awards

5. **original_contribution**: Original contributions of major significance
   - Innovations, methodologies, or systems created by applicant

GROUPING PRINCIPLES:
- Group snippets by the ENTITY they relate to (one organization = one cluster)
- A snippet can belong to multiple clusters if it supports multiple arguments
- Only suggest a standard if the relationship type actually qualifies
- Use "none" for clusters that don't fit any EB-1A criterion"""

EVIDENCE_GROUPING_USER_PROMPT = """Based on the relationship analysis and snippets, create evidence clusters for EB-1A arguments.

APPLICANT: {applicant_name}

RELATIONSHIP ANALYSIS:
{relationships_summary}

SNIPPETS:
{snippets_summary}

For each entity where the applicant has a qualifying relationship, create a cluster with:
1. cluster_id: A unique identifier (e.g., "leading_venus", "member_sfba")
2. entity_name: The organization name
3. suggested_standard: Which EB-1A criterion this supports
4. snippet_ids: All snippets that support this argument
5. reasoning: Why this cluster supports the suggested standard

IMPORTANT:
- Do NOT create leading_role clusters for "partner_with" or "invited_by" relationships
- Group by entity, not by snippet
- Include ALL relevant snippets for each entity

Return your analysis as a JSON object with a "clusters" array."""


async def group_evidence(
    snippets: List[Dict],
    relationship_analysis: Dict,
    applicant_name: str,
    provider: str = "deepseek"
) -> Dict[str, Any]:
    """
    基于关系分析，将 snippets 分组为证据集群

    Args:
        snippets: 带上下文的 snippets
        relationship_analysis: 关系分析结果
        applicant_name: 申请人姓名
        provider: LLM 提供商

    Returns:
        {
            "clusters": [EvidenceCluster, ...],
            "by_standard": {standard: [clusters]},
            "stats": {...}
        }
    """
    print(f"[EvidenceGrouper] Grouping evidence for {applicant_name}...")

    relationships = relationship_analysis.get("relationships", [])
    leadership_entities = relationship_analysis.get("leadership_entities", [])
    non_leadership_entities = relationship_analysis.get("non_leadership_entities", [])

    print(f"[EvidenceGrouper] {len(snippets)} snippets, {len(relationships)} relationships")

    # 准备关系摘要
    relationships_summary = []
    for r in relationships:
        rel_type = r.get("relationship_type", "unknown")
        entity = r.get("entity_name", "")
        confidence = r.get("confidence", 0)
        qualifies = r.get("qualifies_for_leadership", False) or \
                    r.get("qualifies_for_membership", False) or \
                    r.get("qualifies_for_media", False)

        status = "[QUALIFIES]" if qualifies else "[NOT QUALIFYING]"
        relationships_summary.append(
            f"- {entity}: {rel_type} (confidence: {confidence}) {status}"
        )

    # 准备 snippets 摘要
    snippets_summary = []
    for i, s in enumerate(snippets[:60]):  # 限制数量
        snippet_id = s.get("snippet_id", f"snp_{i}")
        text = s.get("text", "")[:150]
        evidence_type = s.get("evidence_type", "")
        snippets_summary.append(f"[{snippet_id}] ({evidence_type}) {text}...")

    # 构建 prompt
    user_prompt = EVIDENCE_GROUPING_USER_PROMPT.format(
        applicant_name=applicant_name,
        relationships_summary="\n".join(relationships_summary),
        snippets_summary="\n\n".join(snippets_summary)
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=EVIDENCE_GROUPING_SYSTEM_PROMPT,
            json_schema=EVIDENCE_GROUPING_SCHEMA,
            temperature=0.1,
            max_tokens=3000
        )

        # 解析集群
        clusters = []
        by_standard = {
            "leading_role": [],
            "membership": [],
            "published_material": [],
            "awards": [],
            "original_contribution": [],
            "none": []
        }

        raw_clusters = result.get("clusters", [])

        # 如果响应格式不对，尝试备用解析
        if not raw_clusters and isinstance(result, dict):
            for key, value in result.items():
                if key != "clusters" and isinstance(value, dict):
                    raw_clusters.append({
                        "cluster_id": key,
                        "entity_name": value.get("entity_name", key),
                        "suggested_standard": value.get("suggested_standard", "none"),
                        "snippet_ids": value.get("snippet_ids", []),
                        "reasoning": value.get("reasoning", "")
                    })

        print(f"[EvidenceGrouper] Found {len(raw_clusters)} clusters")

        for c in raw_clusters:
            cluster = EvidenceCluster(
                cluster_id=c.get("cluster_id", ""),
                entity_name=c.get("entity_name", ""),
                relationship_type=_infer_relationship_type(
                    c.get("entity_name", ""),
                    relationships
                ),
                suggested_standard=c.get("suggested_standard", "none"),
                snippet_ids=c.get("snippet_ids", []),
                reasoning=c.get("reasoning", "")
            )

            # 验证集群是否真的符合标准
            cluster.qualifies = _validate_cluster_qualification(
                cluster,
                relationships,
                non_leadership_entities
            )

            clusters.append(cluster)

            # 按标准分类
            standard = cluster.suggested_standard
            if standard in by_standard and cluster.qualifies:
                by_standard[standard].append(asdict(cluster))

        # 统计
        qualified_count = sum(1 for c in clusters if c.qualifies)

        print(f"[EvidenceGrouper] Qualified clusters: {qualified_count}/{len(clusters)}")
        for std, std_clusters in by_standard.items():
            if std_clusters:
                print(f"[EvidenceGrouper]   {std}: {len(std_clusters)} clusters")

        return {
            "clusters": [asdict(c) for c in clusters],
            "by_standard": by_standard,
            "stats": {
                "total_clusters": len(clusters),
                "qualified_clusters": qualified_count,
                "leading_role": len(by_standard["leading_role"]),
                "membership": len(by_standard["membership"]),
                "published_material": len(by_standard["published_material"]),
                "awards": len(by_standard["awards"]),
                "original_contribution": len(by_standard["original_contribution"])
            }
        }

    except Exception as e:
        print(f"[EvidenceGrouper] Error: {e}")
        return {
            "clusters": [],
            "by_standard": {},
            "stats": {"error": str(e)}
        }


def _infer_relationship_type(entity_name: str, relationships: List[Dict]) -> str:
    """从关系分析中推断实体的关系类型"""
    for r in relationships:
        if r.get("entity_name", "").lower() == entity_name.lower():
            return r.get("relationship_type", "unknown")
    return "unknown"


def _validate_cluster_qualification(
    cluster: EvidenceCluster,
    relationships: List[Dict],
    non_leadership_entities: List[Dict]
) -> bool:
    """
    验证集群是否真的符合建议的标准

    关键：使用关系分析结果来验证，而不是重新判断
    """
    entity_name = cluster.entity_name.lower()
    suggested = cluster.suggested_standard

    # 检查是否在 non-leadership 列表中
    for nle in non_leadership_entities:
        if nle.get("name", "").lower() == entity_name:
            # 这个实体被标记为非领导关系
            if suggested == "leading_role":
                print(f"[EvidenceGrouper] REJECTED: {cluster.entity_name} is not a leadership entity")
                return False

    # 查找该实体的关系类型
    for r in relationships:
        if r.get("entity_name", "").lower() == entity_name:
            rel_type = r.get("relationship_type", "")

            # 验证关系类型是否支持建议的标准
            if suggested == "leading_role":
                if rel_type in ["partner_with", "invited_by"]:
                    print(f"[EvidenceGrouper] REJECTED: {cluster.entity_name} has {rel_type} relationship")
                    return False
                if rel_type not in ["founder_of", "executive_at"]:
                    # employee_at 需要进一步验证
                    if rel_type != "employee_at":
                        print(f"[EvidenceGrouper] REJECTED: {cluster.entity_name} has {rel_type}, not leadership")
                        return False

            elif suggested == "membership":
                if rel_type != "member_of":
                    print(f"[EvidenceGrouper] REJECTED: {cluster.entity_name} has {rel_type}, not membership")
                    return False

            elif suggested == "published_material":
                if rel_type != "featured_in":
                    # 但不严格拒绝，因为媒体报道可能以其他方式出现
                    pass

            break

    return True


def create_rule_based_clusters(
    snippets: List[Dict],
    relationship_analysis: Dict,
    applicant_name: str
) -> Dict[str, Any]:
    """
    基于规则的备用分组方法（不使用 LLM）

    用于：
    1. LLM 调用失败时的回退
    2. 快速测试
    3. 对比 LLM 结果
    """
    clusters = []
    by_standard = {
        "leading_role": [],
        "membership": [],
        "published_material": [],
        "awards": [],
        "original_contribution": [],
        "none": []
    }

    relationships = relationship_analysis.get("relationships", [])

    # 按实体分组 snippets
    entity_snippets = {}
    for r in relationships:
        entity_name = r.get("entity_name", "")
        evidence_snippets = r.get("evidence_snippets", [])
        rel_type = r.get("relationship_type", "")

        if entity_name:
            if entity_name not in entity_snippets:
                entity_snippets[entity_name] = {
                    "relationship_type": rel_type,
                    "snippet_ids": set(),
                    "qualifies_for_leadership": r.get("qualifies_for_leadership", False),
                    "qualifies_for_membership": r.get("qualifies_for_membership", False),
                    "qualifies_for_media": r.get("qualifies_for_media", False)
                }
            entity_snippets[entity_name]["snippet_ids"].update(evidence_snippets)

    # 创建集群
    for entity_name, data in entity_snippets.items():
        rel_type = data["relationship_type"]

        # 确定标准
        if data["qualifies_for_leadership"]:
            suggested_standard = "leading_role"
        elif data["qualifies_for_membership"]:
            suggested_standard = "membership"
        elif data["qualifies_for_media"]:
            suggested_standard = "published_material"
        elif rel_type == "awarded_by":
            suggested_standard = "awards"
        elif rel_type == "contributed_to":
            suggested_standard = "original_contribution"
        else:
            suggested_standard = "none"

        cluster = EvidenceCluster(
            cluster_id=f"cluster_{len(clusters)}",
            entity_name=entity_name,
            relationship_type=rel_type,
            suggested_standard=suggested_standard,
            snippet_ids=list(data["snippet_ids"]),
            confidence=0.8,
            reasoning=f"Based on {rel_type} relationship",
            qualifies=suggested_standard != "none"
        )

        clusters.append(cluster)

        if cluster.qualifies:
            by_standard[suggested_standard].append(asdict(cluster))

    return {
        "clusters": [asdict(c) for c in clusters],
        "by_standard": by_standard,
        "stats": {
            "total_clusters": len(clusters),
            "qualified_clusters": sum(1 for c in clusters if c.qualifies)
        }
    }
