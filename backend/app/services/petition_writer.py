"""
Petition Writer - 两步写作服务

Step 3a: 自由写作 (GPT-4o) - 生成高质量法律文本
Step 3b: 句子级标注 (GPT-4o-mini strict schema) - 将段落拆分为句子并标注 snippet_ids

这种分离确保：
1. 写作质量不受 JSON schema 约束影响
2. 标注使用 strict schema 保证 100% 结构合规
"""

import json
from typing import List, Dict, Optional
from collections import defaultdict
from pathlib import Path
from datetime import datetime

from .llm_client import call_llm_text, call_llm
from .snippet_registry import load_registry
from .snippet_linker import load_links


# EB-1A 标准名称映射
EB1A_STANDARDS = {
    "awards": "Awards",
    "membership": "Membership",
    "press": "Published Material",
    "judging": "Judging",
    "original_contribution": "Original Contribution",
    "scholarly_articles": "Scholarly Articles",
    "exhibitions": "Artistic Exhibitions",
    "leading_role": "Leading or Critical Role",
    "high_salary": "High Salary",
    "commercial_success": "Commercial Success"
}

# L-1 标准名称映射
L1_STANDARDS = {
    "qualifying_relationship": "Qualifying Corporate Relationship",
    "qualifying_employment": "Qualifying Employment Abroad",
    "qualifying_capacity": "Executive/Managerial Capacity",
    "doing_business": "Active Business Operations"
}


async def generate_petition_prose(
    project_id: str,
    section: str,
    snippet_registry: List[Dict] = None,
    snippet_links: List[Dict] = None
) -> str:
    """
    Step 3a: 自由写作

    生成高质量的法律论证段落，不要求 JSON 格式
    只传入律师已映射到该 standard 的 snippets

    Args:
        project_id: 项目 ID
        section: 标准 key (如 "scholarly_articles", "qualifying_relationship")
        snippet_registry: snippet 列表，如不提供则从存储加载
        snippet_links: snippet 关联列表，如不提供则从存储加载

    Returns:
        生成的段落文本
    """
    # 加载数据
    if snippet_registry is None:
        snippet_registry = load_registry(project_id)
    if snippet_links is None:
        snippet_links = load_links(project_id)

    # 过滤出该 standard 的 snippets
    relevant_snippets = [s for s in snippet_registry if s.get("standard_key") == section]

    if not relevant_snippets:
        return f"No evidence has been mapped to the {section} criterion."

    # 构建结构化上下文
    context = _build_structured_context(relevant_snippets, snippet_links)

    # 获取标准名称
    standard_name = EB1A_STANDARDS.get(section) or L1_STANDARDS.get(section, section)

    prompt = f"""You are a Senior Immigration Attorney writing an EB-1A petition.

Write a persuasive, well-structured paragraph (200-400 words) for the "{standard_name}" criterion.

Use ONLY the following evidence. Do not invent any facts.

{context}

Requirements:
- Open with a legal conclusion statement
- Present primary evidence with specific facts, dates, and figures
- Include supporting context and quantitative data
- Close with a reinforcing statement
- Professional legal tone throughout
- Reference evidence naturally (e.g. "as evidenced by..." "according to...")
- Do NOT include citation markers like [1] or [Exhibit A] - we will add those later
"""

    system_prompt = """You are an experienced immigration attorney specializing in EB-1A extraordinary ability petitions.
Your writing is precise, persuasive, and follows legal drafting conventions.
You focus on demonstrating how the evidence meets USCIS requirements."""

    result = await call_llm_text(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.7
    )

    return result


async def annotate_sentences(
    paragraph_text: str,
    snippet_registry: List[Dict],
    section: str
) -> List[Dict]:
    """
    Step 3b: 句子级标注

    将自由段落拆分为句子并标注每句话使用的 snippet_ids
    使用 GPT-4o-mini 的 strict JSON schema 保证 100% 合规

    Args:
        paragraph_text: 3a 生成的段落文本
        snippet_registry: 完整的 snippet 注册表
        section: 标准 key

    Returns:
        sentences: [{
            "text": "句子文本",
            "snippet_ids": ["snip_xxx", "snip_yyy"]
        }]
    """
    # 过滤出该 standard 的 snippets
    relevant_snippets = [s for s in snippet_registry if s.get("standard_key") == section]

    if not relevant_snippets:
        # 无证据时返回空标注
        return [{"text": paragraph_text, "snippet_ids": []}]

    # 构建 snippet reference list
    snippet_ref = "\n".join(
        f'[{s["snippet_id"]}]: "{s["text"][:150]}..."' if len(s["text"]) > 150 else f'[{s["snippet_id"]}]: "{s["text"]}"'
        for s in relevant_snippets
    )

    prompt = f"""Split this paragraph into individual sentences and annotate each with the snippet IDs it draws from.

PARAGRAPH:
{paragraph_text}

AVAILABLE SNIPPETS:
{snippet_ref}

Rules:
1. Every factual claim MUST reference at least one snippet_id
2. ONLY use snippet_ids from the list above
3. Transitional/concluding sentences with no specific fact can have empty snippet_ids
4. Preserve the exact text - do not rewrite sentences
5. Split at sentence boundaries (periods, but not abbreviations like "Dr." or "Inc.")
"""

    # Strict JSON schema
    schema = {
        "type": "object",
        "properties": {
            "sentences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The exact sentence text"
                        },
                        "snippet_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of snippet_ids this sentence draws from"
                        }
                    },
                    "required": ["text", "snippet_ids"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["sentences"],
        "additionalProperties": False
    }

    result = await call_llm(
        prompt=prompt,
        json_schema=schema,
        temperature=0.1
    )

    sentences = result.get("sentences", [])

    # 验证 snippet_ids 都是有效的
    valid_ids = {s["snippet_id"] for s in relevant_snippets}
    for sent in sentences:
        sent["snippet_ids"] = [sid for sid in sent.get("snippet_ids", []) if sid in valid_ids]

    return sentences


def _build_structured_context(
    snippets: List[Dict],
    links: List[Dict]
) -> str:
    """
    构建给写作 LLM 的结构化上下文

    利用 snippet links 将相关 snippets 分组呈现
    让 LLM 知道哪些证据应该放在一起讨论

    使用 Union-Find 算法进行聚类
    """
    if not snippets:
        return "No evidence available."

    snippet_ids = set(s["snippet_id"] for s in snippets)
    snippet_map = {s["snippet_id"]: s for s in snippets}

    # Union-Find 数据结构
    parent = {sid: sid for sid in snippet_ids}

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])  # 路径压缩
        return parent[x]

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # 根据 links 合并相关 snippets
    for link in links:
        a, b = link.get("snippet_a"), link.get("snippet_b")
        strength = link.get("strength", 0)

        # 只合并强度 >= 0.3 且都在当前 snippets 中的
        if a in snippet_ids and b in snippet_ids and strength >= 0.3:
            union(a, b)

    # 按 cluster 分组
    clusters = defaultdict(list)
    for sid in snippet_ids:
        clusters[find(sid)].append(sid)

    # 格式化输出
    lines = []
    group_num = 1

    for root, members in clusters.items():
        if len(members) > 1:
            # 找出这组共享的实体
            shared_entities = set()
            for link in links:
                if link.get("snippet_a") in members and link.get("snippet_b") in members:
                    shared_entities.update(link.get("shared_entities", []))

            shared_str = ", ".join(list(shared_entities)[:3]) if shared_entities else "related evidence"
            lines.append(f"\n## Evidence Group {group_num} (related through: {shared_str})")
            group_num += 1

        for sid in sorted(members):
            s = snippet_map[sid]
            exhibit = s.get("exhibit_id", "Unknown")
            page = s.get("page", "?")
            text = s.get("text", "")

            lines.append(f"\n  [{s['snippet_id']}] (Exhibit {exhibit}, p.{page}):")
            lines.append(f'  "{text}"')

    return "\n".join(lines)


async def write_petition_section(
    project_id: str,
    section: str
) -> Dict:
    """
    完整的两步写作流程

    Returns:
        {
            "section": str,
            "paragraph_text": str,
            "sentences": List[Dict],
            "snippet_count": int
        }
    """
    # 加载数据
    snippet_registry = load_registry(project_id)
    snippet_links = load_links(project_id)

    # 3a: 自由写作
    paragraph = await generate_petition_prose(
        project_id, section, snippet_registry, snippet_links
    )

    # 3b: 句子级标注
    sentences = await annotate_sentences(
        paragraph, snippet_registry, section
    )

    # 统计
    relevant_snippets = [s for s in snippet_registry if s.get("standard_key") == section]

    return {
        "section": section,
        "paragraph_text": paragraph,
        "sentences": sentences,
        "snippet_count": len(relevant_snippets)
    }


# ==================== 存储函数 ====================

DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


def save_constrained_writing(
    project_id: str,
    section: str,
    sentences: List[Dict],
    paragraph_text: str
) -> str:
    """保存两步写作结果"""
    project_dir = PROJECTS_DIR / project_id
    writing_dir = project_dir / "writing_v2"
    writing_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    version_id = timestamp.strftime("%Y%m%d_%H%M%S")

    data = {
        "version_id": version_id,
        "timestamp": timestamp.isoformat(),
        "section": section,
        "paragraph_text": paragraph_text,
        "sentences": sentences,
        "sentence_count": len(sentences),
        "annotated_count": sum(1 for s in sentences if s.get("snippet_ids"))
    }

    filename = f"writing_{section}_{version_id}.json"
    with open(writing_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return version_id


def load_constrained_writing(
    project_id: str,
    section: str,
    version_id: str = None
) -> Optional[Dict]:
    """加载两步写作结果"""
    writing_dir = PROJECTS_DIR / project_id / "writing_v2"
    if not writing_dir.exists():
        return None

    if version_id:
        filepath = writing_dir / f"writing_{section}_{version_id}.json"
    else:
        # 获取最新版本
        files = sorted(writing_dir.glob(f"writing_{section}_*.json"), reverse=True)
        if not files:
            return None
        filepath = files[0]

    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_all_constrained_writing(project_id: str) -> Dict[str, Dict]:
    """加载所有 section 的最新写作结果"""
    writing_dir = PROJECTS_DIR / project_id / "writing_v2"
    if not writing_dir.exists():
        return {}

    sections = {}
    for f in sorted(writing_dir.glob("writing_*.json"), reverse=True):
        with open(f, 'r', encoding='utf-8') as file:
            data = json.load(file)
            section = data.get("section")
            if section and section not in sections:
                sections[section] = data

    return sections
