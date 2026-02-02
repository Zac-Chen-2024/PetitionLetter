"""
本地文件存储服务
将项目数据保存为本地 JSON 文件，类似日志系统
"""
import os
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

# 数据存储根目录 (backend/data)
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


def ensure_dirs():
    """确保数据目录存在"""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def get_project_dir(project_id: str) -> Path:
    """获取项目目录"""
    return PROJECTS_DIR / project_id


def get_project_file(project_id: str, filename: str) -> Path:
    """获取项目文件路径"""
    return get_project_dir(project_id) / filename


# ==================== 项目管理 ====================

def list_projects() -> List[Dict]:
    """列出所有项目"""
    ensure_dirs()
    projects = []

    for item in PROJECTS_DIR.iterdir():
        if item.is_dir():
            meta_file = item / "meta.json"
            if meta_file.exists():
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    projects.append(meta)

    # 按创建时间倒序
    projects.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
    return projects


def create_project(name: str) -> Dict:
    """创建新项目"""
    ensure_dirs()

    project_id = f"project-{int(datetime.now().timestamp() * 1000)}"
    project_dir = get_project_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    # 创建子目录
    (project_dir / "analysis").mkdir(exist_ok=True)
    (project_dir / "relationship").mkdir(exist_ok=True)
    (project_dir / "writing").mkdir(exist_ok=True)

    meta = {
        "id": project_id,
        "name": name,
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat()
    }

    with open(project_dir / "meta.json", 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 初始化空的文档列表
    with open(project_dir / "documents.json", 'w', encoding='utf-8') as f:
        json.dump([], f, ensure_ascii=False, indent=2)

    return meta


def get_project(project_id: str) -> Optional[Dict]:
    """获取项目信息"""
    meta_file = get_project_file(project_id, "meta.json")
    if not meta_file.exists():
        return None

    with open(meta_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def delete_project(project_id: str) -> bool:
    """删除项目"""
    import shutil
    project_dir = get_project_dir(project_id)
    if project_dir.exists():
        shutil.rmtree(project_dir)
        return True
    return False


def update_project_meta(project_id: str, updates: Dict) -> Optional[Dict]:
    """更新项目元数据（如受益人姓名等）"""
    meta_file = get_project_file(project_id, "meta.json")
    if not meta_file.exists():
        return None

    with open(meta_file, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    # 更新提供的字段
    for key, value in updates.items():
        if value is not None:
            meta[key] = value

    meta["updatedAt"] = datetime.now().isoformat()

    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return meta


# ==================== 文档管理 ====================

def get_documents(project_id: str) -> List[Dict]:
    """获取项目的所有文档"""
    docs_file = get_project_file(project_id, "documents.json")
    if not docs_file.exists():
        return []

    with open(docs_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_documents(project_id: str, documents: List[Dict]):
    """保存文档列表"""
    project_dir = get_project_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    docs_file = project_dir / "documents.json"
    with open(docs_file, 'w', encoding='utf-8') as f:
        json.dump(documents, f, ensure_ascii=False, indent=2)

    # 更新项目修改时间
    _update_project_time(project_id)


def add_document(project_id: str, document: Dict) -> Dict:
    """添加文档"""
    documents = get_documents(project_id)
    documents.append(document)
    save_documents(project_id, documents)
    return document


def update_document(project_id: str, doc_id: str, updates: Dict) -> Optional[Dict]:
    """更新文档"""
    documents = get_documents(project_id)
    for i, doc in enumerate(documents):
        if doc.get('id') == doc_id:
            documents[i].update(updates)
            save_documents(project_id, documents)
            return documents[i]
    return None


# ==================== 分析结果 ====================

def save_analysis(project_id: str, analysis_data: Dict) -> str:
    """保存分析结果，返回版本 ID"""
    project_dir = get_project_dir(project_id)
    analysis_dir = project_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # 使用时间戳作为版本 ID
    timestamp = datetime.now()
    version_id = timestamp.strftime("%Y%m%d_%H%M%S")

    version_data = {
        "version_id": version_id,
        "timestamp": timestamp.isoformat(),
        "results": analysis_data
    }

    filename = f"analysis_{version_id}.json"
    with open(analysis_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(version_data, f, ensure_ascii=False, indent=2)

    _update_project_time(project_id)
    return version_id


def list_analysis_versions(project_id: str) -> List[Dict]:
    """列出所有分析版本"""
    analysis_dir = get_project_dir(project_id) / "analysis"
    if not analysis_dir.exists():
        return []

    versions = []
    for f in sorted(analysis_dir.glob("analysis_*.json"), reverse=True):
        with open(f, 'r', encoding='utf-8') as file:
            data = json.load(file)
            versions.append({
                "version_id": data.get("version_id"),
                "timestamp": data.get("timestamp"),
                "doc_count": len(data.get("results", {}))
            })

    return versions


def get_analysis(project_id: str, version_id: str = None) -> Optional[Dict]:
    """获取分析结果，不指定版本则返回最新"""
    analysis_dir = get_project_dir(project_id) / "analysis"
    if not analysis_dir.exists():
        return None

    if version_id:
        filename = f"analysis_{version_id}.json"
        filepath = analysis_dir / filename
    else:
        # 获取最新版本
        files = sorted(analysis_dir.glob("analysis_*.json"), reverse=True)
        if not files:
            return None
        filepath = files[0]

    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


# ==================== 关系分析 ====================

def save_relationship(project_id: str, relationship_data: Dict) -> str:
    """保存关系分析结果"""
    project_dir = get_project_dir(project_id)
    rel_dir = project_dir / "relationship"
    rel_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    version_id = timestamp.strftime("%Y%m%d_%H%M%S")

    version_data = {
        "version_id": version_id,
        "timestamp": timestamp.isoformat(),
        "data": relationship_data
    }

    filename = f"relationship_{version_id}.json"
    with open(rel_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(version_data, f, ensure_ascii=False, indent=2)

    _update_project_time(project_id)
    return version_id


def save_quote_index_map(project_id: str, quote_index_map: Dict) -> str:
    """保存引用索引映射（用于关系分析结果回溯到 bbox）

    Args:
        project_id: 项目 ID
        quote_index_map: {idx: {exhibit_id, material_id, page, quote, standard_key, bbox}}

    Returns:
        version_id
    """
    project_dir = get_project_dir(project_id)
    rel_dir = project_dir / "relationship"
    rel_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    version_id = timestamp.strftime("%Y%m%d_%H%M%S")

    data = {
        "version_id": version_id,
        "timestamp": timestamp.isoformat(),
        "quote_count": len(quote_index_map),
        "quotes": quote_index_map
    }

    filename = f"quote_index_map_{version_id}.json"
    with open(rel_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return version_id


def load_quote_index_map(project_id: str, version_id: str = None) -> Optional[Dict]:
    """加载引用索引映射"""
    rel_dir = get_project_dir(project_id) / "relationship"
    if not rel_dir.exists():
        return None

    if version_id:
        filepath = rel_dir / f"quote_index_map_{version_id}.json"
    else:
        # 获取最新版本
        files = sorted(rel_dir.glob("quote_index_map_*.json"), reverse=True)
        if not files:
            return None
        filepath = files[0]

    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get("quotes", {})


def list_relationship_versions(project_id: str) -> List[Dict]:
    """列出所有关系分析版本"""
    rel_dir = get_project_dir(project_id) / "relationship"
    if not rel_dir.exists():
        return []

    versions = []
    for f in sorted(rel_dir.glob("relationship_*.json"), reverse=True):
        with open(f, 'r', encoding='utf-8') as file:
            data = json.load(file)
            versions.append({
                "version_id": data.get("version_id"),
                "timestamp": data.get("timestamp"),
                "entity_count": len(data.get("data", {}).get("entities", [])),
                "relation_count": len(data.get("data", {}).get("relations", []))
            })

    return versions


def get_relationship(project_id: str, version_id: str = None) -> Optional[Dict]:
    """获取关系分析结果"""
    rel_dir = get_project_dir(project_id) / "relationship"
    if not rel_dir.exists():
        return None

    if version_id:
        filename = f"relationship_{version_id}.json"
        filepath = rel_dir / filename
    else:
        # 排除 snapshots 文件，只匹配时间戳格式的文件
        files = [f for f in rel_dir.glob("relationship_*.json")
                 if f.name != "relationship_snapshots.json"]
        files = sorted(files, reverse=True)
        if not files:
            return None
        filepath = files[0]

    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


# ==================== 关系图快照管理 ====================

def get_snapshots_file(project_id: str) -> Path:
    """获取快照元数据文件路径"""
    rel_dir = get_project_dir(project_id) / "relationship"
    rel_dir.mkdir(parents=True, exist_ok=True)
    return rel_dir / "relationship_snapshots.json"


def list_relationship_snapshots(project_id: str) -> List[Dict]:
    """列出所有关系分析快照"""
    snapshots_file = get_snapshots_file(project_id)
    if not snapshots_file.exists():
        return []

    with open(snapshots_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get("snapshots", [])


def get_current_snapshot_id(project_id: str) -> Optional[str]:
    """获取当前活动快照 ID"""
    snapshots_file = get_snapshots_file(project_id)
    if not snapshots_file.exists():
        return None

    with open(snapshots_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get("current_snap")


def create_relationship_snapshot(
    project_id: str,
    label: str,
    is_original: bool = False,
    parent_snap: Optional[str] = None
) -> Dict:
    """
    创建新的关系分析快照

    Args:
        project_id: 项目 ID
        label: 快照标签
        is_original: 是否为原始分析结果
        parent_snap: 父快照 ID

    Returns:
        创建的快照元数据
    """
    # 获取当前最新的关系分析数据
    current_rel = get_relationship(project_id)
    if not current_rel:
        raise ValueError("No relationship data to snapshot")

    # 生成快照 ID
    timestamp = datetime.now()
    snap_id = f"snap_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    version_id = current_rel.get("version_id")

    # 创建快照元数据
    snapshot = {
        "id": snap_id,
        "version_id": version_id,
        "label": label,
        "created_at": timestamp.isoformat(),
        "is_original": is_original,
        "parent_snap": parent_snap,
        "stats": {
            "entity_count": len(current_rel.get("data", {}).get("entities", [])),
            "relation_count": len(current_rel.get("data", {}).get("relations", []))
        }
    }

    # 加载或初始化快照列表
    snapshots_file = get_snapshots_file(project_id)
    if snapshots_file.exists():
        with open(snapshots_file, 'r', encoding='utf-8') as f:
            snapshots_data = json.load(f)
    else:
        snapshots_data = {"snapshots": [], "current_snap": None}

    # 添加新快照
    snapshots_data["snapshots"].append(snapshot)
    snapshots_data["current_snap"] = snap_id

    # 保存快照元数据
    with open(snapshots_file, 'w', encoding='utf-8') as f:
        json.dump(snapshots_data, f, ensure_ascii=False, indent=2)

    return snapshot


def rollback_to_snapshot(project_id: str, snapshot_id: str) -> Dict:
    """
    回滚到指定快照

    Args:
        project_id: 项目 ID
        snapshot_id: 目标快照 ID

    Returns:
        回滚后的关系数据
    """
    # 加载快照列表
    snapshots_file = get_snapshots_file(project_id)
    if not snapshots_file.exists():
        raise ValueError("No snapshots found")

    with open(snapshots_file, 'r', encoding='utf-8') as f:
        snapshots_data = json.load(f)

    # 查找目标快照
    target_snap = None
    for snap in snapshots_data.get("snapshots", []):
        if snap["id"] == snapshot_id:
            target_snap = snap
            break

    if not target_snap:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    # 获取快照对应的关系数据
    version_id = target_snap["version_id"]
    rel_data = get_relationship(project_id, version_id)

    if not rel_data:
        raise ValueError(f"Relationship data for version {version_id} not found")

    # 保存为新版本（回滚操作本身也创建新版本）
    new_version_id = save_relationship(project_id, rel_data.get("data", {}))

    # 更新当前快照指针
    snapshots_data["current_snap"] = snapshot_id

    # 保存快照元数据
    with open(snapshots_file, 'w', encoding='utf-8') as f:
        json.dump(snapshots_data, f, ensure_ascii=False, indent=2)

    return {
        "snapshot_id": snapshot_id,
        "version_id": new_version_id,
        "label": target_snap.get("label"),
        "data": rel_data.get("data", {})
    }


def update_relationship_data(project_id: str, new_data: Dict) -> str:
    """
    更新关系数据并保存为新版本

    Args:
        project_id: 项目 ID
        new_data: 新的关系数据 {entities, relations, ...}

    Returns:
        新版本 ID
    """
    return save_relationship(project_id, new_data)


def convert_relationship_to_frontend_format(raw_data: Dict) -> Dict:
    """将后端关系分析结果转换为前端期望的格式

    后端格式:
        entities: [{id, name, type, aliases, quote_refs}]
        relations: [{from_entity, to_entity, relation_type, quote_refs}]
        l1_evidence: [{standard, quote_refs, strength}]
        quote_index_map: {idx: {quote, standard_key, exhibit_id, page}}

    前端格式:
        entities: [{id, type, name, documents, attributes}]
        relations: [{source_id, target_id, relation_type, evidence, description}]
        evidence_chains: [{claim, documents, strength, reasoning}]
    """
    if not raw_data or "data" not in raw_data:
        return raw_data

    data = raw_data.get("data", {})
    quote_map = data.get("quote_index_map", {})

    # 辅助函数: quote_refs -> exhibit_id 列表
    def refs_to_exhibits(refs: List[int]) -> List[str]:
        exhibits = set()
        for ref in refs:
            ref_data = quote_map.get(str(ref), {})
            exhibit_id = ref_data.get("exhibit_id", "")
            if exhibit_id:
                exhibits.add(exhibit_id)
        return list(exhibits)

    # L1 标准名称映射
    standard_names = {
        "qualifying_relationship": "Qualifying Corporate Relationship",
        "qualifying_employment": "Qualifying Employment Abroad",
        "qualifying_capacity": "Executive/Managerial Capacity",
        "doing_business": "Active Business Operations"
    }

    # 转换 entities
    frontend_entities = []
    for e in data.get("entities", []):
        frontend_entities.append({
            "id": e.get("id", ""),
            "type": e.get("type", "unknown"),
            "name": e.get("name", ""),
            "documents": refs_to_exhibits(e.get("quote_refs", [])),
            "attributes": {
                "aliases": e.get("aliases", [])
            } if e.get("aliases") else {}
        })

    # 转换 relations
    frontend_relations = []
    for r in data.get("relations", []):
        from_id = r.get("from_entity", "")
        to_id = r.get("to_entity", "")
        rel_type = r.get("relation_type", "related_to")

        # 查找实体名称用于生成描述
        from_name = ""
        to_name = ""
        for e in data.get("entities", []):
            if e.get("id") == from_id:
                from_name = e.get("name", "")
            if e.get("id") == to_id:
                to_name = e.get("name", "")

        frontend_relations.append({
            "source_id": from_id,
            "target_id": to_id,
            "relation_type": rel_type,
            "evidence": refs_to_exhibits(r.get("quote_refs", [])),
            "description": f"{from_name} {rel_type.replace('_', ' ')} {to_name}"
        })

    # 转换 l1_evidence -> evidence_chains
    evidence_chains = []
    for ev in data.get("l1_evidence", []):
        standard_key = ev.get("standard", "")
        refs = ev.get("quote_refs", [])
        strength = ev.get("strength", "moderate")

        # 收集该标准下的引用文本（用于 reasoning）
        sample_quotes = []
        for ref in refs[:3]:  # 最多取3条作为示例
            ref_data = quote_map.get(str(ref), {})
            quote_text = ref_data.get("quote", "")[:100]
            if quote_text:
                sample_quotes.append(quote_text)

        evidence_chains.append({
            "claim": standard_names.get(standard_key, standard_key),
            "documents": refs_to_exhibits(refs),
            "strength": strength,
            "reasoning": f"Supported by {len(refs)} quotes from {len(refs_to_exhibits(refs))} exhibits. Examples: {'; '.join(sample_quotes)}" if sample_quotes else f"Based on {len(refs)} references."
        })

    # 返回前端格式
    return {
        "version_id": raw_data.get("version_id"),
        "timestamp": raw_data.get("timestamp"),
        "data": {
            "entities": frontend_entities,
            "relations": frontend_relations,
            "evidence_chains": evidence_chains
        },
        # 保留原始数据供调试
        "_raw_stats": data.get("stats", {}),
        "_quote_index_map": quote_map
    }


# ==================== 写作生成 ====================

def save_writing(project_id: str, section: str, text: str, citations: List[Dict]) -> str:
    """保存生成的段落"""
    project_dir = get_project_dir(project_id)
    writing_dir = project_dir / "writing"
    writing_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    version_id = timestamp.strftime("%Y%m%d_%H%M%S")

    version_data = {
        "version_id": version_id,
        "timestamp": timestamp.isoformat(),
        "section": section,
        "text": text,
        "citations": citations
    }

    filename = f"writing_{section}_{version_id}.json"
    with open(writing_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(version_data, f, ensure_ascii=False, indent=2)

    _update_project_time(project_id)
    return version_id


def list_writing_versions(project_id: str, section: str = None) -> List[Dict]:
    """列出所有写作版本"""
    writing_dir = get_project_dir(project_id) / "writing"
    if not writing_dir.exists():
        return []

    pattern = f"writing_{section}_*.json" if section else "writing_*.json"
    versions = []

    for f in sorted(writing_dir.glob(pattern), reverse=True):
        with open(f, 'r', encoding='utf-8') as file:
            data = json.load(file)
            versions.append({
                "version_id": data.get("version_id"),
                "timestamp": data.get("timestamp"),
                "section": data.get("section"),
                "text_preview": data.get("text", "")[:100] + "..." if len(data.get("text", "")) > 100 else data.get("text", ""),
                "citation_count": len(data.get("citations", []))
            })

    return versions


def get_writing(project_id: str, version_id: str) -> Optional[Dict]:
    """获取写作结果"""
    writing_dir = get_project_dir(project_id) / "writing"
    if not writing_dir.exists():
        return None

    for f in writing_dir.glob(f"writing_*_{version_id}.json"):
        with open(f, 'r', encoding='utf-8') as file:
            return json.load(file)

    return None


def load_all_writing(project_id: str) -> Dict[str, Dict]:
    """加载所有写作结果，按 section 分组，每个 section 返回最新版本"""
    writing_dir = get_project_dir(project_id) / "writing"
    if not writing_dir.exists():
        return {}

    # 按 section 分组，获取每个 section 的最新版本
    sections = {}
    for f in sorted(writing_dir.glob("writing_*.json"), reverse=True):
        with open(f, 'r', encoding='utf-8') as file:
            data = json.load(file)
            section = data.get("section")
            if section and section not in sections:
                # 只保留每个 section 的最新版本
                sections[section] = {
                    "version_id": data.get("version_id"),
                    "timestamp": data.get("timestamp"),
                    "text": data.get("text"),
                    "citations": data.get("citations", [])
                }

    return sections


def load_writing(project_id: str, section: str) -> Optional[Dict]:
    """加载指定 section 的最新写作结果"""
    all_writing = load_all_writing(project_id)
    return all_writing.get(section)


def get_document_path(project_id: str, document_id: str, file_name: str) -> Optional[str]:
    """获取文档文件路径

    Args:
        project_id: 项目ID
        document_id: 文档ID
        file_name: 原始文件名（用于获取扩展名）

    Returns:
        文件路径字符串，如果不存在返回 None
    """
    files_dir = get_files_dir(project_id)
    ext = Path(file_name).suffix.lower()
    file_path = files_dir / f"{document_id}{ext}"

    if file_path.exists():
        return str(file_path)

    # 尝试常见扩展名
    for ext in ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
        file_path = files_dir / f"{document_id}{ext}"
        if file_path.exists():
            return str(file_path)

    return None


# ==================== L-1 专项分析存储 ====================

def save_chunks(project_id: str, document_id: str, chunks: List[Dict]) -> str:
    """保存文档分块信息"""
    project_dir = get_project_dir(project_id)
    chunks_dir = project_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()

    chunk_data = {
        "document_id": document_id,
        "timestamp": timestamp.isoformat(),
        "chunk_count": len(chunks),
        "chunks": chunks
    }

    filename = f"chunks_{document_id}.json"
    with open(chunks_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(chunk_data, f, ensure_ascii=False, indent=2)

    _update_project_time(project_id)
    return document_id


def get_chunks(project_id: str, document_id: str) -> Optional[List[Dict]]:
    """获取文档分块信息"""
    chunks_dir = get_project_dir(project_id) / "chunks"
    filepath = chunks_dir / f"chunks_{document_id}.json"

    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get("chunks", [])


def save_l1_analysis(project_id: str, chunk_analyses: List[Dict]) -> str:
    """保存 L-1 专项分析结果"""
    project_dir = get_project_dir(project_id)
    l1_dir = project_dir / "l1_analysis"
    l1_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    version_id = timestamp.strftime("%Y%m%d_%H%M%S")

    analysis_data = {
        "version_id": version_id,
        "timestamp": timestamp.isoformat(),
        "total_chunks": len(chunk_analyses),
        "total_quotes": sum(len(c.get("quotes", [])) for c in chunk_analyses),
        "chunk_analyses": chunk_analyses
    }

    filename = f"l1_analysis_{version_id}.json"
    with open(l1_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(analysis_data, f, ensure_ascii=False, indent=2)

    _update_project_time(project_id)
    return version_id


def load_l1_analysis(project_id: str, version_id: str = None) -> Optional[List[Dict]]:
    """
    加载 L-1 分析结果

    新设计：自动合并所有分析文件（灵活整合能力）
    - 按 document_id 保留引用最多的版本
    - 不同文档的结果可以来自不同的分析文件
    - 解决批量分析产生多个文件导致数据分散的问题
    """
    from .quote_merger import hash_quote

    l1_dir = get_project_dir(project_id) / "l1_analysis"
    if not l1_dir.exists():
        return None

    if version_id:
        # 指定版本时，只返回该版本
        filepath = l1_dir / f"l1_analysis_{version_id}.json"
        if not filepath.exists():
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("chunk_analyses", [])

    # === 自动合并模式：读取所有文件，按文档保留最佳结果 ===
    files = sorted(l1_dir.glob("l1_analysis_*.json"), reverse=True)
    if not files:
        return None

    # 按 document_id 存储最佳结果
    # 格式: {document_id: {"quotes": [...], "metadata": {...}, "quote_count": int}}
    best_by_document: Dict[str, Dict] = {}

    for filepath in files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # 支持新格式 (material_analyses) 和旧格式 (chunk_analyses)
                analyses = data.get("material_analyses", []) or data.get("chunk_analyses", [])

                for chunk in analyses:
                    # 新格式用 exhibit_id 作为主键（材料级），旧格式用 document_id
                    # 为了兼容关系分析，统一按 exhibit_id 分组
                    exhibit_id = chunk.get("exhibit_id", "")
                    material_id = chunk.get("material_id", "")
                    doc_id = chunk.get("document_id", "")

                    # 使用 exhibit_id 作为分组键
                    group_key = exhibit_id or doc_id
                    if not group_key:
                        continue

                    quotes = chunk.get("quotes", [])

                    # 新格式：按 exhibit_id 聚合所有材料的引用
                    if group_key not in best_by_document:
                        best_by_document[group_key] = {
                            "chunk": {
                                "exhibit_id": exhibit_id,
                                "document_id": doc_id,
                                "file_name": chunk.get("file_name", f"Exhibit {exhibit_id}.pdf"),
                                "quotes": [],
                                "materials": []
                            },
                            "quote_count": 0
                        }

                    # 聚合引用（去重）
                    existing_quotes = {q.get("quote", "")[:100] for q in best_by_document[group_key]["chunk"]["quotes"]}
                    for q in quotes:
                        quote_text = q.get("quote", "")[:100]
                        if quote_text not in existing_quotes:
                            best_by_document[group_key]["chunk"]["quotes"].append(q)
                            existing_quotes.add(quote_text)

                    best_by_document[group_key]["quote_count"] = len(best_by_document[group_key]["chunk"]["quotes"])

                    # 记录材料来源
                    if material_id:
                        best_by_document[group_key]["chunk"]["materials"].append(material_id)

        except Exception as e:
            # 跳过无法读取的文件
            print(f"[Storage] Warning: Failed to read {filepath}: {e}")
            continue

    # 组装合并后的结果
    merged_analyses = [item["chunk"] for item in best_by_document.values()]

    # 按 exhibit_id 排序
    merged_analyses.sort(key=lambda x: x.get("exhibit_id", "Z-99"))

    return merged_analyses


def save_l1_summary(project_id: str, summary: Dict) -> str:
    """保存 L-1 汇总结果"""
    project_dir = get_project_dir(project_id)
    l1_dir = project_dir / "l1_analysis"
    l1_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    version_id = timestamp.strftime("%Y%m%d_%H%M%S")

    summary["version_id"] = version_id

    filename = f"l1_summary_{version_id}.json"
    with open(l1_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    _update_project_time(project_id)
    return version_id


def load_l1_summary(project_id: str, version_id: str = None) -> Optional[Dict]:
    """加载 L-1 汇总结果"""
    l1_dir = get_project_dir(project_id) / "l1_analysis"
    if not l1_dir.exists():
        return None

    if version_id:
        filepath = l1_dir / f"l1_summary_{version_id}.json"
    else:
        # 获取最新版本
        files = sorted(l1_dir.glob("l1_summary_*.json"), reverse=True)
        if not files:
            return None
        filepath = files[0]

    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def list_l1_versions(project_id: str) -> Dict[str, List[Dict]]:
    """列出所有 L-1 分析和汇总版本"""
    l1_dir = get_project_dir(project_id) / "l1_analysis"
    if not l1_dir.exists():
        return {"analyses": [], "summaries": []}

    analyses = []
    for f in sorted(l1_dir.glob("l1_analysis_*.json"), reverse=True):
        with open(f, 'r', encoding='utf-8') as file:
            data = json.load(file)
            analyses.append({
                "version_id": data.get("version_id"),
                "timestamp": data.get("timestamp"),
                "total_chunks": data.get("total_chunks"),
                "total_quotes": data.get("total_quotes")
            })

    summaries = []
    for f in sorted(l1_dir.glob("l1_summary_*.json"), reverse=True):
        with open(f, 'r', encoding='utf-8') as file:
            data = json.load(file)
            summaries.append({
                "version_id": data.get("version_id"),
                "timestamp": data.get("summary_timestamp"),
                "total_quotes": data.get("total_quotes"),
                "statistics": data.get("statistics")
            })

    return {"analyses": analyses, "summaries": summaries}


# ==================== 文件存储 ====================

def get_files_dir(project_id: str) -> Path:
    """获取项目文件存储目录"""
    files_dir = get_project_dir(project_id) / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    return files_dir


def save_uploaded_file(project_id: str, document_id: str, file_bytes: bytes, file_name: str) -> Path:
    """保存上传的原始文件

    Args:
        project_id: 项目ID
        document_id: 文档ID
        file_bytes: 文件内容
        file_name: 原始文件名

    Returns:
        保存的文件路径
    """
    files_dir = get_files_dir(project_id)

    # 使用 document_id 作为文件名前缀，保留原始扩展名
    ext = Path(file_name).suffix.lower()
    saved_path = files_dir / f"{document_id}{ext}"

    with open(saved_path, 'wb') as f:
        f.write(file_bytes)

    return saved_path


def get_uploaded_file(project_id: str, document_id: str, file_name: str) -> Optional[bytes]:
    """读取已上传的原始文件

    Args:
        project_id: 项目ID
        document_id: 文档ID
        file_name: 原始文件名（用于获取扩展名）

    Returns:
        文件内容，如果不存在返回 None
    """
    files_dir = get_files_dir(project_id)
    ext = Path(file_name).suffix.lower()
    file_path = files_dir / f"{document_id}{ext}"

    if not file_path.exists():
        return None

    with open(file_path, 'rb') as f:
        return f.read()


def delete_uploaded_file(project_id: str, document_id: str, file_name: str) -> bool:
    """删除已上传的原始文件"""
    files_dir = get_files_dir(project_id)
    ext = Path(file_name).suffix.lower()
    file_path = files_dir / f"{document_id}{ext}"

    if file_path.exists():
        file_path.unlink()
        return True
    return False


def load_uploaded_file(project_id: str, document_id: str) -> Optional[bytes]:
    """加载已上传的原始文件（通过document_id匹配，自动查找扩展名）

    Args:
        project_id: 项目ID
        document_id: 文档ID

    Returns:
        文件内容，如果不存在返回 None
    """
    files_dir = get_files_dir(project_id)

    # 尝试常见扩展名
    for ext in ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
        file_path = files_dir / f"{document_id}{ext}"
        if file_path.exists():
            with open(file_path, 'rb') as f:
                return f.read()

    # 尝试匹配以 document_id 开头的文件
    for file_path in files_dir.glob(f"{document_id}*"):
        if file_path.is_file():
            with open(file_path, 'rb') as f:
                return f.read()

    return None


def delete_document_file(project_id: str, document_id: str) -> bool:
    """删除文档相关的所有文件（通过document_id匹配）"""
    files_dir = get_files_dir(project_id)
    deleted = False

    if files_dir.exists():
        # 删除所有以 document_id 开头的文件
        for file_path in files_dir.glob(f"{document_id}*"):
            try:
                file_path.unlink()
                deleted = True
            except Exception:
                pass

    return deleted


# ==================== 辅助函数 ====================

def _update_project_time(project_id: str):
    """更新项目修改时间"""
    meta_file = get_project_file(project_id, "meta.json")
    if meta_file.exists():
        with open(meta_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)

        meta["updatedAt"] = datetime.now().isoformat()

        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)


def get_full_project_data(project_id: str) -> Optional[Dict]:
    """获取项目的完整数据（用于导出）"""
    project = get_project(project_id)
    if not project:
        return None

    return {
        "meta": project,
        "documents": get_documents(project_id),
        "analysis_versions": list_analysis_versions(project_id),
        "relationship_versions": list_relationship_versions(project_id),
        "writing_versions": list_writing_versions(project_id)
    }


# ==================== 样式模板存储 ====================

def get_style_templates_dir() -> Path:
    """获取样式模板存储目录（全局，不按项目分）"""
    templates_dir = DATA_DIR / "style_templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    return templates_dir


def save_style_template(section: str, name: str, original_text: str, parsed_structure: str) -> Dict:
    """保存样式模板

    Args:
        section: 段落类型 (qualifying_relationship, qualifying_employment, etc.)
        name: 模板名称
        original_text: 用户粘贴的原始例文
        parsed_structure: LLM 解析出的结构（带占位符）

    Returns:
        保存的模板数据
    """
    templates_dir = get_style_templates_dir()
    section_dir = templates_dir / section
    section_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    template_id = f"tpl_{int(timestamp.timestamp() * 1000)}"

    template_data = {
        "id": template_id,
        "section": section,
        "name": name,
        "original_text": original_text,
        "parsed_structure": parsed_structure,
        "created_at": timestamp.isoformat(),
        "updated_at": timestamp.isoformat()
    }

    filepath = section_dir / f"{template_id}.json"
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(template_data, f, ensure_ascii=False, indent=2)

    return template_data


def get_style_templates(section: str = None) -> List[Dict]:
    """获取样式模板列表

    Args:
        section: 可选，指定段落类型。不指定则返回所有模板

    Returns:
        模板列表
    """
    templates_dir = get_style_templates_dir()
    templates = []

    if section:
        # 获取指定 section 的模板
        section_dir = templates_dir / section
        if section_dir.exists():
            for f in sorted(section_dir.glob("tpl_*.json"), reverse=True):
                with open(f, 'r', encoding='utf-8') as file:
                    templates.append(json.load(file))
    else:
        # 获取所有 section 的模板
        for section_dir in templates_dir.iterdir():
            if section_dir.is_dir():
                for f in sorted(section_dir.glob("tpl_*.json"), reverse=True):
                    with open(f, 'r', encoding='utf-8') as file:
                        templates.append(json.load(file))

        # 按创建时间倒序
        templates.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    return templates


def get_style_template(template_id: str) -> Optional[Dict]:
    """获取单个样式模板"""
    templates_dir = get_style_templates_dir()

    # 遍历所有 section 目录查找
    for section_dir in templates_dir.iterdir():
        if section_dir.is_dir():
            filepath = section_dir / f"{template_id}.json"
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)

    return None


def delete_style_template(template_id: str) -> bool:
    """删除样式模板"""
    templates_dir = get_style_templates_dir()

    # 遍历所有 section 目录查找并删除
    for section_dir in templates_dir.iterdir():
        if section_dir.is_dir():
            filepath = section_dir / f"{template_id}.json"
            if filepath.exists():
                filepath.unlink()
                return True

    return False


# ==================== 高亮图片存储 ====================

def get_highlights_dir(project_id: str) -> Path:
    """获取项目高亮图片存储目录"""
    highlights_dir = get_project_dir(project_id) / "highlights"
    highlights_dir.mkdir(parents=True, exist_ok=True)
    return highlights_dir


def save_highlight_image(project_id: str, document_id: str, page_number: int, image_bytes: bytes) -> str:
    """保存高亮图片

    Args:
        project_id: 项目ID
        document_id: 文档ID
        page_number: 页码
        image_bytes: 图片内容 (PNG)

    Returns:
        保存的相对 URL 路径
    """
    highlights_dir = get_highlights_dir(project_id)
    filename = f"{document_id}_page_{page_number}.png"
    file_path = highlights_dir / filename

    with open(file_path, 'wb') as f:
        f.write(image_bytes)

    # 返回相对 URL
    return f"/api/highlight/saved/{project_id}/{document_id}/{page_number}"


# ==================== OCR 页级别存储 ====================

def get_ocr_pages_dir(project_id: str, document_id: str) -> Path:
    """获取文档 OCR 页结果目录"""
    ocr_dir = get_project_dir(project_id) / "ocr_pages" / document_id
    ocr_dir.mkdir(parents=True, exist_ok=True)
    return ocr_dir


def save_ocr_page(project_id: str, document_id: str, page_number: int, page_result: Dict):
    """保存单页 OCR 结果

    Args:
        project_id: 项目ID
        document_id: 文档ID
        page_number: 页码 (从1开始)
        page_result: 页面OCR结果 {"page_number": 1, "markdown_text": "...", "text_blocks": [...]}
    """
    ocr_dir = get_ocr_pages_dir(project_id, document_id)
    filepath = ocr_dir / f"page_{page_number}.json"
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(page_result, f, ensure_ascii=False, indent=2)


def get_completed_pages(project_id: str, document_id: str) -> List[int]:
    """获取已完成的页码列表

    Returns:
        已完成页码的有序列表，如 [1, 2, 3, 5] (第4页未完成)
    """
    project_dir = get_project_dir(project_id)
    ocr_dir = project_dir / "ocr_pages" / document_id
    if not ocr_dir.exists():
        return []

    completed = []
    for f in ocr_dir.glob("page_*.json"):
        try:
            page_num = int(f.stem.split("_")[1])
            completed.append(page_num)
        except (ValueError, IndexError):
            pass
    return sorted(completed)


def load_all_ocr_pages(project_id: str, document_id: str) -> List[Dict]:
    """加载所有已完成的页结果

    Returns:
        按页码排序的页面结果列表
    """
    project_dir = get_project_dir(project_id)
    ocr_dir = project_dir / "ocr_pages" / document_id
    if not ocr_dir.exists():
        return []

    pages = []
    for f in sorted(ocr_dir.glob("page_*.json"), key=lambda x: int(x.stem.split("_")[1])):
        with open(f, 'r', encoding='utf-8') as file:
            pages.append(json.load(file))
    return pages


def clear_ocr_pages(project_id: str, document_id: str):
    """清除文档的所有页 OCR 结果（用于完全重新处理）"""
    import shutil
    project_dir = get_project_dir(project_id)
    ocr_dir = project_dir / "ocr_pages" / document_id
    if ocr_dir.exists():
        shutil.rmtree(ocr_dir)


def get_highlight_image(project_id: str, document_id: str, page_number: int) -> Optional[bytes]:
    """获取已保存的高亮图片

    Args:
        project_id: 项目ID
        document_id: 文档ID
        page_number: 页码

    Returns:
        图片内容，如果不存在返回 None
    """
    highlights_dir = get_highlights_dir(project_id)
    filename = f"{document_id}_page_{page_number}.png"
    file_path = highlights_dir / filename

    if not file_path.exists():
        return None

    with open(file_path, 'rb') as f:
        return f.read()


def update_style_template(template_id: str, updates: Dict) -> Optional[Dict]:
    """更新样式模板"""
    templates_dir = get_style_templates_dir()

    # 遍历所有 section 目录查找
    for section_dir in templates_dir.iterdir():
        if section_dir.is_dir():
            filepath = section_dir / f"{template_id}.json"
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    template = json.load(f)

                # 更新字段
                for key, value in updates.items():
                    if key in ['name', 'original_text', 'parsed_structure'] and value is not None:
                        template[key] = value

                template['updated_at'] = datetime.now().isoformat()

                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(template, f, ensure_ascii=False, indent=2)

                return template

    return None
