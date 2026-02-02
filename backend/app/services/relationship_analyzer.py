"""
关系分析服务 v2.0 - 动态分组增量构建

核心思路：
1. 根据引用长度动态分组（字符上限）
2. 每批提取实体和关系
3. 增量构建关系图，去重合并
4. 保留引用索引用于 bbox 回溯
"""

import json
import asyncio
import httpx
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Entity:
    """实体节点"""
    id: str
    name: str
    type: str  # person, company, position
    aliases: List[str] = field(default_factory=list)
    quote_refs: List[int] = field(default_factory=list)


@dataclass
class Relation:
    """关系边"""
    from_entity: str
    to_entity: str
    relation_type: str
    quote_refs: List[int] = field(default_factory=list)


class RelationshipGraph:
    """关系图 - 增量构建"""

    def __init__(self):
        self.entities: Dict[str, Entity] = {}  # id -> Entity
        self.relations: List[Relation] = []
        self._name_to_id: Dict[str, str] = {}  # normalized_name -> id
        self._next_id = 0

    def _normalize(self, name: str) -> str:
        """名称规范化"""
        return name.lower().strip().replace(".", "").replace(",", "").replace("'", "")

    def find_entity(self, name: str) -> Optional[str]:
        """查找实体，返回 ID"""
        norm = self._normalize(name)

        # 精确匹配
        if norm in self._name_to_id:
            return self._name_to_id[norm]

        # 包含匹配
        for existing_norm, eid in self._name_to_id.items():
            if norm in existing_norm or existing_norm in norm:
                return eid

        return None

    def add_entity(self, name: str, etype: str, quote_ref: int) -> str:
        """添加实体，返回 ID（已存在则合并）"""
        existing_id = self.find_entity(name)

        if existing_id:
            # 合并到已有实体
            entity = self.entities[existing_id]
            if name not in entity.aliases and name != entity.name:
                entity.aliases.append(name)
            if quote_ref >= 0 and quote_ref not in entity.quote_refs:
                entity.quote_refs.append(quote_ref)
            return existing_id
        else:
            # 创建新实体
            eid = f"e{self._next_id}"
            self._next_id += 1
            self.entities[eid] = Entity(
                id=eid,
                name=name,
                type=etype,
                aliases=[],
                quote_refs=[quote_ref] if quote_ref >= 0 else []
            )
            self._name_to_id[self._normalize(name)] = eid
            return eid

    def add_relation(self, from_name: str, to_name: str, rel_type: str, quote_ref: int):
        """添加关系"""
        from_id = self.find_entity(from_name)
        to_id = self.find_entity(to_name)

        if not from_id or not to_id:
            return

        # 检查是否已存在相同关系
        for r in self.relations:
            if r.from_entity == from_id and r.to_entity == to_id and r.relation_type == rel_type:
                if quote_ref >= 0 and quote_ref not in r.quote_refs:
                    r.quote_refs.append(quote_ref)
                return

        # 添加新关系
        self.relations.append(Relation(
            from_entity=from_id,
            to_entity=to_id,
            relation_type=rel_type,
            quote_refs=[quote_ref] if quote_ref >= 0 else []
        ))

    def to_dict(self) -> Dict:
        """导出为字典"""
        return {
            "entities": [asdict(e) for e in self.entities.values()],
            "relations": [asdict(r) for r in self.relations]
        }


class RelationshipAnalyzer:
    """动态分组关系分析器"""

    def __init__(
        self,
        llm_base_url: str = "http://localhost:11434/v1",
        model: str = "qwen3:30b-a3b",
        batch_char_limit: int = 1500,
        batch_count_limit: int = 3  # 每批最多3条引用
    ):
        self.llm_base_url = llm_base_url
        self.model = model
        self.batch_char_limit = batch_char_limit
        self.batch_count_limit = batch_count_limit
        self.graph = RelationshipGraph()
        self.quote_index_map: Dict[int, Dict] = {}

    async def _call_llm(self, prompt: str, timeout: float = 180.0) -> str:
        """调用 LLM"""
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Return ONLY valid JSON. No markdown, no explanation."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"}
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.llm_base_url}/chat/completions",
                headers={"Authorization": "Bearer ollama", "Content-Type": "application/json"},
                json=request_body
            )

            if response.status_code != 200:
                raise ValueError(f"LLM error: {response.text}")

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return content

    def _group_quotes_by_length(self, quotes: List[Dict]) -> List[List[Tuple[int, Dict]]]:
        """根据长度和数量动态分组"""
        groups = []
        current_group = []
        current_length = 0

        for idx, q in enumerate(quotes):
            quote_text = q.get("quote", "")
            quote_len = len(quote_text)

            # 如果单条就超限，单独一组
            if quote_len >= self.batch_char_limit:
                if current_group:
                    groups.append(current_group)
                    current_group = []
                    current_length = 0
                groups.append([(idx, q)])
            # 如果加入会超过字符限制或数量限制，开始新组
            elif (current_length + quote_len > self.batch_char_limit or
                  len(current_group) >= self.batch_count_limit):
                if current_group:
                    groups.append(current_group)
                current_group = [(idx, q)]
                current_length = quote_len
            # 加入当前组
            else:
                current_group.append((idx, q))
                current_length += quote_len

        if current_group:
            groups.append(current_group)

        return groups

    async def _analyze_batch(self, batch: List[Tuple[int, Dict]]) -> None:
        """分析一批引用，提取实体和关系"""
        # 构建 prompt
        quotes_text = []
        for idx, q in batch:
            quote = q.get("quote", "")[:500]  # 限制单条长度
            quotes_text.append(f"[{idx}] {quote}")

        prompt = f"""Extract entities and relationships from these quotes.

Quotes:
{chr(10).join(quotes_text)}

Return JSON:
{{"results": [{{"quote_idx": 0, "entities": [{{"name": "...", "type": "person|company|position"}}], "relations": [{{"from": "entity name", "to": "entity name", "type": "employed_by|owns|subsidiary_of|manages|founded|works_at"}}]}}]}}

Rules:
- Only extract what is explicitly stated
- Use exact names from text
- quote_idx must match the [idx] in quotes"""

        try:
            result = await self._call_llm(prompt)
            data = json.loads(result)

            # 处理结果
            for item in data.get("results", []):
                quote_idx = item.get("quote_idx", -1)

                # 添加实体
                for e in item.get("entities", []):
                    name = e.get("name", "").strip()
                    etype = e.get("type", "unknown")
                    if name:
                        self.graph.add_entity(name, etype, quote_idx)

                # 添加关系
                for r in item.get("relations", []):
                    from_name = r.get("from", "").strip()
                    to_name = r.get("to", "").strip()
                    rel_type = r.get("type", "related_to")
                    if from_name and to_name:
                        # 确保实体存在
                        self.graph.add_entity(from_name, "unknown", quote_idx)
                        self.graph.add_entity(to_name, "unknown", quote_idx)
                        self.graph.add_relation(from_name, to_name, rel_type, quote_idx)

        except json.JSONDecodeError as e:
            print(f"  [批次分析] JSON 解析失败: {e}")
        except Exception as e:
            import traceback
            print(f"  [批次分析] 失败: {type(e).__name__}: {e}")
            traceback.print_exc()

    async def analyze(self, quotes: List[Dict], progress_callback=None) -> Dict:
        """
        执行关系分析

        Args:
            quotes: [{quote, standard_key, exhibit_id, page, ...}, ...]
            progress_callback: (current_batch, total_batches, message) -> None

        Returns:
            {entities, relations, l1_evidence, quote_index_map, stats}
        """
        # 保存引用映射
        for idx, q in enumerate(quotes):
            self.quote_index_map[idx] = q

        # 动态分组
        groups = self._group_quotes_by_length(quotes)
        total_batches = len(groups)

        print(f"[关系分析] {len(quotes)} 条引用 → {total_batches} 个批次")

        # 逐批处理
        for batch_idx, batch in enumerate(groups):
            batch_quotes = [idx for idx, _ in batch]
            print(f"  批次 {batch_idx + 1}/{total_batches}: 引用 {batch_quotes}")

            if progress_callback:
                progress_callback(batch_idx + 1, total_batches, f"处理批次 {batch_idx + 1}/{total_batches}")

            await self._analyze_batch(batch)

            # 小延迟避免过载
            await asyncio.sleep(0.2)

        # 生成 L1 证据
        l1_evidence = self._generate_l1_evidence(quotes)

        # 构建结果
        result = {
            **self.graph.to_dict(),
            "l1_evidence": l1_evidence,
            "quote_index_map": {str(k): v for k, v in self.quote_index_map.items()},
            "stats": {
                "total_quotes": len(quotes),
                "total_batches": total_batches,
                "entity_count": len(self.graph.entities),
                "relation_count": len(self.graph.relations),
                "analyzed_at": datetime.now().isoformat()
            }
        }

        print(f"[关系分析] 完成: {len(self.graph.entities)} 实体, {len(self.graph.relations)} 关系")

        return result

    def _generate_l1_evidence(self, quotes: List[Dict]) -> List[Dict]:
        """根据 standard_key 生成 L1 证据"""
        standard_refs = {}

        for idx, q in enumerate(quotes):
            sk = q.get("standard_key", "")
            if sk:
                if sk not in standard_refs:
                    standard_refs[sk] = []
                standard_refs[sk].append(idx)

        evidence = []
        for standard, refs in standard_refs.items():
            strength = "strong" if len(refs) >= 3 else ("moderate" if len(refs) >= 1 else "weak")
            evidence.append({
                "standard": standard,
                "quote_refs": refs,
                "strength": strength
            })

        return evidence


async def run_relationship_analysis(
    quotes: List[Dict],
    llm_base_url: str = "http://localhost:11434/v1",
    model: str = "qwen3:30b-a3b",
    batch_char_limit: int = 1500,
    batch_count_limit: int = 3,
    progress_callback=None
) -> Dict:
    """
    运行关系分析

    Args:
        quotes: 引用列表
        llm_base_url: LLM API 地址
        model: 模型名称
        batch_char_limit: 批次字符上限
        progress_callback: 进度回调

    Returns:
        分析结果
    """
    analyzer = RelationshipAnalyzer(
        llm_base_url=llm_base_url,
        model=model,
        batch_char_limit=batch_char_limit,
        batch_count_limit=batch_count_limit
    )
    return await analyzer.analyze(quotes, progress_callback)
