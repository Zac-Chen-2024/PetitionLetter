"""
Snippet Linker - 从实体图推导 snippet 间关联信号

输入：relationship_analyzer 产出的实体图 + snippet_registry
输出：snippet pairs + 关联类型 + 共享实体

不调用 LLM，纯图算法。零额外成本。

原理：
如果两个 snippets 提到了同一个实体，它们之间就有 co-reference 关联：

snippet_003 ──提到──→ Entity("Nature 论文") ←──提到── snippet_007
  → 推导：snippet_003 ↔ snippet_007 关联，原因 = 共享实体 "Nature 论文"
"""

import json
from typing import List, Dict, Tuple, Set
from collections import defaultdict
from pathlib import Path

# 数据存储根目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


def build_snippet_links(
    graph_data: Dict,
    snippet_registry: List[Dict],
    min_shared_entities: int = 1
) -> List[Dict]:
    """
    从实体图推导 snippet 关联

    Args:
        graph_data: relationship_analyzer 输出 {entities, relations, quote_index_map}
        snippet_registry: [{snippet_id, quote_index, ...}]
        min_shared_entities: 至少共享几个实体才算关联

    Returns:
        links: [
            {
                "snippet_a": "snip_xxx",
                "snippet_b": "snip_yyy",
                "link_type": "co-reference",
                "shared_entities": ["Nature 论文", "Dr. Chen"],
                "strength": 0.8  # 共享实体数 / 两个 snippet 的平均实体数
            }
        ]
    """
    if not graph_data or not snippet_registry:
        return []

    # 建立 quote_index → snippet_id 映射
    # quote_index 是 relationship_analyzer 里的 quote 索引
    idx_to_snippet = {}
    for s in snippet_registry:
        quote_idx = s.get("quote_index")
        if quote_idx is not None:
            idx_to_snippet[int(quote_idx)] = s["snippet_id"]

    # 如果没有 quote_index，尝试按顺序映射
    if not idx_to_snippet:
        for i, s in enumerate(snippet_registry):
            idx_to_snippet[i] = s["snippet_id"]

    # 建立 entity → snippet_ids 倒排索引
    entity_to_snippets: Dict[str, Set[str]] = defaultdict(set)
    snippet_entity_count: Dict[str, int] = defaultdict(int)

    entities = graph_data.get("entities", [])
    for entity in entities:
        entity_name = entity.get("name", "")
        quote_refs = entity.get("quote_refs", [])

        for ref in quote_refs:
            try:
                ref_int = int(ref)
                if ref_int in idx_to_snippet:
                    sid = idx_to_snippet[ref_int]
                    entity_to_snippets[entity_name].add(sid)
                    snippet_entity_count[sid] += 1
            except (ValueError, TypeError):
                continue

    # 遍历所有实体，找到共享同一实体的 snippet pairs
    pair_shared: Dict[Tuple[str, str], List[str]] = defaultdict(list)

    for entity_name, snippet_ids in entity_to_snippets.items():
        if len(snippet_ids) < 2:
            continue

        snippet_list = sorted(snippet_ids)
        for i in range(len(snippet_list)):
            for j in range(i + 1, len(snippet_list)):
                pair_key = (snippet_list[i], snippet_list[j])
                pair_shared[pair_key].append(entity_name)

    # 过滤并生成 links
    links = []
    for (sa, sb), shared in pair_shared.items():
        if len(shared) < min_shared_entities:
            continue

        # 计算关联强度：共享实体数 / 两个 snippet 平均实体数
        avg_entities = (snippet_entity_count.get(sa, 1) + snippet_entity_count.get(sb, 1)) / 2
        strength = min(1.0, len(shared) / max(avg_entities, 1))

        links.append({
            "snippet_a": sa,
            "snippet_b": sb,
            "link_type": "co-reference",
            "shared_entities": shared[:5],  # 最多列 5 个
            "strength": round(strength, 2)
        })

    # 按强度降序排列
    links.sort(key=lambda x: x["strength"], reverse=True)

    return links


def build_snippet_links_from_relations(
    graph_data: Dict,
    snippet_registry: List[Dict]
) -> List[Dict]:
    """
    从关系边推导 snippet 关联（补充方式）

    如果两个 snippets 被同一条 relation 引用，也建立关联
    """
    if not graph_data or not snippet_registry:
        return []

    # 建立 quote_index → snippet_id 映射
    idx_to_snippet = {}
    for s in snippet_registry:
        quote_idx = s.get("quote_index")
        if quote_idx is not None:
            idx_to_snippet[int(quote_idx)] = s["snippet_id"]

    if not idx_to_snippet:
        for i, s in enumerate(snippet_registry):
            idx_to_snippet[i] = s["snippet_id"]

    # 遍历 relations
    pair_relations: Dict[Tuple[str, str], List[str]] = defaultdict(list)

    relations = graph_data.get("relations", [])
    for rel in relations:
        quote_refs = rel.get("quote_refs", [])
        rel_type = rel.get("relation_type", "related")

        # 转换为 snippet_ids
        snippet_ids = []
        for ref in quote_refs:
            try:
                ref_int = int(ref)
                if ref_int in idx_to_snippet:
                    snippet_ids.append(idx_to_snippet[ref_int])
            except (ValueError, TypeError):
                continue

        # 两两配对
        snippet_ids = sorted(set(snippet_ids))
        for i in range(len(snippet_ids)):
            for j in range(i + 1, len(snippet_ids)):
                pair_key = (snippet_ids[i], snippet_ids[j])
                pair_relations[pair_key].append(rel_type)

    # 生成 links
    links = []
    for (sa, sb), rel_types in pair_relations.items():
        links.append({
            "snippet_a": sa,
            "snippet_b": sb,
            "link_type": "relation-based",
            "shared_relations": list(set(rel_types))[:5],
            "strength": min(1.0, len(rel_types) * 0.3)  # 每条关系贡献 0.3
        })

    return links


def merge_links(
    entity_links: List[Dict],
    relation_links: List[Dict]
) -> List[Dict]:
    """
    合并实体关联和关系关联

    同一对 snippets 的多种关联合并，强度取最大值
    """
    pair_map: Dict[Tuple[str, str], Dict] = {}

    # 添加实体关联
    for link in entity_links:
        key = (link["snippet_a"], link["snippet_b"])
        if key not in pair_map:
            pair_map[key] = {
                "snippet_a": link["snippet_a"],
                "snippet_b": link["snippet_b"],
                "link_type": "hybrid",
                "shared_entities": link.get("shared_entities", []),
                "shared_relations": [],
                "strength": link["strength"]
            }
        else:
            pair_map[key]["shared_entities"].extend(link.get("shared_entities", []))
            pair_map[key]["strength"] = max(pair_map[key]["strength"], link["strength"])

    # 添加关系关联
    for link in relation_links:
        key = (link["snippet_a"], link["snippet_b"])
        if key not in pair_map:
            pair_map[key] = {
                "snippet_a": link["snippet_a"],
                "snippet_b": link["snippet_b"],
                "link_type": "hybrid",
                "shared_entities": [],
                "shared_relations": link.get("shared_relations", []),
                "strength": link["strength"]
            }
        else:
            pair_map[key]["shared_relations"].extend(link.get("shared_relations", []))
            pair_map[key]["strength"] = max(pair_map[key]["strength"], link["strength"])

    # 去重并限制数量
    for key, link in pair_map.items():
        link["shared_entities"] = list(set(link["shared_entities"]))[:5]
        link["shared_relations"] = list(set(link["shared_relations"]))[:5]

        # 更新 link_type
        if link["shared_entities"] and link["shared_relations"]:
            link["link_type"] = "hybrid"
        elif link["shared_entities"]:
            link["link_type"] = "co-reference"
        else:
            link["link_type"] = "relation-based"

    # 转为列表并排序
    links = list(pair_map.values())
    links.sort(key=lambda x: x["strength"], reverse=True)

    return links


def get_snippets_dir(project_id: str) -> Path:
    """获取 snippets 存储目录"""
    snippets_dir = PROJECTS_DIR / project_id / "snippets"
    snippets_dir.mkdir(parents=True, exist_ok=True)
    return snippets_dir


def save_links(project_id: str, links: List[Dict]):
    """保存 snippet 关联到 JSON 文件"""
    snippets_dir = get_snippets_dir(project_id)
    links_file = snippets_dir / "links.json"

    from datetime import datetime, timezone
    data = {
        "version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "link_count": len(links),
        "links": links
    }

    with open(links_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_links(project_id: str) -> List[Dict]:
    """加载 snippet 关联"""
    snippets_dir = get_snippets_dir(project_id)
    links_file = snippets_dir / "links.json"

    if not links_file.exists():
        return []

    with open(links_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get("links", [])


def get_related_snippets(project_id: str, snippet_id: str) -> List[Dict]:
    """获取与指定 snippet 相关的所有 snippets"""
    links = load_links(project_id)

    related = []
    for link in links:
        if link["snippet_a"] == snippet_id:
            related.append({
                "snippet_id": link["snippet_b"],
                "link_type": link["link_type"],
                "shared_entities": link.get("shared_entities", []),
                "strength": link["strength"]
            })
        elif link["snippet_b"] == snippet_id:
            related.append({
                "snippet_id": link["snippet_a"],
                "link_type": link["link_type"],
                "shared_entities": link.get("shared_entities", []),
                "strength": link["strength"]
            })

    # 按强度排序
    related.sort(key=lambda x: x["strength"], reverse=True)
    return related


def get_link_stats(project_id: str) -> Dict:
    """获取关联统计信息"""
    links = load_links(project_id)

    if not links:
        return {
            "total_links": 0,
            "avg_strength": 0,
            "by_type": {},
            "connected_snippets": 0
        }

    # 统计
    by_type = defaultdict(int)
    connected = set()
    total_strength = 0

    for link in links:
        by_type[link["link_type"]] += 1
        connected.add(link["snippet_a"])
        connected.add(link["snippet_b"])
        total_strength += link["strength"]

    return {
        "total_links": len(links),
        "avg_strength": round(total_strength / len(links), 2) if links else 0,
        "by_type": dict(by_type),
        "connected_snippets": len(connected)
    }
