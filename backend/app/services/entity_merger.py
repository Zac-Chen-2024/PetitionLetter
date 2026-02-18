"""
Entity Merger - 实体合并服务

功能：
1. 收集所有 exhibits 中提取的实体
2. 使用 LLM 识别同一实体的不同称呼
3. 生成合并建议供用户确认
4. 应用合并更新所有引用

流程：
1. suggest_entity_merges() - 生成合并建议
2. 用户通过 UI 确认/拒绝
3. apply_entity_merges() - 应用已确认的合并
"""

import json
import uuid
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

from .llm_client import call_llm
from .unified_extractor import (
    get_extraction_dir,
    get_entities_dir,
    load_combined_extraction,
    PROJECTS_DIR
)
from ..core.config import settings


# ==================== Data Models ====================

@dataclass
class MergeSuggestion:
    """合并建议"""
    id: str
    primary_entity_name: str          # 主实体名称
    primary_entity_type: str          # 主实体类型
    merge_entity_names: List[str]     # 要合并的实体名称
    reason: str                       # 合并原因
    confidence: float                 # 置信度
    status: str = "pending"           # pending/accepted/rejected


@dataclass
class MergeRecord:
    """合并记录"""
    id: str
    primary_entity_name: str
    merged_entity_names: List[str]
    merge_reason: str
    is_ai_suggested: bool
    created_at: str
    confirmed_at: Optional[str] = None
    confirmed_by: str = "user"


# ==================== LLM Prompts ====================

MERGE_SUGGESTION_SYSTEM_PROMPT = """You are an expert at entity resolution and name matching.

Your task is to identify entities that refer to the SAME real-world person, organization, or thing, but with different names or spellings.

RULES:
1. Only merge entities that clearly refer to the SAME thing
2. Consider:
   - Name variations (formal vs informal): "Dr. John Smith" = "John Smith" = "J. Smith"
   - Abbreviations: "Massachusetts Institute of Technology" = "MIT"
   - Titles: "Professor John Smith" = "Dr. John Smith" = "John Smith"
   - Nicknames: "[Full Name]" = "[Nickname]" = "Coach [Name]"
3. DO NOT merge:
   - Different people with similar names
   - Parent and child organizations
   - Different awards/publications with similar names

The applicant's name is: {applicant_name}
Pay special attention to variations of the applicant's name."""

MERGE_SUGGESTION_USER_PROMPT = """Analyze these entities extracted from EB-1A petition documents and identify which ones refer to the SAME real-world entity.

## Entities (grouped by type)

{entities_text}

## Instructions

For each group of entities that should be merged:
1. Choose the most formal/complete name as the PRIMARY entity
2. List all other names as MERGE targets
3. Explain WHY they are the same entity

Return JSON format:
{{
  "merge_suggestions": [
    {{
      "primary_name": "The most formal name",
      "merge_names": ["alias1", "alias2"],
      "entity_type": "person|organization|...",
      "reason": "Why these are the same",
      "confidence": 0.9
    }}
  ]
}}

If no merges are needed, return {{"merge_suggestions": []}}"""


MERGE_SUGGESTION_SCHEMA = {
    "type": "object",
    "required": ["merge_suggestions"],
    "properties": {
        "merge_suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["primary_name", "merge_names", "entity_type", "reason", "confidence"],
                "properties": {
                    "primary_name": {"type": "string"},
                    "merge_names": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "entity_type": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"}
                },
                "additionalProperties": False
            }
        }
    },
    "additionalProperties": False
}


# ==================== Core Functions ====================

async def suggest_entity_merges(
    project_id: str,
    applicant_name: str,
    provider: str = "deepseek"
) -> List[Dict]:
    """
    生成实体合并建议

    Args:
        project_id: 项目 ID
        applicant_name: 申请人姓名
        provider: LLM 提供商 ("deepseek" 或 "openai")

    Returns:
        合并建议列表
    """
    # 1. 加载合并后的提取结果
    combined = load_combined_extraction(project_id)
    if not combined:
        return []

    entities = combined.get("entities", [])
    if not entities:
        return []

    print(f"[EntityMerger] Analyzing {len(entities)} entities for merges...")

    # 2. 按类型分组实体
    entities_by_type = {}
    for e in entities:
        entity_type = e.get("type", "other")
        if entity_type not in entities_by_type:
            entities_by_type[entity_type] = []
        entities_by_type[entity_type].append(e)

    # 3. 格式化为 LLM 输入
    entities_text = ""
    for entity_type, type_entities in entities_by_type.items():
        entities_text += f"\n### {entity_type.upper()} ({len(type_entities)} entities)\n"
        for e in type_entities:
            identity = e.get("identity", "")
            relation = e.get("relation_to_applicant", "")
            exhibits = ", ".join(e.get("exhibit_ids", []))
            entities_text += f"- {e['name']}"
            if identity:
                entities_text += f" | {identity}"
            if relation:
                entities_text += f" | relation: {relation}"
            entities_text += f" | exhibits: {exhibits}\n"

    # 4. 调用 LLM
    system_prompt = MERGE_SUGGESTION_SYSTEM_PROMPT.format(applicant_name=applicant_name)
    user_prompt = MERGE_SUGGESTION_USER_PROMPT.format(entities_text=entities_text)

    print(f"[EntityMerger] Calling LLM ({provider}) for merge suggestions...")

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=system_prompt,
            json_schema=MERGE_SUGGESTION_SCHEMA,
            temperature=0.1,
            max_tokens=4000
        )
    except Exception as e:
        print(f"[EntityMerger] LLM error: {e}")
        return []

    # 5. 处理结果
    raw_suggestions = result.get("merge_suggestions", [])
    suggestions = []

    for idx, s in enumerate(raw_suggestions):
        if s.get("confidence", 0) < 0.7:
            continue

        suggestion = {
            "id": f"merge_{uuid.uuid4().hex[:8]}",
            "primary_entity_name": s.get("primary_name", ""),
            "primary_entity_type": s.get("entity_type", "other"),
            "merge_entity_names": s.get("merge_names", []),
            "reason": s.get("reason", ""),
            "confidence": s.get("confidence", 0.8),
            "status": "pending"
        }
        suggestions.append(suggestion)

    # 6. 保存合并建议
    entities_dir = get_entities_dir(project_id)
    suggestions_file = entities_dir / "merge_suggestions.json"

    suggestions_data = {
        "generated_at": datetime.now().isoformat(),
        "applicant_name": applicant_name,
        "total_entities": len(entities),
        "suggestions": suggestions
    }

    with open(suggestions_file, 'w', encoding='utf-8') as f:
        json.dump(suggestions_data, f, ensure_ascii=False, indent=2)

    print(f"[EntityMerger] Generated {len(suggestions)} merge suggestions")

    return suggestions


def load_merge_suggestions(project_id: str) -> List[Dict]:
    """加载合并建议"""
    suggestions_file = get_entities_dir(project_id) / "merge_suggestions.json"
    if suggestions_file.exists():
        with open(suggestions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("suggestions", [])
    return []


def update_merge_suggestion_status(
    project_id: str,
    suggestion_id: str,
    status: str
) -> bool:
    """更新合并建议状态"""
    suggestions_file = get_entities_dir(project_id) / "merge_suggestions.json"
    if not suggestions_file.exists():
        return False

    with open(suggestions_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    suggestions = data.get("suggestions", [])
    updated = False

    for s in suggestions:
        if s.get("id") == suggestion_id:
            s["status"] = status
            s["updated_at"] = datetime.now().isoformat()
            updated = True
            break

    if updated:
        with open(suggestions_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return updated


def apply_entity_merges(project_id: str) -> Dict:
    """
    应用已确认的合并

    这会更新：
    1. combined_extraction.json 中的 entities
    2. 所有 snippet 的 subject 字段
    3. 所有 relation 的 entity 引用

    Returns:
        应用结果统计
    """
    # 1. 加载合并建议
    suggestions = load_merge_suggestions(project_id)
    accepted_merges = [s for s in suggestions if s.get("status") == "accepted"]

    if not accepted_merges:
        return {
            "success": True,
            "message": "No accepted merges to apply",
            "merges_applied": 0
        }

    # 2. 构建合并映射 (旧名称 -> 新名称)
    name_mapping = {}
    for merge in accepted_merges:
        primary_name = merge.get("primary_entity_name")
        for old_name in merge.get("merge_entity_names", []):
            name_mapping[old_name] = primary_name

    print(f"[EntityMerger] Applying {len(accepted_merges)} merges with {len(name_mapping)} name mappings")

    # 3. 加载合并后的提取结果
    combined = load_combined_extraction(project_id)
    if not combined:
        return {
            "success": False,
            "error": "No combined extraction found"
        }

    # 4. 更新 entities
    entities = combined.get("entities", [])
    merged_entity_ids = set()
    primary_entities = {}

    # 找出主实体和要合并的实体
    for e in entities:
        name = e.get("name")
        if name in name_mapping:
            # 这是要被合并的实体
            merged_entity_ids.add(e.get("id"))
        elif name in [m.get("primary_entity_name") for m in accepted_merges]:
            # 这是主实体
            primary_entities[name] = e

    # 合并别名
    for merge in accepted_merges:
        primary_name = merge.get("primary_entity_name")
        if primary_name in primary_entities:
            entity = primary_entities[primary_name]
            if entity.get("aliases") is None:
                entity["aliases"] = []
            for alias in merge.get("merge_entity_names", []):
                if alias not in entity["aliases"]:
                    entity["aliases"].append(alias)
            entity["is_merged"] = True
            entity["merged_from"] = merge.get("merge_entity_names", [])

    # 移除被合并的实体
    new_entities = [e for e in entities if e.get("id") not in merged_entity_ids]

    # 5. 更新 snippets 中的 subject
    snippets = combined.get("snippets", [])
    snippets_updated = 0

    for snippet in snippets:
        subject = snippet.get("subject", "")
        if subject in name_mapping:
            snippet["subject"] = name_mapping[subject]
            snippets_updated += 1

    # 6. 更新 relations 中的实体引用
    relations = combined.get("relations", [])
    relations_updated = 0

    for relation in relations:
        from_entity = relation.get("from_entity", "")
        to_entity = relation.get("to_entity", "")

        if from_entity in name_mapping:
            relation["from_entity"] = name_mapping[from_entity]
            relations_updated += 1

        if to_entity in name_mapping:
            relation["to_entity"] = name_mapping[to_entity]
            relations_updated += 1

    # 7. 更新 combined_extraction.json
    combined["entities"] = new_entities
    combined["snippets"] = snippets
    combined["relations"] = relations
    combined["merge_applied_at"] = datetime.now().isoformat()

    # 更新统计
    combined["stats"]["total_entities"] = len(new_entities)

    extraction_dir = get_extraction_dir(project_id)
    combined_file = extraction_dir / "combined_extraction.json"
    with open(combined_file, 'w', encoding='utf-8') as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    # 8. 同步更新 snippets 文件
    snippets_dir = PROJECTS_DIR / project_id / "snippets"
    snippets_file = snippets_dir / "extracted_snippets.json"

    if snippets_file.exists():
        with open(snippets_file, 'r', encoding='utf-8') as f:
            snippets_data = json.load(f)

        snippets_data["snippets"] = snippets
        snippets_data["merge_applied_at"] = datetime.now().isoformat()

        with open(snippets_file, 'w', encoding='utf-8') as f:
            json.dump(snippets_data, f, ensure_ascii=False, indent=2)

    # 9. 保存合并历史
    merge_history = []
    for merge in accepted_merges:
        record = {
            "id": merge.get("id"),
            "primary_entity_name": merge.get("primary_entity_name"),
            "merged_entity_names": merge.get("merge_entity_names"),
            "merge_reason": merge.get("reason"),
            "is_ai_suggested": True,
            "created_at": merge.get("created_at", datetime.now().isoformat()),
            "confirmed_at": datetime.now().isoformat()
        }
        merge_history.append(record)

    history_file = get_entities_dir(project_id) / "merge_history.json"
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump({
            "applied_at": datetime.now().isoformat(),
            "merges": merge_history
        }, f, ensure_ascii=False, indent=2)

    # 10. 保存更新后的 entities
    entities_file = get_entities_dir(project_id) / "entities.json"
    with open(entities_file, 'w', encoding='utf-8') as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "entity_count": len(new_entities),
            "entities": new_entities
        }, f, ensure_ascii=False, indent=2)

    print(f"[EntityMerger] Applied {len(accepted_merges)} merges, updated {snippets_updated} snippets, {relations_updated} relations")

    return {
        "success": True,
        "merges_applied": len(accepted_merges),
        "entities_removed": len(merged_entity_ids),
        "entities_remaining": len(new_entities),
        "snippets_updated": snippets_updated,
        "relations_updated": relations_updated
    }


def add_manual_merge(
    project_id: str,
    primary_name: str,
    merge_names: List[str],
    entity_type: str = "person"
) -> Dict:
    """
    添加手动合并

    用户可以手动指定要合并的实体
    """
    suggestion = {
        "id": f"merge_manual_{uuid.uuid4().hex[:8]}",
        "primary_entity_name": primary_name,
        "primary_entity_type": entity_type,
        "merge_entity_names": merge_names,
        "reason": "Manual merge by user",
        "confidence": 1.0,
        "status": "accepted",
        "is_manual": True,
        "created_at": datetime.now().isoformat()
    }

    # 加载现有建议
    suggestions_file = get_entities_dir(project_id) / "merge_suggestions.json"

    if suggestions_file.exists():
        with open(suggestions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = {
            "generated_at": datetime.now().isoformat(),
            "suggestions": []
        }

    data["suggestions"].append(suggestion)

    with open(suggestions_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return suggestion


def get_all_entities(project_id: str) -> List[Dict]:
    """获取所有实体"""
    # 优先从 entities.json 加载（已合并的）
    entities_file = get_entities_dir(project_id) / "entities.json"
    if entities_file.exists():
        with open(entities_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("entities", [])

    # 否则从 combined_extraction.json 加载
    combined = load_combined_extraction(project_id)
    if combined:
        return combined.get("entities", [])

    return []


def get_merge_status(project_id: str) -> Dict:
    """获取合并状态"""
    suggestions = load_merge_suggestions(project_id)

    pending = [s for s in suggestions if s.get("status") == "pending"]
    accepted = [s for s in suggestions if s.get("status") == "accepted"]
    rejected = [s for s in suggestions if s.get("status") == "rejected"]

    # 检查是否已应用
    history_file = get_entities_dir(project_id) / "merge_history.json"
    has_applied = history_file.exists()

    return {
        "total_suggestions": len(suggestions),
        "pending": len(pending),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "has_applied": has_applied,
        "needs_confirmation": len(pending) > 0
    }
