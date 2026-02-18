"""
Unified Extractor - 统一的 Snippets + Entities + Relations 提取服务

核心改进：
1. 一次 LLM 调用同时提取 snippets + entities + relations
2. 每个 snippet 都有 subject 归属（谁的成就）
3. 每个 entity 都有 identity（身份/title）和与申请人的关系
4. 保留完整文档上下文，避免碎片化

流程：
1. 每个 exhibit 调用一次 LLM 提取
2. 所有 exhibit 完成后进行实体合并
3. 用户确认合并后生成最终关系图
"""

import json
import uuid
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

from .llm_client import call_llm
from ..core.config import settings

# 数据目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


# ==================== Data Models ====================

@dataclass
class EnhancedSnippet:
    """带有 subject 归属的 snippet"""
    snippet_id: str
    exhibit_id: str
    document_id: str
    text: str
    page: int
    bbox: Optional[Dict]
    block_id: str

    # Subject Attribution
    subject: str                      # 这是谁的成就
    subject_role: str                 # applicant/recommender/colleague/mentor/other
    is_applicant_achievement: bool    # 是否是申请人的成就

    # Evidence Classification
    evidence_type: str                # award/membership/publication/judging/contribution/article/exhibition/leadership/other
    confidence: float
    reasoning: str

    # Metadata
    is_ai_suggested: bool = True
    is_confirmed: bool = False


@dataclass
class Entity:
    """实体：人物、组织、奖项等"""
    id: str
    name: str
    type: str                         # person/organization/award/publication/position/project/event/metric
    identity: str                     # 身份描述，如 "Professor at Stanford"
    relation_to_applicant: str        # self/recommender/mentor/colleague/employer/other

    # References
    snippet_ids: List[str]
    exhibit_ids: List[str]
    mentioned_in_blocks: List[str]

    # For merging
    aliases: List[str] = None
    is_merged: bool = False
    merged_from: List[str] = None


@dataclass
class Relation:
    """实体间的关系"""
    id: str
    from_entity: str                  # entity name
    to_entity: str                    # entity name
    relation_type: str                # recommends/works_at/leads/authored/founded/member_of/received/etc
    context: str                      # 关系上下文
    source_snippet_ids: List[str]
    source_blocks: List[str]


@dataclass
class ExhibitExtraction:
    """单个 exhibit 的提取结果"""
    exhibit_id: str
    extracted_at: str
    applicant_name: str

    # Document summary
    document_type: str
    primary_subject: str
    key_themes: List[str]

    # Extracted data
    snippets: List[Dict]
    entities: List[Dict]
    relations: List[Dict]

    # Stats
    snippet_count: int
    entity_count: int
    relation_count: int


# ==================== LLM Prompts ====================

UNIFIED_EXTRACTION_SYSTEM_PROMPT = """You are an expert immigration attorney assistant specializing in EB-1A visa petitions.

Your task is to analyze a document and extract THREE types of information:

1. **Evidence Snippets**: Text excerpts that can support an EB-1A petition
   - Each snippet MUST have a SUBJECT: the person whose achievement/credential this describes
   - CRITICAL: Consider DOCUMENT CONTEXT when determining is_applicant_achievement:
     * If document is ABOUT the applicant (news article, media coverage, recommendation letter praising them),
       then text describing the applicant's achievements IS is_applicant_achievement=true
     * Recommender's OWN background ("I have 30 years at Stanford") = is_applicant_achievement=false
     * But recommender CONFIRMING applicant's work ("The applicant did X") = is_applicant_achievement=true

2. **Named Entities**: People, organizations, awards, publications, positions
   - Include their IDENTITY (role/title)
   - Include their RELATIONSHIP to the applicant
   - For recommendation letters, note who the recommender is

3. **Relationships**: How entities relate to each other
   - Subject → Action → Object format
   - Include context
   - If in a recommendation/evaluation, note who did the evaluation

CRITICAL RULES:
- The applicant for this petition is: {applicant_name}
- NAME ALIASES: The applicant may appear under DIFFERENT NAMES in documents:
  * English name vs Chinese name (e.g., "John Smith" = "约翰·史密斯")
  * First name only, last name only, or nickname
  * If document is ABOUT someone with SAME SURNAME as applicant and matching context, treat as applicant
  * Example: If applicant is "John Smith", then "John founded XYZ Company" in a media article = applicant's achievement
- DOCUMENT CONTEXT MATTERS: A media article about the applicant = applicant's achievement evidence
- A recommendation letter confirming "applicant did X" = applicant achievement (recommender confirms it)
- Recommender's OWN credentials ("I have PhD from Harvard") = NOT applicant achievement
- Extract ALL supporting context, including:
  * Membership criteria and evaluation process (proves selectivity)
  * Media outlet credentials (proves "major" publication)
  * Organization reputation (proves "distinguished" organization)
- Do NOT skip low-confidence items - include them with appropriate confidence scores

Evidence types for EB-1A:
- award: Prizes or awards for excellence
- membership: Membership in associations requiring outstanding achievements
- membership_criteria: Criteria showing selective membership requirements
- membership_evaluation: Formal evaluation/assessment leading to membership
- peer_assessment: Expert peer evaluation of the applicant's work
- publication: Published material about the person (scholarly)
- media_coverage: News articles or media mentions about the applicant
- judging: Participation as a judge
- contribution: Original contributions of major significance
- article: Authorship of scholarly articles
- exhibition: Display of work at exhibitions
- leadership: Leading or critical role for organizations
- recommendation: Recommendation or endorsement from recognized expert
- peer_achievement: Achievements of OTHER members/peers (proves selectivity of group)
- source_credibility: Credentials of media/organization (proves "major" or "distinguished")
- quantitative_impact: Metrics, numbers, statistics showing impact
- other: Other relevant evidence

CRITICAL - Evidence Purpose (WHY this evidence matters):
- direct_proof: Directly proves applicant's achievement (e.g., "Applicant founded X")
- selectivity_proof: Proves selectivity/prestige of association/award (e.g., "Other members include Olympic champions")
- credibility_proof: Proves credibility of source (e.g., "Newspaper has circulation of 40,000")
- impact_proof: Proves quantitative impact (e.g., "100,000 page views", "trained 200,000 coaches")

===== SIGNIFICANCE LAYER EXTRACTION (CRITICAL - Most Commonly Missed!) =====

The SIGNIFICANCE layer answers: "WHY does this evidence matter?" - This is what separates approved petitions from RFEs!

MUST EXTRACT these patterns:

1. QUANTITATIVE DATA (impact_proof):
   - Numbers with units: "40,000 copies", "100,000 views", "200,000 coaches", "5,000,000 participants"
   - Percentages: "top 5%", "only 10% accepted"
   - Currency: "$1M revenue", "¥500万"
   - Counts: "300 athletes from 10 countries", "14 branch stores"
   Pattern: Look for numbers followed by units (copies, views, users, coaches, athletes, participants, stores, countries)

2. ORGANIZATION REPUTATION (credibility_proof):
   - Credit ratings: "AAA credit rating", "信用等级AAA"
   - Official status: "official partner of", "national association", "government-affiliated"
   - Awards to organization: "won Adam Malik Award", "received IMPA award"
   - Rankings: "leading", "top", "largest", "most influential"
   Pattern: Look for ratings, "official", "national", "leading", organization awards

3. PEER ACHIEVEMENTS (selectivity_proof):
   - Other members' credentials: "members include Olympic champion", "other recipients include Nobel laureate"
   - Competition level: "competed against 500 applicants", "selected from 1000 candidates"
   - Evaluator credentials: "reviewed by Vice President", "evaluated by industry experts"
   Pattern: Look for "members include", "other recipients", "reviewed by", prominent titles

4. MEDIA CREDENTIALS (credibility_proof):
   - Circulation data: "circulation of 40,000", "200,000 weekly copies"
   - Media awards: "won journalism award", "received press award"
   - Media ownership: "owned by [parent media group]", "subsidiary of [corporation]"
   - Media reputation: "leading newspaper", "largest English daily", "national publication"
   Pattern: Look for circulation numbers, media awards, ownership info, "leading"/"largest"

IMPORTANT: Extract BOTH direct evidence AND supporting evidence that proves WHY the direct evidence matters!
DO NOT SKIP significance evidence - it is what proves "major", "distinguished", "outstanding" for USCIS!"""

UNIFIED_EXTRACTION_USER_PROMPT = """Analyze this document (Exhibit {exhibit_id}) and extract structured information.

The applicant's name is: {applicant_name}

## Step 1: Identify Document Context and Applicant Names
First, determine: What is the PRIMARY PURPOSE of this document?
- Recommendation letter FOR {applicant_name}? (recommender praises applicant)
- Media coverage / news article ABOUT {applicant_name}?
- Official certification/membership document FOR {applicant_name}?
- Resume or CV of {applicant_name}?
- Third-party background information?

IMPORTANT - Check for NAME ALIASES:
- The applicant "{applicant_name}" may appear under DIFFERENT NAMES:
  * English name vs Chinese name (or other language variations)
  * Abbreviated name, nickname, or title (Dr., Prof., Coach, etc.)
  * Same surname with similar context = likely the applicant
- If document is about someone with SAME SURNAME as "{applicant_name}" and the document is exhibit evidence for this applicant, treat that person AS the applicant.

This context determines how to classify is_applicant_achievement.

## Document Text Blocks
Each block has format: [block_id] text content

{blocks_text}

## Instructions

Extract the following in a single JSON response:

1. **document_summary**: Identify document type and primary subject
2. **snippets**: Evidence text with SUBJECT attribution
3. **entities**: All named entities with identity and relationship to applicant
4. **relations**: Relationships between entities

For each SNIPPET, you MUST determine:
- subject: Whose achievement/credential is this? (exact name or "{applicant_name}")
- subject_role: "applicant", "recommender", "evaluator", "colleague", "mentor", "peer", "organization", or "other"
- recommender_name: If this is from a recommendation/evaluation, who is the recommender?
- is_applicant_achievement:
  * TRUE if: subject is applicant, OR document is ABOUT applicant and confirms their achievement
  * TRUE ALSO if: evidence SUPPORTS applicant's case (selectivity proof, credibility proof, impact proof)
  * FALSE only if: someone else's OWN background completely unrelated to applicant's case
- evidence_type: Choose MOST SPECIFIC type (see system prompt for full list)
- evidence_purpose: WHY does this evidence matter?
  * "direct_proof" - Directly proves applicant's achievement
  * "selectivity_proof" - Proves selectivity/prestige (other members' achievements, strict criteria)
  * "credibility_proof" - Proves source credibility (media circulation, organization reputation)
  * "impact_proof" - Proves quantitative impact (page views, user counts, revenue)

CRITICAL EXAMPLES:

1. DIRECT PROOF - Recommendation letter says "The applicant revolutionized X":
   → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_purpose="direct_proof"

2. NOT APPLICANT - Recommender says "I (Dr. Smith) have 20 years at Stanford":
   → subject="Dr. Smith", is_applicant_achievement=FALSE (recommender's own background)

3. DIRECT PROOF - News article says "{applicant_name} founded [company/organization]":
   → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="media_coverage", evidence_purpose="direct_proof"

4. SELECTIVITY PROOF - Membership document says "Other members include Olympic gold medalist Ping Zhang":
   → subject="Ping Zhang", is_applicant_achievement=TRUE, evidence_type="peer_achievement", evidence_purpose="selectivity_proof"
   → This PROVES the association is selective, which supports applicant's membership!

5. SELECTIVITY PROOF - "Membership requires 10 years experience and outstanding achievements":
   → subject="the association", is_applicant_achievement=TRUE, evidence_type="membership_criteria", evidence_purpose="selectivity_proof"

6. CREDIBILITY PROOF - "[Publication name] has circulation of X and won [journalism award]":
   → subject="[publication]", is_applicant_achievement=TRUE, evidence_type="source_credibility", evidence_purpose="credibility_proof"
   → This PROVES the publication is "major media", which supports applicant's media coverage!

7. IMPACT PROOF - "The courses received 100,000 page views and trained 200,000 coaches":
   → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="quantitative_impact", evidence_purpose="impact_proof"

8. CREDIBILITY PROOF - "Company has AAA credit rating":
   → subject="the company", is_applicant_achievement=TRUE, evidence_type="source_credibility", evidence_purpose="credibility_proof"
   → This PROVES the organization is "distinguished", which supports applicant's leading role!

9. IMPACT PROOF - "5,000,000 people participated in the event":
   → subject="the event", is_applicant_achievement=TRUE, evidence_type="quantitative_impact", evidence_purpose="impact_proof"
   → This PROVES the scale of applicant's leadership impact!

10. IMPACT PROOF - "300 athletes from 10 countries competed":
    → subject="the competition", is_applicant_achievement=TRUE, evidence_type="quantitative_impact", evidence_purpose="impact_proof"
    → This PROVES international reach and significance!

11. CREDIBILITY PROOF - "weekly circulation of 200,000 copies":
    → subject="the publication", is_applicant_achievement=TRUE, evidence_type="source_credibility", evidence_purpose="credibility_proof"

12. SELECTIVITY PROOF - "membership requires 10 years experience and review by board of directors":
    → subject="the association", is_applicant_achievement=TRUE, evidence_type="membership_criteria", evidence_purpose="selectivity_proof"

CRITICAL EXTRACTION PATTERNS for SIGNIFICANCE layer:
- Numbers + units: "40,000 copies", "100,000 views", "5M participants", "14 stores", "10 countries"
- Ratings: "AAA", "credit rating", "信用等级"
- Awards to organizations: "won ... Award", "received ... prize"
- Peer credentials: "members include", "other recipients", "Olympic", "champion", "gold medal"
- Media rankings: "leading", "top", "largest", "most", "first"

CRITICAL: Extract BOTH direct evidence AND supporting evidence!
- Direct evidence: What the applicant did
- Supporting evidence: Why it matters (selectivity, credibility, impact)
Do NOT skip supporting evidence - it is ESSENTIAL for EB-1A petitions!"""


UNIFIED_EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["document_summary", "snippets", "entities", "relations"],
    "properties": {
        "document_summary": {
            "type": "object",
            "required": ["document_type", "primary_subject", "key_themes"],
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "Type: resume, recommendation_letter, award_certificate, publication, media_article, other"
                },
                "primary_subject": {
                    "type": "string",
                    "description": "Main person this document is about"
                },
                "key_themes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key themes or topics"
                }
            },
            "additionalProperties": False
        },
        "snippets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "text", "subject", "subject_role", "recommender_name", "is_applicant_achievement", "evidence_type", "evidence_purpose", "evidence_layer", "confidence", "reasoning"],
                "properties": {
                    "block_id": {"type": "string"},
                    "text": {"type": "string"},
                    "subject": {"type": "string", "description": "Person whose achievement this is"},
                    "subject_role": {
                        "type": "string",
                        "enum": ["applicant", "recommender", "evaluator", "colleague", "mentor", "peer", "organization", "other"]
                    },
                    "recommender_name": {
                        "type": ["string", "null"],
                        "description": "If from recommendation/evaluation, who is the recommender/evaluator? Use null if not applicable."
                    },
                    "is_applicant_achievement": {"type": "boolean"},
                    "evidence_type": {
                        "type": "string",
                        "enum": [
                            "award",
                            "membership",
                            "membership_criteria",
                            "membership_evaluation",
                            "peer_assessment",
                            "peer_achievement",
                            "publication",
                            "media_coverage",
                            "source_credibility",
                            "quantitative_impact",
                            "judging",
                            "contribution",
                            "article",
                            "exhibition",
                            "leadership",
                            "recommendation",
                            "other"
                        ]
                    },
                    "evidence_purpose": {
                        "type": "string",
                        "enum": ["direct_proof", "selectivity_proof", "credibility_proof", "impact_proof"],
                        "description": "WHY this evidence matters: direct_proof (applicant achievement), selectivity_proof (proves selectivity), credibility_proof (proves source credibility), impact_proof (proves quantitative impact)"
                    },
                    "evidence_layer": {
                        "type": "string",
                        "enum": ["claim", "proof", "significance", "context"],
                        "description": "Evidence pyramid layer: claim (what applicant did), proof (how to prove), significance (why it matters - MOST IMPORTANT), context (background)"
                    },
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"}
                },
                "additionalProperties": False
            }
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "identity", "relation_to_applicant", "mentioned_in_blocks"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["person", "organization", "award", "publication", "position", "project", "event", "metric"]
                    },
                    "identity": {"type": "string", "description": "Role/title/description"},
                    "relation_to_applicant": {
                        "type": "string",
                        "enum": ["self", "recommender", "mentor", "colleague", "employer", "organization", "award_giver", "other"]
                    },
                    "mentioned_in_blocks": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "additionalProperties": False
            }
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from_entity", "relation_type", "to_entity", "context", "source_blocks"],
                "properties": {
                    "from_entity": {"type": "string"},
                    "relation_type": {"type": "string"},
                    "to_entity": {"type": "string"},
                    "context": {"type": "string"},
                    "source_blocks": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "additionalProperties": False
            }
        }
    },
    "additionalProperties": False
}


# ==================== Helper Functions ====================

def generate_snippet_id(exhibit_id: str, block_id: str) -> str:
    """生成唯一 snippet ID"""
    unique_suffix = uuid.uuid4().hex[:8]
    return f"snp_{exhibit_id}_{block_id}_{unique_suffix}"


def generate_entity_id(exhibit_id: str, index: int) -> str:
    """生成唯一 entity ID"""
    return f"ent_{exhibit_id}_{index}"


def generate_relation_id(exhibit_id: str, index: int) -> str:
    """生成唯一 relation ID"""
    return f"rel_{exhibit_id}_{index}"


def _infer_evidence_layer(item: Dict) -> str:
    """根据 evidence_purpose 和 evidence_type 推断证据层级"""
    purpose = item.get("evidence_purpose", "direct_proof")
    etype = item.get("evidence_type", "other")

    # significance 层：selectivity/credibility/impact proof
    if purpose in ["selectivity_proof", "credibility_proof", "impact_proof"]:
        return "significance"

    # significance 层的证据类型
    if etype in ["peer_achievement", "source_credibility", "quantitative_impact", "membership_criteria"]:
        return "significance"

    # proof 层：证明申请人的声明
    if etype in ["award", "membership_evaluation", "peer_assessment", "recommendation"]:
        return "proof"

    # context 层：背景信息
    if etype in ["other"]:
        return "context"

    # 默认 claim 层：直接声明
    return "claim"


def format_blocks_for_llm(pages: List[Dict]) -> Tuple[str, Dict]:
    """将所有页的 blocks 格式化为 LLM 输入格式

    Returns:
        tuple: (blocks_text, block_map)
            - blocks_text: 格式化后的文本
            - block_map: {composite_id -> (page_num, block)} 的映射
    """
    lines = []
    block_map = {}

    for page_data in pages:
        page_num = page_data.get("page_number", 0)
        blocks = page_data.get("text_blocks", [])

        for block in blocks:
            block_id = block.get("block_id", "")
            text = block.get("text_content", "").strip()

            # 跳过空文本或太短的文本
            if not text or len(text) < 5:
                continue

            # 复合 ID: p{页码}_{block_id}
            composite_id = f"p{page_num}_{block_id}"
            block_map[composite_id] = (page_num, block)
            lines.append(f"[{composite_id}] {text}")

    return "\n".join(lines), block_map


def get_extraction_dir(project_id: str) -> Path:
    """获取提取结果目录"""
    extraction_dir = PROJECTS_DIR / project_id / "extraction"
    extraction_dir.mkdir(parents=True, exist_ok=True)
    return extraction_dir


def get_entities_dir(project_id: str) -> Path:
    """获取实体目录"""
    entities_dir = PROJECTS_DIR / project_id / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    return entities_dir


# ==================== Core Functions ====================

async def extract_exhibit_unified(
    project_id: str,
    exhibit_id: str,
    applicant_name: str,
    provider: str = "deepseek"
) -> Dict:
    """
    统一提取单个 exhibit 的 snippets + entities + relations

    Args:
        project_id: 项目 ID
        exhibit_id: Exhibit ID
        applicant_name: 申请人姓名
        provider: LLM 提供商 ("deepseek" 或 "openai")

    Returns:
        提取结果 dict
    """
    # 1. 加载文档
    doc_path = PROJECTS_DIR / project_id / "documents" / f"{exhibit_id}.json"
    if not doc_path.exists():
        raise FileNotFoundError(f"Document not found: {doc_path}")

    with open(doc_path, 'r', encoding='utf-8') as f:
        doc_data = json.load(f)

    pages = doc_data.get("pages", [])
    if not pages:
        return {
            "success": False,
            "error": f"No pages in exhibit {exhibit_id}",
            "exhibit_id": exhibit_id
        }

    print(f"[UnifiedExtractor] Processing exhibit {exhibit_id} ({len(pages)} pages)...")

    # 2. 格式化 blocks
    blocks_text, block_map = format_blocks_for_llm(pages)

    if not blocks_text or len(blocks_text) < 50:
        return {
            "success": False,
            "error": f"Not enough text content in {exhibit_id}",
            "exhibit_id": exhibit_id
        }

    # 3. 构建 prompt
    system_prompt = UNIFIED_EXTRACTION_SYSTEM_PROMPT.format(applicant_name=applicant_name)
    user_prompt = UNIFIED_EXTRACTION_USER_PROMPT.format(
        exhibit_id=exhibit_id,
        applicant_name=applicant_name,
        blocks_text=blocks_text
    )

    # 4. 调用 LLM
    print(f"[UnifiedExtractor] Calling LLM ({provider}) for {exhibit_id}...")

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=system_prompt,
            json_schema=UNIFIED_EXTRACTION_SCHEMA,
            temperature=0.2,   # 提高到 0.2：允许更多变化，更好地识别上下文
            max_tokens=10000   # 增加到 10000：允许更详细的输出
        )
    except Exception as e:
        print(f"[UnifiedExtractor] LLM error for {exhibit_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "exhibit_id": exhibit_id
        }

    # 5. 处理结果
    document_summary = result.get("document_summary", {})
    raw_snippets = result.get("snippets", [])
    raw_entities = result.get("entities", [])
    raw_relations = result.get("relations", [])

    # 6. 处理 snippets - 添加 ID 和 bbox
    # 使用分层置信度阈值：支持性内容（如 membership_criteria）用更低阈值
    CONFIDENCE_THRESHOLDS = {
        "award": 0.5,
        "membership": 0.4,
        "membership_criteria": 0.3,      # 低阈值：标准描述都重要
        "membership_evaluation": 0.3,    # 低阈值：评估过程都重要
        "peer_assessment": 0.3,          # 低阈值：同行评价都有意义
        "media_coverage": 0.4,
        "recommendation": 0.4,
        "contribution": 0.4,
        "leadership": 0.4,
    }
    DEFAULT_THRESHOLD = 0.35  # 默认阈值从 0.5 降低到 0.35

    processed_snippets = []
    for item in raw_snippets:
        evidence_type = item.get("evidence_type", "other")
        threshold = CONFIDENCE_THRESHOLDS.get(evidence_type, DEFAULT_THRESHOLD)

        if item.get("confidence", 0) < threshold:
            continue

        composite_id = item.get("block_id", "")
        page_block = block_map.get(composite_id)

        if not page_block:
            print(f"[Warning] Block '{composite_id}' not found in {exhibit_id}, skipping")
            continue

        page_num, block = page_block
        original_block_id = block.get("block_id", "")

        snippet_id = generate_snippet_id(exhibit_id, composite_id)

        processed_snippets.append({
            "snippet_id": snippet_id,
            "exhibit_id": exhibit_id,
            "document_id": f"doc_{exhibit_id}",
            "text": item.get("text", ""),
            "page": page_num,
            "bbox": block.get("bbox"),
            "block_id": original_block_id,

            # Subject Attribution
            "subject": item.get("subject", applicant_name),
            "subject_role": item.get("subject_role", "applicant"),
            "recommender_name": item.get("recommender_name"),  # 新增：推荐人名称
            "is_applicant_achievement": item.get("is_applicant_achievement", True),

            # Evidence Classification
            "evidence_type": item.get("evidence_type", "other"),
            "evidence_purpose": item.get("evidence_purpose", "direct_proof"),  # 证据目的
            "evidence_layer": item.get("evidence_layer", _infer_evidence_layer(item)),  # 证据层级
            "confidence": item.get("confidence", 0.5),
            "reasoning": item.get("reasoning", ""),

            # Metadata
            "is_ai_suggested": True,
            "is_confirmed": False
        })

    # 7. 处理 entities - 添加 ID
    processed_entities = []
    for idx, item in enumerate(raw_entities):
        entity_id = generate_entity_id(exhibit_id, idx)
        processed_entities.append({
            "id": entity_id,
            "name": item.get("name", ""),
            "type": item.get("type", "other"),
            "identity": item.get("identity", ""),
            "relation_to_applicant": item.get("relation_to_applicant", "other"),
            "snippet_ids": [],  # 将在后处理中填充
            "exhibit_ids": [exhibit_id],
            "mentioned_in_blocks": item.get("mentioned_in_blocks", []),
            "aliases": [],
            "is_merged": False,
            "merged_from": []
        })

    # 8. 处理 relations - 添加 ID
    processed_relations = []
    for idx, item in enumerate(raw_relations):
        relation_id = generate_relation_id(exhibit_id, idx)
        processed_relations.append({
            "id": relation_id,
            "from_entity": item.get("from_entity", ""),
            "to_entity": item.get("to_entity", ""),
            "relation_type": item.get("relation_type", ""),
            "context": item.get("context", ""),
            "source_snippet_ids": [],  # 将在后处理中填充
            "source_blocks": item.get("source_blocks", [])
        })

    # 9. 保存提取结果
    extraction_result = {
        "version": "4.0",
        "exhibit_id": exhibit_id,
        "extracted_at": datetime.now().isoformat(),
        "applicant_name": applicant_name,

        "document_summary": document_summary,

        "snippets": processed_snippets,
        "entities": processed_entities,
        "relations": processed_relations,

        "stats": {
            "snippet_count": len(processed_snippets),
            "entity_count": len(processed_entities),
            "relation_count": len(processed_relations),
            "applicant_snippets": sum(1 for s in processed_snippets if s.get("is_applicant_achievement")),
            "other_snippets": sum(1 for s in processed_snippets if not s.get("is_applicant_achievement"))
        }
    }

    # 保存到文件
    extraction_dir = get_extraction_dir(project_id)
    extraction_file = extraction_dir / f"{exhibit_id}_extraction.json"
    with open(extraction_file, 'w', encoding='utf-8') as f:
        json.dump(extraction_result, f, ensure_ascii=False, indent=2)

    print(f"[UnifiedExtractor] {exhibit_id}: {len(processed_snippets)} snippets, {len(processed_entities)} entities, {len(processed_relations)} relations")

    return {
        "success": True,
        "exhibit_id": exhibit_id,
        **extraction_result["stats"]
    }


async def extract_all_unified(
    project_id: str,
    applicant_name: str,
    provider: str = "deepseek",
    progress_callback=None
) -> Dict:
    """
    提取项目中所有 exhibits

    Args:
        project_id: 项目 ID
        applicant_name: 申请人姓名
        provider: LLM 提供商 ("deepseek" 或 "openai")
        progress_callback: 进度回调 (current, total, message)

    Returns:
        提取结果汇总
    """
    documents_dir = PROJECTS_DIR / project_id / "documents"

    if not documents_dir.exists():
        return {
            "success": False,
            "error": "Documents directory not found"
        }

    exhibit_files = list(documents_dir.glob("*.json"))
    total_exhibits = len(exhibit_files)

    print(f"[UnifiedExtractor] Starting extraction for {total_exhibits} exhibits, applicant: {applicant_name}")

    all_snippets = []
    all_entities = []
    all_relations = []

    successful = 0
    failed = 0

    for idx, exhibit_file in enumerate(exhibit_files):
        exhibit_id = exhibit_file.stem

        if progress_callback:
            progress_callback(idx, total_exhibits, f"Extracting {exhibit_id}...")

        try:
            result = await extract_exhibit_unified(project_id, exhibit_id, applicant_name, provider=provider)

            if result.get("success"):
                successful += 1

                # 加载提取结果
                extraction_file = get_extraction_dir(project_id) / f"{exhibit_id}_extraction.json"
                if extraction_file.exists():
                    with open(extraction_file, 'r', encoding='utf-8') as f:
                        extraction_data = json.load(f)

                    all_snippets.extend(extraction_data.get("snippets", []))
                    all_entities.extend(extraction_data.get("entities", []))
                    all_relations.extend(extraction_data.get("relations", []))
            else:
                failed += 1
                print(f"[UnifiedExtractor] Failed to extract {exhibit_id}: {result.get('error')}")

        except Exception as e:
            failed += 1
            print(f"[UnifiedExtractor] Exception extracting {exhibit_id}: {e}")

    if progress_callback:
        progress_callback(total_exhibits, total_exhibits, "Saving combined results...")

    # 保存合并后的结果
    combined_result = {
        "version": "4.0",
        "extracted_at": datetime.now().isoformat(),
        "applicant_name": applicant_name,
        "exhibit_count": total_exhibits,
        "successful": successful,
        "failed": failed,

        "snippets": all_snippets,
        "entities": all_entities,
        "relations": all_relations,

        "stats": {
            "total_snippets": len(all_snippets),
            "total_entities": len(all_entities),
            "total_relations": len(all_relations),
            "applicant_snippets": sum(1 for s in all_snippets if s.get("is_applicant_achievement")),
            "other_snippets": sum(1 for s in all_snippets if not s.get("is_applicant_achievement"))
        }
    }

    # 保存合并结果
    extraction_dir = get_extraction_dir(project_id)
    combined_file = extraction_dir / "combined_extraction.json"
    with open(combined_file, 'w', encoding='utf-8') as f:
        json.dump(combined_result, f, ensure_ascii=False, indent=2)

    # 同时保存到 snippets 目录（兼容现有代码）
    snippets_dir = PROJECTS_DIR / project_id / "snippets"
    snippets_dir.mkdir(parents=True, exist_ok=True)
    snippets_file = snippets_dir / "extracted_snippets.json"

    snippets_data = {
        "version": "4.0",
        "extracted_at": datetime.now().isoformat(),
        "snippet_count": len(all_snippets),
        "extraction_method": "unified_extraction",
        "model": getattr(settings, 'openai_model', 'gpt-4o'),
        "snippets": all_snippets
    }

    with open(snippets_file, 'w', encoding='utf-8') as f:
        json.dump(snippets_data, f, ensure_ascii=False, indent=2)

    print(f"[UnifiedExtractor] Complete: {successful}/{total_exhibits} exhibits, {len(all_snippets)} snippets, {len(all_entities)} entities")

    return {
        "success": True,
        "exhibit_count": total_exhibits,
        "successful": successful,
        "failed": failed,
        **combined_result["stats"]
    }


def load_combined_extraction(project_id: str) -> Optional[Dict]:
    """加载合并后的提取结果"""
    combined_file = get_extraction_dir(project_id) / "combined_extraction.json"
    if combined_file.exists():
        with open(combined_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def load_exhibit_extraction(project_id: str, exhibit_id: str) -> Optional[Dict]:
    """加载单个 exhibit 的提取结果"""
    extraction_file = get_extraction_dir(project_id) / f"{exhibit_id}_extraction.json"
    if extraction_file.exists():
        with open(extraction_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def get_extraction_status(project_id: str) -> Dict:
    """获取提取状态"""
    extraction_dir = get_extraction_dir(project_id)
    documents_dir = PROJECTS_DIR / project_id / "documents"

    # 统计已提取的 exhibits
    extracted_exhibits = []
    if extraction_dir.exists():
        for f in extraction_dir.glob("*_extraction.json"):
            exhibit_id = f.stem.replace("_extraction", "")
            extracted_exhibits.append(exhibit_id)

    # 统计所有 exhibits
    all_exhibits = []
    if documents_dir.exists():
        all_exhibits = [f.stem for f in documents_dir.glob("*.json")]

    # 检查合并结果
    combined_file = extraction_dir / "combined_extraction.json"
    has_combined = combined_file.exists()

    combined_stats = None
    if has_combined:
        with open(combined_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            combined_stats = data.get("stats")

    return {
        "total_exhibits": len(all_exhibits),
        "extracted_exhibits": len(extracted_exhibits),
        "extracted_exhibit_ids": extracted_exhibits,
        "pending_exhibits": [e for e in all_exhibits if e not in extracted_exhibits],
        "has_combined_extraction": has_combined,
        "combined_stats": combined_stats
    }
