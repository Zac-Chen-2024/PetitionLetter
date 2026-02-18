"""
关系分析服务 v3.0 - 使用 OpenAI API

核心功能：
1. 从 snippets 中提取实体（人物、组织、成就等）
2. 识别实体之间的关系
3. 识别主体（申请人）- 通过分析谁是材料的核心人物
4. 判断每个 snippet 的成就归属于谁

关键概念：
- 主体归属：每个成就/证据必须归属到正确的人
- 例如：识别到"奥运金牌"，必须判断是申请人的还是其他人的
"""

import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from .llm_client import call_llm


# 实体类型
ENTITY_TYPES = [
    "person",       # 人物
    "organization", # 组织/公司/机构
    "award",        # 奖项/荣誉
    "publication",  # 出版物/论文/专利
    "position",     # 职位/角色
    "project",      # 项目/产品
    "event",        # 事件/会议/展览
    "metric",       # 指标/数据（引用数、收入等）
]

# 关系类型
RELATION_TYPES = [
    "received",      # 获得（奖项、荣誉）
    "works_at",      # 任职于
    "leads",         # 领导/管理
    "authored",      # 撰写/发明
    "founded",       # 创立
    "member_of",     # 成员
    "published_in",  # 发表于
    "cited_by",      # 被引用
    "collaborated",  # 合作
    "judged",        # 评审
    "owns",          # 拥有
    # 推荐信相关
    "writes_recommendation_for",  # 写推荐信给某人
    "recommends_to",              # 推荐到某组织
    "recommends_for_position",    # 推荐担任某职位
    "supervised_by",              # 被监督/指导
    "mentored_by",                # 被指导
    "trained_by",                 # 被训练
    "coached_by",                 # 被教练
    "evaluated_by",               # 被评估
]


@dataclass
class Entity:
    """实体"""
    id: str
    name: str
    type: str
    mentions: int = 1  # 被提及次数
    snippet_ids: List[str] = field(default_factory=list)  # 出现在哪些 snippet


@dataclass
class Relation:
    """关系"""
    from_entity: str  # 实体名称
    to_entity: str    # 实体名称
    relation_type: str
    snippet_ids: List[str] = field(default_factory=list)


@dataclass
class SnippetAttribution:
    """Snippet 归属信息"""
    snippet_id: str
    subject: str           # 这个 snippet 描述的主体是谁
    achievement_type: str  # 成就类型
    is_applicant: bool     # 是否归属于申请人
    confidence: float


class RelationshipAnalyzer:
    """
    关系分析器 - 使用 OpenAI API

    主要任务：
    1. 提取实体和关系
    2. 识别申请人（主体）
    3. 判断每个 snippet 的成就归属
    """

    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self.entities: Dict[str, Entity] = {}
        self.relations: List[Relation] = []

    async def analyze_snippets(
        self,
        snippets: List[Dict],
        known_applicant_name: Optional[str] = None,
        progress_callback=None
    ) -> Dict:
        """
        分析 snippets，提取实体、关系，识别主体

        Args:
            snippets: [{snippet_id, text, standard_key, exhibit_id, ...}, ...]
            known_applicant_name: 已知的申请人姓名（如果提供则跳过识别步骤）
            progress_callback: (current, total, message) -> None

        Returns:
            {
                "entities": [...],
                "relations": [...],
                "main_subject": "申请人姓名",
                "attributions": [{snippet_id, subject, is_applicant, ...}, ...],
                "stats": {...}
            }
        """
        if not snippets:
            return {
                "entities": [],
                "relations": [],
                "main_subject": known_applicant_name,
                "attributions": [],
                "stats": {"total_snippets": 0}
            }

        total = len(snippets)
        print(f"[RelationshipAnalyzer] Analyzing {total} snippets...")
        if known_applicant_name:
            print(f"[RelationshipAnalyzer] Known applicant: {known_applicant_name}")

        # Step 1: 批量提取实体和关系
        if progress_callback:
            progress_callback(0, 100, "Extracting entities...")

        # 将 snippets 分批处理（每批约 10 个）
        batch_size = 10
        all_extractions = []

        for i in range(0, total, batch_size):
            batch = snippets[i:i+batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size

            if progress_callback:
                progress = int((i / total) * 40)
                progress_callback(progress, 100, f"Extracting batch {batch_num}/{total_batches}...")

            extraction = await self._extract_entities_batch(batch, known_applicant_name)
            all_extractions.append(extraction)

            # 小延迟避免 rate limit
            await asyncio.sleep(0.5)

        # 合并所有提取结果
        self._merge_extractions(all_extractions)

        # Step 2: 识别主体（申请人）- 如果已提供则跳过
        if progress_callback:
            progress_callback(50, 100, "Identifying main subject...")

        if known_applicant_name:
            main_subject = known_applicant_name
            print(f"[RelationshipAnalyzer] Using provided applicant name: {main_subject}")
        else:
            main_subject = await self._identify_main_subject(snippets)

        # Step 2.5: 合并申请人的不同名称变体
        if main_subject:
            if progress_callback:
                progress_callback(60, 100, "Consolidating applicant entities...")
            self._consolidate_applicant_entities(main_subject)

        # Step 3: 判断每个 snippet 的归属
        if progress_callback:
            progress_callback(70, 100, "Attributing snippets...")

        attributions = await self._attribute_snippets(snippets, main_subject)

        if progress_callback:
            progress_callback(100, 100, "Analysis complete")

        result = {
            "entities": [asdict(e) for e in self.entities.values()],
            "relations": [asdict(r) for r in self.relations],
            "main_subject": main_subject,
            "attributions": [asdict(a) for a in attributions],
            "stats": {
                "total_snippets": total,
                "entity_count": len(self.entities),
                "relation_count": len(self.relations),
                "main_subject": main_subject,
                "analyzed_at": datetime.now().isoformat()
            }
        }

        print(f"[RelationshipAnalyzer] Complete: {len(self.entities)} entities, "
              f"{len(self.relations)} relations, main subject: {main_subject}")

        return result

    async def _extract_entities_batch(self, batch: List[Dict], known_applicant: Optional[str] = None) -> Dict:
        """从一批 snippets 中提取实体和关系"""

        # 构建输入文本
        quotes_text = []
        for i, s in enumerate(batch):
            text = s.get('text', '')[:500]  # 限制长度
            snippet_id = s.get('snippet_id', f'snp_{i}')
            quotes_text.append(f"[{snippet_id}] {text}")

        # 如果知道申请人姓名，在提示词中强调
        applicant_hint = ""
        if known_applicant:
            applicant_hint = f"""
IMPORTANT: The applicant's name is "{known_applicant}".
When you see names like "{known_applicant}", "Coach {known_applicant.split()[0]}", "Ms. {known_applicant.split()[-1]}", "Mr. {known_applicant.split()[-1]}", or similar variations, they all refer to the same person (the applicant).
Please normalize all references to the applicant as "{known_applicant}" in the output.
"""

        prompt = f"""Analyze these evidence snippets from an EB-1A visa petition and extract entities and relationships.
{applicant_hint}
Snippets:
{chr(10).join(quotes_text)}

Extract:
1. Entities: People (especially the applicant and recommendation letter writers), organizations, awards, publications, positions
2. Relationships: ALL meaningful relationships including:
   - Who received what award
   - Who works at which organization
   - Who authored what publication
   - Who writes recommendation letters for whom
   - Who recommends someone to which organization
   - Who supervised/mentored/trained whom

Return JSON:
{{
  "entities": [
    {{"name": "Dr. John Smith", "type": "person", "snippet_ids": ["snp_xxx"]}},
    {{"name": "Best Paper Award", "type": "award", "snippet_ids": ["snp_xxx"]}},
    {{"name": "Harvard University", "type": "organization", "snippet_ids": ["snp_xxx"]}}
  ],
  "relations": [
    {{"from": "Dr. John Smith", "to": "Best Paper Award", "type": "received", "snippet_ids": ["snp_xxx"]}},
    {{"from": "Prof. Jane Doe", "to": "Dr. John Smith", "type": "writes_recommendation_for", "snippet_ids": ["snp_xxx"]}},
    {{"from": "Prof. Jane Doe", "to": "Harvard University", "type": "recommends_to", "snippet_ids": ["snp_xxx"]}}
  ]
}}

Entity types: person, organization, award, publication, position, project, event, metric
Relation types: received, works_at, leads, authored, founded, member_of, published_in, cited_by, collaborated, judged, owns, writes_recommendation_for, recommends_to, recommends_for_position, supervised_by, mentored_by, trained_by, coached_by, evaluated_by

IMPORTANT for recommendation letters:
- If someone writes a recommendation letter, create TWO relations:
  1. "writes_recommendation_for" from writer to applicant
  2. "recommends_to" from writer to the target organization (if mentioned)
- Also capture supervisor/mentor relationships mentioned in letters

Important:
- Use exact names from text (but normalize applicant name variations)
- Include snippet_ids where each entity/relation appears
- Focus on the applicant and their achievements
- Pay special attention to recommendation letter relationships"""

        try:
            result = await call_llm(
                prompt=prompt,
                model=self.model,
                system_prompt="You are an expert at analyzing visa petition evidence. Extract entities and relationships precisely.",
                temperature=0.1
            )
            return result
        except Exception as e:
            print(f"[RelationshipAnalyzer] Batch extraction failed: {e}")
            return {"entities": [], "relations": []}

    def _merge_extractions(self, extractions: List[Dict]):
        """合并多批提取结果，去重"""

        for extraction in extractions:
            # 合并实体
            for e in extraction.get("entities", []):
                name = e.get("name", "").strip()
                if not name:
                    continue

                etype = e.get("type", "unknown")
                snippet_ids = e.get("snippet_ids", [])

                # 规范化名称用于去重
                norm_name = name.lower().replace(".", "").replace(",", "")

                # 查找是否已存在
                existing_key = None
                for key, entity in self.entities.items():
                    if key == norm_name or norm_name in key or key in norm_name:
                        existing_key = key
                        break

                if existing_key:
                    # 合并到已有实体
                    self.entities[existing_key].mentions += 1
                    for sid in snippet_ids:
                        if sid not in self.entities[existing_key].snippet_ids:
                            self.entities[existing_key].snippet_ids.append(sid)
                else:
                    # 创建新实体
                    self.entities[norm_name] = Entity(
                        id=f"e_{len(self.entities)}",
                        name=name,
                        type=etype,
                        mentions=1,
                        snippet_ids=snippet_ids
                    )

            # 合并关系
            for r in extraction.get("relations", []):
                from_name = r.get("from", "").strip()
                to_name = r.get("to", "").strip()
                rel_type = r.get("type", "related")
                snippet_ids = r.get("snippet_ids", [])

                if not from_name or not to_name:
                    continue

                # 检查是否已存在相同关系
                exists = False
                for existing_r in self.relations:
                    if (existing_r.from_entity.lower() == from_name.lower() and
                        existing_r.to_entity.lower() == to_name.lower() and
                        existing_r.relation_type == rel_type):
                        # 合并 snippet_ids
                        for sid in snippet_ids:
                            if sid not in existing_r.snippet_ids:
                                existing_r.snippet_ids.append(sid)
                        exists = True
                        break

                if not exists:
                    self.relations.append(Relation(
                        from_entity=from_name,
                        to_entity=to_name,
                        relation_type=rel_type,
                        snippet_ids=snippet_ids
                    ))

    def _consolidate_applicant_entities(self, main_subject: str):
        """
        合并申请人的不同名称变体到一个实体

        例如: "John Smith", "Coach John", "Dr. Smith", "Johnny" -> "John Smith"
        """
        # 生成可能的名称变体
        name_parts = main_subject.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[-1] if len(name_parts) > 1 else name_parts[0] if name_parts else ""

        # 常见的名称变体模式
        possible_variations = set()
        possible_variations.add(main_subject.lower())
        if first_name:
            possible_variations.add(first_name.lower())
            possible_variations.add(f"coach {first_name.lower()}")
            possible_variations.add(f"dr. {first_name.lower()}")
            possible_variations.add(f"mr. {first_name.lower()}")
            possible_variations.add(f"ms. {first_name.lower()}")
        if last_name:
            possible_variations.add(last_name.lower())
            possible_variations.add(f"coach {last_name.lower()}")
            possible_variations.add(f"dr. {last_name.lower()}")
            possible_variations.add(f"mr. {last_name.lower()}")
            possible_variations.add(f"ms. {last_name.lower()}")
        if first_name and last_name:
            possible_variations.add(f"{first_name.lower()} {last_name.lower()}")
            possible_variations.add(f"{last_name.lower()}, {first_name.lower()}")

        # 找出所有匹配的实体
        matching_keys = []
        for key, entity in self.entities.items():
            if entity.type != "person":
                continue
            name_lower = entity.name.lower().replace(".", "").replace(",", "").strip()
            # 检查是否匹配任何变体
            for variation in possible_variations:
                if variation in name_lower or name_lower in variation:
                    matching_keys.append(key)
                    break

        if len(matching_keys) <= 1:
            print(f"[RelationshipAnalyzer] No name variations to consolidate for {main_subject}")
            return

        print(f"[RelationshipAnalyzer] Consolidating {len(matching_keys)} name variations for {main_subject}")

        # 创建统一的实体
        consolidated_snippets = set()
        total_mentions = 0

        for key in matching_keys:
            entity = self.entities[key]
            consolidated_snippets.update(entity.snippet_ids)
            total_mentions += entity.mentions
            print(f"  - Merging: {entity.name} ({entity.mentions} mentions)")

        # 更新或创建主实体
        main_key = main_subject.lower().replace(".", "").replace(",", "")
        if main_key in self.entities:
            self.entities[main_key].snippet_ids = list(consolidated_snippets)
            self.entities[main_key].mentions = total_mentions
        else:
            self.entities[main_key] = Entity(
                id=f"e_main_{len(self.entities)}",
                name=main_subject,
                type="person",
                mentions=total_mentions,
                snippet_ids=list(consolidated_snippets)
            )

        # 删除其他变体
        for key in matching_keys:
            if key != main_key and key in self.entities:
                del self.entities[key]

        # 更新关系中的实体名称
        for relation in self.relations:
            for variation in possible_variations:
                if variation in relation.from_entity.lower():
                    relation.from_entity = main_subject
                if variation in relation.to_entity.lower():
                    relation.to_entity = main_subject

        print(f"[RelationshipAnalyzer] Consolidated to single entity: {main_subject} ({total_mentions} total mentions)")

    async def _identify_main_subject(self, snippets: List[Dict]) -> Optional[str]:
        """
        识别主体（申请人）

        策略：
        1. 找出所有 person 类型实体
        2. 根据提及次数和关系数量判断
        3. 使用 LLM 确认
        """
        # 找出所有 person 实体
        person_entities = [
            e for e in self.entities.values()
            if e.type == "person"
        ]

        if not person_entities:
            print("[RelationshipAnalyzer] No person entities found")
            return None

        # 按提及次数排序
        person_entities.sort(key=lambda e: e.mentions, reverse=True)

        # 如果只有一个人，直接返回
        if len(person_entities) == 1:
            return person_entities[0].name

        # 取前 5 个候选人，让 LLM 判断
        candidates = person_entities[:5]

        # 收集一些代表性 snippets
        sample_texts = []
        for s in snippets[:10]:
            text = s.get('text', '')[:200]
            sample_texts.append(text)

        prompt = f"""Based on these evidence snippets from an EB-1A visa petition, identify the main applicant (the person this petition is for).

Sample evidence:
{chr(10).join(sample_texts)}

Candidate names found in the documents:
{chr(10).join([f"- {e.name} (mentioned {e.mentions} times)" for e in candidates])}

Return JSON:
{{"main_subject": "Full Name of Applicant", "confidence": 0.9, "reasoning": "Brief explanation"}}

The applicant is typically:
- The person with most achievements described
- The person receiving awards, holding leadership positions
- The primary author of publications
- NOT the letter writer or reference"""

        try:
            result = await call_llm(
                prompt=prompt,
                model=self.model,
                system_prompt="Identify the main applicant in a visa petition.",
                temperature=0.1
            )

            main_subject = result.get("main_subject", candidates[0].name)
            print(f"[RelationshipAnalyzer] Identified main subject: {main_subject}")
            return main_subject

        except Exception as e:
            print(f"[RelationshipAnalyzer] Main subject identification failed: {e}")
            # 回退：返回提及最多的人
            return candidates[0].name if candidates else None

    async def _attribute_snippets(
        self,
        snippets: List[Dict],
        main_subject: Optional[str]
    ) -> List[SnippetAttribution]:
        """
        判断每个 snippet 的成就归属

        关键问题：这个 snippet 描述的成就是申请人的还是其他人的？
        """
        if not main_subject:
            # 没有识别到主体，全部标记为未知
            return [
                SnippetAttribution(
                    snippet_id=s.get('snippet_id', ''),
                    subject="Unknown",
                    achievement_type=s.get('standard_key', ''),
                    is_applicant=True,  # 默认假设是申请人的
                    confidence=0.5
                )
                for s in snippets
            ]

        # 批量处理归属判断
        attributions = []
        batch_size = 15

        for i in range(0, len(snippets), batch_size):
            batch = snippets[i:i+batch_size]
            batch_attributions = await self._attribute_batch(batch, main_subject)
            attributions.extend(batch_attributions)
            await asyncio.sleep(0.3)

        return attributions

    async def _attribute_batch(
        self,
        batch: List[Dict],
        main_subject: str
    ) -> List[SnippetAttribution]:
        """判断一批 snippets 的归属"""

        quotes_text = []
        for s in batch:
            snippet_id = s.get('snippet_id', '')
            text = s.get('text', '')[:400]
            standard_key = s.get('standard_key', '')
            quotes_text.append(f"[{snippet_id}] ({standard_key}) {text}")

        prompt = f"""For each snippet, determine if the achievement/evidence belongs to the applicant "{main_subject}" or someone else.

Snippets:
{chr(10).join(quotes_text)}

Return JSON array:
[
  {{"snippet_id": "snp_xxx", "subject": "Name of person this describes", "is_applicant": true, "confidence": 0.9}}
]

Rules:
- is_applicant = true if the achievement belongs to {main_subject}
- is_applicant = false if it describes someone else's achievement (e.g., a reference letter writer's background)
- subject = the actual person being described
- confidence = how certain you are (0.0-1.0)"""

        try:
            result = await call_llm(
                prompt=prompt,
                model=self.model,
                system_prompt="Determine who each piece of evidence describes.",
                temperature=0.1
            )

            attributions = []
            items = result if isinstance(result, list) else result.get("attributions", result.get("results", []))

            for item in items:
                if isinstance(item, dict):
                    attributions.append(SnippetAttribution(
                        snippet_id=item.get("snippet_id", ""),
                        subject=item.get("subject", main_subject),
                        achievement_type="",  # 从 snippet 获取
                        is_applicant=item.get("is_applicant", True),
                        confidence=item.get("confidence", 0.8)
                    ))

            # 补充 snippet 中的 standard_key
            snippet_map = {s.get('snippet_id'): s for s in batch}
            for attr in attributions:
                if attr.snippet_id in snippet_map:
                    attr.achievement_type = snippet_map[attr.snippet_id].get('standard_key', '')

            return attributions

        except Exception as e:
            print(f"[RelationshipAnalyzer] Attribution batch failed: {e}")
            # 回退：全部归属于申请人
            return [
                SnippetAttribution(
                    snippet_id=s.get('snippet_id', ''),
                    subject=main_subject,
                    achievement_type=s.get('standard_key', ''),
                    is_applicant=True,
                    confidence=0.5
                )
                for s in batch
            ]


async def analyze_relationships(
    snippets: List[Dict],
    model: str = "gpt-4o-mini",
    applicant_name: Optional[str] = None,
    progress_callback=None
) -> Dict:
    """
    关系分析入口函数

    Args:
        snippets: snippet 列表
        model: 使用的模型
        applicant_name: 已知的申请人姓名（用于精确归属判断）
        progress_callback: 进度回调

    Returns:
        分析结果
    """
    analyzer = RelationshipAnalyzer(model=model)
    return await analyzer.analyze_snippets(snippets, applicant_name, progress_callback)


# ==================== EB-1A Specific Relationship Analysis ====================

# EB-1A 关键关系类型 (用于区分领导角色 vs 邀请 vs 合作)
EB1A_RELATIONSHIP_TYPES = {
    "founder_of": "申请人创立/创办了该组织 → Leading Role 证据",
    "executive_at": "申请人在该组织担任高管 (CEO/Director/法定代表人) → Leading Role 证据",
    "employee_at": "申请人在该组织工作 (非领导职位) → 可能是 Leading Role (需看具体职位)",
    "member_of": "申请人是该协会/组织的会员 → Membership 证据",
    "featured_in": "申请人被该媒体报道 → Published Material 证据",
    "invited_by": "申请人被该组织邀请 (演讲/参加活动) → NOT Leading Role",
    "partner_with": "申请人与该组织合作/建立合作关系 → NOT Leading Role",
    "awarded_by": "申请人从该组织获得奖项 → Awards 证据",
    "contributed_to": "申请人对该领域/组织有贡献 → Original Contribution 证据",
    "recommended_by": "该组织/专家为申请人写推荐信 → 支持证据",
}

# EB-1A 关系分析的 JSON Schema
EB1A_RELATIONSHIP_SCHEMA = {
    "type": "object",
    "properties": {
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "组织/媒体/协会的名称"
                    },
                    "entity_type": {
                        "type": "string",
                        "enum": ["organization", "media", "association", "event", "person"],
                        "description": "实体类型"
                    },
                    "relationship_type": {
                        "type": "string",
                        "enum": list(EB1A_RELATIONSHIP_TYPES.keys()),
                        "description": "申请人与该实体的关系类型"
                    },
                    "evidence_snippets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "支持该关系的 snippet IDs"
                    },
                    "confidence": {
                        "type": "number",
                        "description": "置信度 0-1"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "判断依据"
                    }
                },
                "required": ["entity_name", "entity_type", "relationship_type", "confidence", "reasoning"]
            }
        }
    },
    "required": ["relationships"]
}

EB1A_RELATIONSHIP_SYSTEM_PROMPT = """You are an expert immigration attorney analyzing evidence for an EB-1A visa petition.

Your task is to analyze the relationship between the applicant and each organization/entity mentioned in the evidence.

CRITICAL DISTINCTIONS for EB-1A:

1. **LEADERSHIP RELATIONSHIPS** (qualify for Leading Role criterion):
   - founder_of: Applicant FOUNDED/CREATED the organization
   - executive_at: Applicant holds executive position (CEO, Director, Legal Representative, Chairman)

2. **NON-LEADERSHIP RELATIONSHIPS** (do NOT qualify for Leading Role):
   - invited_by: Applicant was INVITED to speak/participate (keynote speaker, guest speaker, invited expert)
   - partner_with: Applicant has PARTNERSHIP/COOPERATION agreement (not employed or leading)

3. **OTHER RELATIONSHIPS**:
   - member_of: Membership in association → Membership criterion
   - featured_in: Media coverage → Published Material criterion
   - awarded_by: Received award → Awards criterion
   - contributed_to: Made contributions → Original Contribution criterion

IMPORTANT RULES:
- Being invited to speak at an organization's event ≠ Leading that organization
- Having a partnership/cooperation agreement ≠ Leading that organization
- Being featured in media ≠ Working for that media
- Carefully read the context to determine the TRUE relationship"""

EB1A_RELATIONSHIP_USER_PROMPT = """Analyze the relationships between the applicant "{applicant_name}" and the entities mentioned below.

ENTITIES TO ANALYZE:
{entities_list}

EVIDENCE SNIPPETS:
{snippets_text}

For each entity where the applicant has a relationship, determine:
1. relationship_type: One of [founder_of, executive_at, employee_at, member_of, featured_in, invited_by, partner_with, awarded_by, contributed_to, recommended_by]
2. evidence_snippets: List of snippet IDs that support this relationship
3. confidence: 0.0 to 1.0
4. reasoning: Brief explanation

CRITICAL DISTINCTIONS:
- "invited to speak at X" → relationship_type: "invited_by" (NOT leadership)
- "partnership with X" or "cooperation with X" → relationship_type: "partner_with" (NOT leadership)
- "founded X" or "created X" → relationship_type: "founder_of" (IS leadership)
- "CEO/Director/Legal Representative of X" → relationship_type: "executive_at" (IS leadership)

Return your analysis as a JSON object with EXACTLY this structure:
{{
  "relationships": [
    {{
      "entity_name": "Organization Name",
      "entity_type": "organization",
      "relationship_type": "founder_of",
      "evidence_snippets": ["snp_1", "snp_2"],
      "confidence": 0.9,
      "reasoning": "Evidence shows applicant founded this organization"
    }}
  ]
}}

IMPORTANT: The root object MUST have a "relationships" array."""


@dataclass
class ApplicantRelationship:
    """申请人与实体的关系"""
    entity_name: str
    entity_type: str  # organization, media, association, event, person
    relationship_type: str  # founder_of, executive_at, invited_by, partner_with, etc.
    evidence_snippets: List[str]
    confidence: float
    reasoning: str

    # EB-1A 相关标记
    qualifies_for_leadership: bool = False  # 是否可用于 Leading Role criterion
    qualifies_for_membership: bool = False  # 是否可用于 Membership criterion
    qualifies_for_media: bool = False  # 是否可用于 Published Material criterion

    def __post_init__(self):
        """根据关系类型自动设置 EB-1A 资格标记"""
        if self.relationship_type in ["founder_of", "executive_at"]:
            self.qualifies_for_leadership = True
        elif self.relationship_type == "member_of":
            self.qualifies_for_membership = True
        elif self.relationship_type == "featured_in":
            self.qualifies_for_media = True


async def analyze_applicant_relationships(
    snippets: List[Dict],
    entities: List[Dict],
    applicant_name: str,
    provider: str = "deepseek"
) -> Dict[str, Any]:
    """
    分析申请人与每个实体的关系类型 (EB-1A 专用)

    这是 Full LLM Multi-Agent Pipeline 的核心组件，用于区分：
    - Leadership 关系 (founder_of, executive_at) → 可用于 Leading Role
    - Invitation 关系 (invited_by) → 不可用于 Leading Role
    - Partnership 关系 (partner_with) → 不可用于 Leading Role

    Args:
        snippets: 带上下文的 snippets
        entities: 实体列表
        applicant_name: 申请人姓名
        provider: LLM 提供商

    Returns:
        {
            "relationships": [ApplicantRelationship, ...],
            "leadership_entities": [...],  # 可用于 Leading Role 的实体
            "non_leadership_entities": [...],  # 不可用于 Leading Role 的实体
            "stats": {...}
        }
    """
    print(f"[EB1A-RelationshipAnalyzer] Analyzing relationships for {applicant_name}...")
    print(f"[EB1A-RelationshipAnalyzer] {len(snippets)} snippets, {len(entities)} entities")

    # 过滤出组织类实体 (用于分析 leadership/invitation/partnership)
    org_entities = [
        e for e in entities
        if e.get("type", "").lower() in ["organization", "company", "association", "club", "federation", "media"]
    ]

    if not org_entities:
        print("[EB1A-RelationshipAnalyzer] No organization entities found")
        return {
            "relationships": [],
            "leadership_entities": [],
            "non_leadership_entities": [],
            "stats": {"total_entities": 0, "analyzed": 0}
        }

    # 准备 snippets 文本 (包含上下文)
    snippets_text = []
    for i, s in enumerate(snippets[:50]):  # 限制数量避免 token 过多
        text = s.get("text", "")
        context = s.get("context", {})
        full_context = context.get("full_context", "") if context else ""
        snippet_id = s.get("snippet_id", f"snp_{i}")

        if full_context:
            snippets_text.append(f"[{snippet_id}] {full_context[:500]}")
        else:
            snippets_text.append(f"[{snippet_id}] {text[:300]}")

    # 准备实体列表
    entities_list = "\n".join([
        f"- {e.get('name', '')} ({e.get('type', '')})"
        for e in org_entities[:30]  # 限制数量
    ])

    # 构建 prompt
    user_prompt = EB1A_RELATIONSHIP_USER_PROMPT.format(
        applicant_name=applicant_name,
        entities_list=entities_list,
        snippets_text="\n\n".join(snippets_text)
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=EB1A_RELATIONSHIP_SYSTEM_PROMPT,
            json_schema=EB1A_RELATIONSHIP_SCHEMA,
            temperature=0.1,
            max_tokens=3000
        )

        # 调试输出
        print(f"[EB1A-RelationshipAnalyzer] Raw result type: {type(result)}")
        print(f"[EB1A-RelationshipAnalyzer] Raw result keys: {result.keys() if isinstance(result, dict) else 'N/A'}")

        # 解析结果 - 处理多种可能的响应格式
        relationships = []
        leadership_entities = []
        non_leadership_entities = []

        # 尝试获取 relationships 数组
        raw_relationships = result.get("relationships", [])

        # 如果没有 relationships 键，尝试从其他格式转换
        if not raw_relationships and isinstance(result, dict):
            # 可能是 {entity_name: relationship_info} 格式
            for key, value in result.items():
                if key == "relationships":
                    continue
                if isinstance(value, dict):
                    # 转换为标准格式
                    raw_relationships.append({
                        "entity_name": key,
                        "entity_type": value.get("entity_type", "organization"),
                        "relationship_type": value.get("relationship_type", value.get("type", "unknown")),
                        "evidence_snippets": value.get("evidence_snippets", value.get("snippets", [])),
                        "confidence": value.get("confidence", 0.5),
                        "reasoning": value.get("reasoning", value.get("reason", ""))
                    })
                elif isinstance(value, str):
                    # 简化格式: {entity_name: relationship_type}
                    raw_relationships.append({
                        "entity_name": key,
                        "entity_type": "organization",
                        "relationship_type": value,
                        "evidence_snippets": [],
                        "confidence": 0.5,
                        "reasoning": ""
                    })

        print(f"[EB1A-RelationshipAnalyzer] Parsed relationships count: {len(raw_relationships)}")

        for r in raw_relationships:
            rel = ApplicantRelationship(
                entity_name=r.get("entity_name", ""),
                entity_type=r.get("entity_type", "organization"),
                relationship_type=r.get("relationship_type", "unknown"),
                evidence_snippets=r.get("evidence_snippets", []),
                confidence=r.get("confidence", 0.5),
                reasoning=r.get("reasoning", "")
            )
            relationships.append(rel)

            # 分类
            if rel.qualifies_for_leadership:
                leadership_entities.append({
                    "name": rel.entity_name,
                    "relationship": rel.relationship_type,
                    "confidence": rel.confidence,
                    "reasoning": rel.reasoning
                })
            elif rel.relationship_type in ["invited_by", "partner_with"]:
                non_leadership_entities.append({
                    "name": rel.entity_name,
                    "relationship": rel.relationship_type,
                    "confidence": rel.confidence,
                    "reasoning": rel.reasoning
                })

        print(f"[EB1A-RelationshipAnalyzer] Found {len(relationships)} relationships")
        print(f"[EB1A-RelationshipAnalyzer] Leadership entities: {len(leadership_entities)}")
        print(f"[EB1A-RelationshipAnalyzer] Non-leadership entities: {len(non_leadership_entities)}")

        return {
            "relationships": [asdict(r) for r in relationships],
            "leadership_entities": leadership_entities,
            "non_leadership_entities": non_leadership_entities,
            "stats": {
                "total_entities": len(org_entities),
                "analyzed": len(relationships),
                "leadership_count": len(leadership_entities),
                "non_leadership_count": len(non_leadership_entities)
            }
        }

    except Exception as e:
        print(f"[EB1A-RelationshipAnalyzer] Error: {e}")
        return {
            "relationships": [],
            "leadership_entities": [],
            "non_leadership_entities": [],
            "stats": {"error": str(e)}
        }
