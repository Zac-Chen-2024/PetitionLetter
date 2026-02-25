"""
Entity Analyzer - LLM 动态实体分析服务

分析项目中的实体关系，生成 project_metadata.json 配置文件：
- 申请人名字变体
- Exhibit → 实体映射 (媒体/协会/组织)
- 实体合并规则
- 关键成就识别

替代 argument_composer.py 中的硬编码映射。
"""

import json
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime, timezone

from .llm_client import call_llm
from .unified_extractor import load_combined_extraction


# 数据目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


# Exhibit mapping item schema (used in arrays)
EXHIBIT_MAPPING_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "exhibit_id": {"type": "string", "description": "Exhibit ID (e.g., D1, C2, F3)"},
        "name": {"type": "string", "description": "Entity name (media/association/organization)"}
    },
    "required": ["exhibit_id", "name"],
    "additionalProperties": False
}

# LLM 分析的 JSON Schema (使用数组替代动态对象，兼容 OpenAI)
ENTITY_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "applicant": {
            "type": "object",
            "properties": {
                "formal_name": {"type": "string", "description": "Full legal name of the applicant"},
                "name_variants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "All name variants (nicknames, titles, etc.)"
                }
            },
            "required": ["formal_name", "name_variants"],
            "additionalProperties": False
        },
        "exhibit_mappings": {
            "type": "object",
            "properties": {
                "media": {
                    "type": "array",
                    "items": EXHIBIT_MAPPING_ITEM_SCHEMA,
                    "description": "Exhibit ID -> Media name mappings (for D series)"
                },
                "associations": {
                    "type": "array",
                    "items": EXHIBIT_MAPPING_ITEM_SCHEMA,
                    "description": "Exhibit ID -> Association name mappings (for C series)"
                },
                "organizations": {
                    "type": "array",
                    "items": EXHIBIT_MAPPING_ITEM_SCHEMA,
                    "description": "Exhibit ID -> Organization name mappings (for F series)"
                }
            },
            "required": ["media", "associations", "organizations"],
            "additionalProperties": False
        },
        "entity_merges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "canonical": {"type": "string", "description": "Canonical/formal name"},
                    "variants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Variant names that should be merged"
                    }
                },
                "required": ["canonical", "variants"],
                "additionalProperties": False
            },
            "description": "Entities that should be merged (same thing, different names)"
        },
        "disqualified_memberships": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Memberships that are just professional certifications, not selective associations"
        },
        "key_achievements": {
            "type": "object",
            "properties": {
                "original_contribution": {"type": "string", "description": "Name of the main original contribution"},
                "awards": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of major awards"
                }
            },
            "required": ["original_contribution", "awards"],
            "additionalProperties": False
        }
    },
    "required": ["applicant", "exhibit_mappings", "entity_merges", "disqualified_memberships", "key_achievements"],
    "additionalProperties": False
}


ENTITY_ANALYSIS_SYSTEM_PROMPT = """You are an expert immigration attorney analyzing evidence documents for an EB-1A (Extraordinary Ability) petition.

Your task is to analyze the extracted entities and snippets to identify:
1. The applicant's formal name and all name variants
2. How each Exhibit maps to specific entities (media outlets, associations, organizations)
3. Which entity names refer to the same thing and should be merged
4. Which memberships are just professional certifications (not selective associations)
5. The key achievements (original contributions, major awards)

Be precise with entity names - use the formal/official names."""


ENTITY_ANALYSIS_USER_PROMPT = """Analyze the following extracted data from an EB-1A petition for {applicant_name}:

## ENTITIES ({entity_count} total)
{entities_text}

## SNIPPETS BY EXHIBIT ({snippet_count} total)
{snippets_by_exhibit}

## INSTRUCTIONS

Based on this data, generate a JSON configuration. You MUST output valid JSON in EXACTLY this format:

```json
{{
  "applicant": {{
    "formal_name": "Full Legal Name",
    "name_variants": ["Nickname1", "Ms. Name", "Coach Name"]
  }},
  "exhibit_mappings": {{
    "media": [
      {{"exhibit_id": "D1", "name": "Media Outlet Name"}},
      {{"exhibit_id": "D2", "name": "Another Media"}}
    ],
    "associations": [
      {{"exhibit_id": "C1", "name": "Association Name"}}
    ],
    "organizations": [
      {{"exhibit_id": "F1", "name": "Organization Name"}}
    ]
  }},
  "entity_merges": [
    {{"canonical": "Official Name", "variants": ["Variant1", "Variant2"]}}
  ],
  "disqualified_memberships": ["Example Cert Body"],
  "key_achievements": {{
    "original_contribution": "Name of the main contribution",
    "awards": ["Award 1", "Award 2"]
  }}
}}
```

RULES:
1. APPLICANT: Identify the formal name and all variants (nicknames, titles)
2. EXHIBIT MAPPINGS:
   - D-series → media outlet names
   - C-series → association names
   - F-series → organization names
3. ENTITY MERGES: Same entity with different names
4. DISQUALIFIED MEMBERSHIPS: Professional certifications (NOT selective associations)
5. KEY ACHIEVEMENTS: Original contribution and major awards

Output ONLY the JSON, no other text."""


def _normalize_llm_response(result: Dict[str, Any], applicant_name: str) -> Dict[str, Any]:
    """
    规范化 LLM 响应格式 (处理 DeepSeek vs OpenAI 的差异)

    DeepSeek 可能返回:
    - 包装在 'content' 键中
    - applicant_info 而不是 applicant
    - 不同的字段结构
    """
    import re

    # 处理 DeepSeek 的 'content' 包装
    if isinstance(result, dict) and list(result.keys()) == ['content']:
        content = result['content']
        if isinstance(content, dict):
            result = content
        elif isinstance(content, str):
            # 可能是 JSON 字符串，尝试解析
            try:
                # 清理可能的问题字符
                cleaned = content.strip()
                # 移除 markdown code blocks
                if cleaned.startswith('```'):
                    cleaned = re.sub(r'^```json?\s*', '', cleaned)
                    cleaned = re.sub(r'\s*```$', '', cleaned)
                result = json.loads(cleaned)
            except json.JSONDecodeError as e:
                print(f"[EntityAnalyzer] JSON parse error: {e}")
                # 尝试修复常见问题
                try:
                    # 替换无效的 Unicode 转义
                    fixed = content.encode('utf-8', errors='replace').decode('utf-8')
                    result = json.loads(fixed)
                except:
                    print(f"[EntityAnalyzer] Could not parse content, using empty result")
                    result = {}

    normalized = {}

    # 规范化 applicant
    if "applicant" in result:
        normalized["applicant"] = result["applicant"]
    elif "applicant_info" in result:
        normalized["applicant"] = result["applicant_info"]
    else:
        normalized["applicant"] = {
            "formal_name": applicant_name,
            "name_variants": [applicant_name.lower()]
        }

    # 规范化 exhibit_mappings
    if "exhibit_mappings" in result:
        normalized["exhibit_mappings"] = result["exhibit_mappings"]
    else:
        normalized["exhibit_mappings"] = {
            "media": [],
            "associations": [],
            "organizations": []
        }

    # 规范化 entity_merges
    normalized["entity_merges"] = result.get("entity_merges", [])

    # 规范化 disqualified_memberships
    normalized["disqualified_memberships"] = result.get("disqualified_memberships", [])

    # 规范化 key_achievements
    if "key_achievements" in result:
        ka = result["key_achievements"]
        if isinstance(ka, dict):
            normalized["key_achievements"] = ka
        elif isinstance(ka, list):
            # DeepSeek 可能返回数组
            normalized["key_achievements"] = {
                "original_contribution": ka[0] if ka else "",
                "awards": ka[1:] if len(ka) > 1 else []
            }
        else:
            normalized["key_achievements"] = {
                "original_contribution": str(ka),
                "awards": []
            }
    else:
        normalized["key_achievements"] = {
            "original_contribution": "",
            "awards": []
        }

    return normalized


def _convert_arrays_to_dicts(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 LLM 输出的数组格式转换为字典格式 (兼容 argument_composer)

    LLM 输出: {"media": [{"exhibit_id": "D1", "name": "Jakarta Post"}, ...]}
    转换后:   {"media": {"D1": "Jakarta Post", ...}}
    """
    if "exhibit_mappings" in result:
        mappings = result["exhibit_mappings"]

        # 转换 media
        if isinstance(mappings.get("media"), list):
            mappings["media"] = {
                item["exhibit_id"]: item["name"]
                for item in mappings["media"]
                if "exhibit_id" in item and "name" in item
            }

        # 转换 associations
        if isinstance(mappings.get("associations"), list):
            mappings["associations"] = {
                item["exhibit_id"]: item["name"]
                for item in mappings["associations"]
                if "exhibit_id" in item and "name" in item
            }

        # 转换 organizations
        if isinstance(mappings.get("organizations"), list):
            mappings["organizations"] = {
                item["exhibit_id"]: item["name"]
                for item in mappings["organizations"]
                if "exhibit_id" in item and "name" in item
            }

    return result


async def analyze_project_entities(
    project_id: str,
    applicant_name: str,
    provider: str = "deepseek",
    force: bool = False
) -> Dict[str, Any]:
    """
    分析项目实体，生成配置

    Args:
        project_id: 项目 ID
        applicant_name: 申请人姓名
        provider: LLM 提供商
        force: 是否强制重新分析

    Returns:
        project_metadata 配置
    """
    metadata_file = PROJECTS_DIR / project_id / "project_metadata.json"

    # 如果配置已存在且不强制重新分析，直接返回
    if metadata_file.exists() and not force:
        with open(metadata_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    # 加载提取数据
    combined = load_combined_extraction(project_id)
    if not combined:
        return _create_empty_metadata(applicant_name)

    entities = combined.get("entities", [])
    snippets = combined.get("snippets", [])

    if not entities and not snippets:
        return _create_empty_metadata(applicant_name)

    print(f"[EntityAnalyzer] Analyzing {len(entities)} entities, {len(snippets)} snippets for {applicant_name}...")

    # 格式化实体
    entities_text = _format_entities(entities)

    # 按 Exhibit 分组 snippets
    snippets_by_exhibit = _format_snippets_by_exhibit(snippets)

    # 构建 prompt
    user_prompt = ENTITY_ANALYSIS_USER_PROMPT.format(
        applicant_name=applicant_name,
        entity_count=len(entities),
        entities_text=entities_text,
        snippet_count=len(snippets),
        snippets_by_exhibit=snippets_by_exhibit
    )

    # 调用 LLM
    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=ENTITY_ANALYSIS_SYSTEM_PROMPT,
            json_schema=ENTITY_ANALYSIS_SCHEMA,
            temperature=0.1,
            max_tokens=4000
        )
        # Debug: 打印原始响应
        print(f"[EntityAnalyzer] Raw LLM response keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
    except Exception as e:
        print(f"[EntityAnalyzer] LLM error: {e}")
        return _create_empty_metadata(applicant_name)

    # 规范化响应格式 (处理 DeepSeek vs OpenAI 的差异)
    result = _normalize_llm_response(result, applicant_name)

    # 后处理: 将数组格式转换为字典格式 (兼容 argument_composer)
    result = _convert_arrays_to_dicts(result)

    # 添加元数据
    result["_metadata"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "entity_count": len(entities),
        "snippet_count": len(snippets)
    }

    # 保存配置
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[EntityAnalyzer] Saved project_metadata.json")

    return result


def load_project_metadata(project_id: str) -> Optional[Dict[str, Any]]:
    """加载项目配置"""
    metadata_file = PROJECTS_DIR / project_id / "project_metadata.json"
    if metadata_file.exists():
        with open(metadata_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def _create_empty_metadata(applicant_name: str) -> Dict[str, Any]:
    """创建空配置"""
    return {
        "applicant": {
            "formal_name": applicant_name,
            "name_variants": [applicant_name.lower()]
        },
        "exhibit_mappings": {
            "media": {},
            "associations": {},
            "organizations": {}
        },
        "entity_merges": [],
        "disqualified_memberships": [],
        "key_achievements": {
            "original_contribution": "",
            "awards": []
        }
    }


def _format_entities(entities: List[Dict]) -> str:
    """格式化实体列表"""
    lines = []

    # 按类型分组
    by_type = {}
    for e in entities:
        etype = e.get("type", "other")
        if etype not in by_type:
            by_type[etype] = []
        by_type[etype].append(e)

    for etype, type_entities in by_type.items():
        lines.append(f"\n### {etype.upper()} ({len(type_entities)})")
        for e in type_entities[:20]:  # 限制数量
            name = e.get("name", "")
            identity = e.get("identity", "")
            relation = e.get("relation_to_applicant", "")
            exhibits = ", ".join(e.get("exhibit_ids", []))

            line = f"- {name}"
            if identity:
                line += f" | {identity}"
            if relation:
                line += f" | relation: {relation}"
            if exhibits:
                line += f" | exhibits: {exhibits}"
            lines.append(line)

    return "\n".join(lines)


def _format_snippets_by_exhibit(snippets: List[Dict]) -> str:
    """按 Exhibit 分组格式化 snippets"""
    by_exhibit = {}
    for s in snippets:
        exhibit_id = s.get("exhibit_id", "unknown")
        if exhibit_id not in by_exhibit:
            by_exhibit[exhibit_id] = []
        by_exhibit[exhibit_id].append(s)

    lines = []
    for exhibit_id in sorted(by_exhibit.keys()):
        exhibit_snippets = by_exhibit[exhibit_id]
        lines.append(f"\n### Exhibit {exhibit_id} ({len(exhibit_snippets)} snippets)")

        # 取前 3 个 snippet 的摘要
        for s in exhibit_snippets[:3]:
            text = s.get("text", "")[:150]
            subject = s.get("subject", "")
            etype = s.get("evidence_type", "")
            lines.append(f"  - [{etype}] {subject}: {text}...")

        if len(exhibit_snippets) > 3:
            lines.append(f"  ... and {len(exhibit_snippets) - 3} more")

    return "\n".join(lines)
