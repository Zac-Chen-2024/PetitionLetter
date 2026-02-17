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

from .llm_client import call_openai
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
   - Determine if it's the applicant's achievement or someone else's (e.g., recommender's background)

2. **Named Entities**: People, organizations, awards, publications, positions
   - Include their IDENTITY (role/title)
   - Include their RELATIONSHIP to the applicant

3. **Relationships**: How entities relate to each other
   - Subject → Action → Object format
   - Include context

CRITICAL RULES:
- The applicant for this petition is: {applicant_name}
- For EACH snippet, you MUST identify whose achievement this is
- Recommender credentials/backgrounds are NOT applicant achievements
- Be precise with subject attribution - this determines what evidence is usable

Evidence types for EB-1A:
- award: Prizes or awards for excellence
- membership: Membership in associations requiring outstanding achievements
- publication: Published material about the person
- judging: Participation as a judge
- contribution: Original contributions of major significance
- article: Authorship of scholarly articles
- exhibition: Display of work at exhibitions
- leadership: Leading or critical role for organizations
- other: Other relevant evidence"""

UNIFIED_EXTRACTION_USER_PROMPT = """Analyze this document (Exhibit {exhibit_id}) and extract structured information.

The applicant's name is: {applicant_name}

## Document Text Blocks
Each block has format: [block_id] text content

{blocks_text}

## Instructions

Extract the following in a single JSON response:

1. **document_summary**: Brief summary of what this document is
2. **snippets**: Evidence text with SUBJECT attribution
3. **entities**: All named entities with identity and relationship to applicant
4. **relations**: Relationships between entities

For each SNIPPET, you MUST determine:
- subject: Whose achievement/credential is this? (exact name)
- subject_role: Is this person the "applicant", "recommender", "colleague", "mentor", or "other"?
- is_applicant_achievement: true ONLY if this describes the applicant's own achievement

IMPORTANT: Many recommendation letters include the recommender's credentials. These are NOT applicant achievements!
Example: "Professor John Smith, who has 30 years of experience at Stanford..." → subject="Professor John Smith", is_applicant_achievement=false"""


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
                "required": ["block_id", "text", "subject", "subject_role", "is_applicant_achievement", "evidence_type", "confidence", "reasoning"],
                "properties": {
                    "block_id": {"type": "string"},
                    "text": {"type": "string"},
                    "subject": {"type": "string", "description": "Person whose achievement this is"},
                    "subject_role": {
                        "type": "string",
                        "enum": ["applicant", "recommender", "colleague", "mentor", "other"]
                    },
                    "is_applicant_achievement": {"type": "boolean"},
                    "evidence_type": {
                        "type": "string",
                        "enum": ["award", "membership", "publication", "judging", "contribution", "article", "exhibition", "leadership", "other"]
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
    applicant_name: str
) -> Dict:
    """
    统一提取单个 exhibit 的 snippets + entities + relations

    Args:
        project_id: 项目 ID
        exhibit_id: Exhibit ID
        applicant_name: 申请人姓名

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
    model = getattr(settings, 'openai_model', 'gpt-4o')
    print(f"[UnifiedExtractor] Calling LLM ({model}) for {exhibit_id}...")

    try:
        result = await call_openai(
            prompt=user_prompt,
            model=model,
            system_prompt=system_prompt,
            json_schema=UNIFIED_EXTRACTION_SCHEMA,
            temperature=0.1,
            max_tokens=8000
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
    processed_snippets = []
    for item in raw_snippets:
        if item.get("confidence", 0) < 0.5:
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
            "is_applicant_achievement": item.get("is_applicant_achievement", True),

            # Evidence Classification
            "evidence_type": item.get("evidence_type", "other"),
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
    progress_callback=None
) -> Dict:
    """
    提取项目中所有 exhibits

    Args:
        project_id: 项目 ID
        applicant_name: 申请人姓名
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
            result = await extract_exhibit_unified(project_id, exhibit_id, applicant_name)

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
