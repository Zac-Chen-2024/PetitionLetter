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
        files = sorted(rel_dir.glob("relationship_*.json"), reverse=True)
        if not files:
            return None
        filepath = files[0]

    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


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
    """加载 L-1 分析结果"""
    l1_dir = get_project_dir(project_id) / "l1_analysis"
    if not l1_dir.exists():
        return None

    if version_id:
        filepath = l1_dir / f"l1_analysis_{version_id}.json"
    else:
        # 获取最新版本
        files = sorted(l1_dir.glob("l1_analysis_*.json"), reverse=True)
        if not files:
            return None
        filepath = files[0]

    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get("chunk_analyses", [])


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
