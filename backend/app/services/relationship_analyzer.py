"""
关系分析服务 v2.0 - 动态分组增量构建

核心思路：
1. 根据引用长度动态分组（字符上限）
2. 每批提取实体和关系
3. 增量构建关系图，去重合并
4. 保留引用索引用于 bbox 回溯
5. 支持断点续传（checkpoint）避免中断后从头开始
"""

import json
import asyncio
import httpx
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

# 数据存储根目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


class RelationshipCheckpoint:
    """关系分析断点管理器 - 支持断点续传"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.checkpoint_dir = PROJECTS_DIR / project_id / "relationship"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = self.checkpoint_dir / "relationship_checkpoint.json"
        self.state: Dict[str, Any] = {}
        self.load()

    def load(self) -> bool:
        """加载已有状态，返回是否存在有效断点"""
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                    self.state = json.load(f)
                # 验证状态有效性
                if self.state.get("status") in ["processing", "failed"]:
                    return True
            except (json.JSONDecodeError, IOError) as e:
                print(f"[Checkpoint] 加载失败: {e}")
                self.state = {}
        return False

    def _save(self):
        """保存当前状态到文件"""
        with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def init_new(self, total_batches: int, quotes_list: List[Dict], quote_index_map: Dict):
        """初始化新的分析任务"""
        self.state = {
            "started_at": datetime.now().isoformat(),
            "status": "processing",
            "total_batches": total_batches,
            "completed_batches": [],
            "failed_batches": [],
            "current_batch": None,
            "graph_state": None,
            "quote_index_map": {str(k): v for k, v in quote_index_map.items()},
            "quotes_list": quotes_list
        }
        self._save()

    def save_batch(self, batch_idx: int, graph_state: Dict):
        """每批处理完成后保存状态"""
        if batch_idx not in self.state.get("completed_batches", []):
            self.state["completed_batches"].append(batch_idx)
        # 从失败列表移除（如果是重试成功）
        if batch_idx in self.state.get("failed_batches", []):
            self.state["failed_batches"].remove(batch_idx)
        self.state["current_batch"] = None
        self.state["graph_state"] = graph_state
        self._save()

    def mark_batch_failed(self, batch_idx: int):
        """标记批次失败"""
        if batch_idx not in self.state.get("failed_batches", []):
            self.state["failed_batches"].append(batch_idx)
        self.state["current_batch"] = None
        self._save()

    def mark_batch_in_progress(self, batch_idx: int):
        """标记批次处理中"""
        self.state["current_batch"] = batch_idx
        self._save()

    def is_batch_completed(self, batch_idx: int) -> bool:
        """检查批次是否已完成"""
        return batch_idx in self.state.get("completed_batches", [])

    def get_resume_point(self) -> int:
        """获取恢复点（下一个未完成批次索引）"""
        completed = set(self.state.get("completed_batches", []))
        total = self.state.get("total_batches", 0)
        for i in range(total):
            if i not in completed:
                return i
        return total  # 所有批次都已完成

    def mark_completed(self):
        """标记整体完成并删除 checkpoint 文件"""
        self.state["status"] = "completed"
        self.state["completed_at"] = datetime.now().isoformat()
        # 分析完成后删除 checkpoint 文件
        self.clear()

    def mark_failed(self, error: str):
        """标记整体失败"""
        self.state["status"] = "failed"
        self.state["error"] = error
        self.state["failed_at"] = datetime.now().isoformat()
        self._save()

    def clear(self):
        """清除 checkpoint 文件"""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
        self.state = {}

    def has_valid_checkpoint(self) -> bool:
        """检查是否有有效的未完成断点"""
        return (
            self.state.get("status") in ["processing", "failed"] and
            self.state.get("total_batches", 0) > 0 and
            len(self.state.get("completed_batches", [])) < self.state.get("total_batches", 0)
        )

    def get_graph_state(self) -> Optional[Dict]:
        """获取保存的图状态"""
        return self.state.get("graph_state")

    def get_quotes_list(self) -> List[Dict]:
        """获取保存的引用列表"""
        return self.state.get("quotes_list", [])

    def get_quote_index_map(self) -> Dict:
        """获取保存的引用索引映射"""
        return self.state.get("quote_index_map", {})

    def get_progress(self) -> Dict:
        """获取当前进度信息"""
        completed = len(self.state.get("completed_batches", []))
        failed = len(self.state.get("failed_batches", []))
        total = self.state.get("total_batches", 0)
        return {
            "completed": completed,
            "failed": failed,
            "total": total,
            "status": self.state.get("status", "unknown"),
            "started_at": self.state.get("started_at"),
            "current_batch": self.state.get("current_batch")
        }


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

    def to_checkpoint(self) -> Dict:
        """序列化完整状态用于断点保存"""
        return {
            "entities": {
                eid: asdict(e) for eid, e in self.entities.items()
            },
            "relations": [asdict(r) for r in self.relations],
            "_name_to_id": self._name_to_id.copy(),
            "_next_id": self._next_id
        }

    @classmethod
    def from_checkpoint(cls, data: Dict) -> "RelationshipGraph":
        """从检查点恢复图状态"""
        graph = cls()
        if not data:
            return graph

        # 恢复实体
        for eid, e_data in data.get("entities", {}).items():
            graph.entities[eid] = Entity(
                id=e_data["id"],
                name=e_data["name"],
                type=e_data["type"],
                aliases=e_data.get("aliases", []),
                quote_refs=e_data.get("quote_refs", [])
            )

        # 恢复关系
        for r_data in data.get("relations", []):
            graph.relations.append(Relation(
                from_entity=r_data["from_entity"],
                to_entity=r_data["to_entity"],
                relation_type=r_data["relation_type"],
                quote_refs=r_data.get("quote_refs", [])
            ))

        # 恢复内部状态
        graph._name_to_id = data.get("_name_to_id", {}).copy()
        graph._next_id = data.get("_next_id", 0)

        return graph


class RelationshipAnalyzer:
    """动态分组关系分析器"""

    def __init__(
        self,
        llm_base_url: str = "http://localhost:11434/v1",
        model: str = "qwen3:30b-a3b",
        batch_char_limit: int = 800,
        batch_count_limit: int = 2  # 每批最多2条引用
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
                {"role": "system", "content": "/no_think\nReturn ONLY valid JSON. No markdown, no explanation, no reasoning."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 8000,
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

    async def _analyze_batch(self, batch: List[Tuple[int, Dict]]) -> bool:
        """分析一批引用，提取实体和关系

        Returns:
            bool: 是否成功
        """
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

            return True

        except json.JSONDecodeError as e:
            print(f"  [批次分析] JSON 解析失败: {e}")
            return False
        except Exception as e:
            import traceback
            print(f"  [批次分析] 失败: {type(e).__name__}: {e}")
            traceback.print_exc()
            return False

    async def analyze(
        self,
        quotes: List[Dict],
        progress_callback=None,
        checkpoint: Optional[RelationshipCheckpoint] = None,
        quote_index_map: Optional[Dict] = None
    ) -> Dict:
        """
        执行关系分析（支持断点续传）

        Args:
            quotes: [{quote, standard_key, exhibit_id, page, ...}, ...]
            progress_callback: (current_batch, total_batches, message) -> None
            checkpoint: 断点管理器（可选）
            quote_index_map: 引用索引映射（可选，用于断点恢复）

        Returns:
            {entities, relations, l1_evidence, quote_index_map, stats}
        """
        MAX_RETRIES = 3  # 单批次最大重试次数

        # 保存引用映射
        if quote_index_map:
            self.quote_index_map = {int(k): v for k, v in quote_index_map.items()}
        else:
            for idx, q in enumerate(quotes):
                self.quote_index_map[idx] = q

        # 动态分组
        groups = self._group_quotes_by_length(quotes)
        total_batches = len(groups)

        # 检查是否从断点恢复
        resume_batch = 0
        if checkpoint and checkpoint.has_valid_checkpoint():
            resume_batch = checkpoint.get_resume_point()
            graph_state = checkpoint.get_graph_state()
            if graph_state:
                self.graph = RelationshipGraph.from_checkpoint(graph_state)
            print(f"[关系分析] 从批次 {resume_batch + 1} 恢复 (已完成 {resume_batch}/{total_batches})")
            if progress_callback:
                progress_callback(resume_batch, total_batches, f"从批次 {resume_batch + 1} 恢复")
        else:
            print(f"[关系分析] {len(quotes)} 条引用 → {total_batches} 个批次")
            # 初始化新的 checkpoint
            if checkpoint:
                checkpoint.init_new(total_batches, quotes, self.quote_index_map)

        # 逐批处理
        for batch_idx, batch in enumerate(groups):
            # 跳过已完成的批次
            if checkpoint and checkpoint.is_batch_completed(batch_idx):
                continue

            batch_quotes = [idx for idx, _ in batch]
            print(f"  批次 {batch_idx + 1}/{total_batches}: 引用 {batch_quotes}")

            if progress_callback:
                progress_callback(batch_idx + 1, total_batches, f"处理批次 {batch_idx + 1}/{total_batches}")

            # 标记处理中
            if checkpoint:
                checkpoint.mark_batch_in_progress(batch_idx)

            # 带重试的批次处理
            success = False
            for retry in range(MAX_RETRIES):
                success = await self._analyze_batch(batch)
                if success:
                    break
                print(f"  批次 {batch_idx + 1} 第 {retry + 1} 次重试失败")
                await asyncio.sleep(1.0)  # 重试前等待

            # 保存批次结果
            if checkpoint:
                if success:
                    checkpoint.save_batch(batch_idx, self.graph.to_checkpoint())
                else:
                    checkpoint.mark_batch_failed(batch_idx)
                    print(f"  批次 {batch_idx + 1} 最终失败，已记录")

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
                "analyzed_at": datetime.now().isoformat(),
                "resumed_from_batch": resume_batch if resume_batch > 0 else None,
                "failed_batches": checkpoint.state.get("failed_batches", []) if checkpoint else []
            }
        }

        # 标记完成（会自动删除 checkpoint 文件）
        if checkpoint:
            checkpoint.mark_completed()

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
    batch_char_limit: int = 800,
    batch_count_limit: int = 2,
    progress_callback=None,
    checkpoint: Optional[RelationshipCheckpoint] = None,
    quote_index_map: Optional[Dict] = None
) -> Dict:
    """
    运行关系分析（支持断点续传）

    Args:
        quotes: 引用列表
        llm_base_url: LLM API 地址
        model: 模型名称
        batch_char_limit: 批次字符上限
        progress_callback: 进度回调
        checkpoint: 断点管理器（可选）
        quote_index_map: 引用索引映射（用于恢复时）

    Returns:
        分析结果
    """
    analyzer = RelationshipAnalyzer(
        llm_base_url=llm_base_url,
        model=model,
        batch_char_limit=batch_char_limit,
        batch_count_limit=batch_count_limit
    )
    return await analyzer.analyze(
        quotes,
        progress_callback,
        checkpoint=checkpoint,
        quote_index_map=quote_index_map
    )
