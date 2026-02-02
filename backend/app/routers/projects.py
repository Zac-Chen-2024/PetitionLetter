"""
项目管理 API
所有数据保存到本地文件系统
支持受益人姓名等元数据更新
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.services import storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str


class ProjectResponse(BaseModel):
    id: str
    name: str
    createdAt: str
    updatedAt: Optional[str] = None
    beneficiaryName: Optional[str] = None
    petitionerName: Optional[str] = None
    foreignEntityName: Optional[str] = None


class UpdateProjectRequest(BaseModel):
    beneficiaryName: Optional[str] = None
    petitionerName: Optional[str] = None
    foreignEntityName: Optional[str] = None


# ==================== 项目管理 ====================

@router.get("", response_model=List[ProjectResponse])
def list_projects():
    """获取所有项目列表"""
    return storage.list_projects()


@router.post("", response_model=ProjectResponse)
def create_project(req: CreateProjectRequest):
    """创建新项目"""
    return storage.create_project(req.name)


@router.get("/{project_id}")
def get_project(project_id: str):
    """获取项目详情"""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}")
def delete_project(project_id: str):
    """删除项目"""
    if storage.delete_project(project_id):
        return {"success": True, "message": "Project deleted"}
    raise HTTPException(status_code=404, detail="Project not found")


@router.patch("/{project_id}")
def update_project(project_id: str, req: UpdateProjectRequest):
    """更新项目信息（如受益人姓名、申请人公司、海外公司）"""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Only include fields that are provided (not None)
    updates = {}
    if req.beneficiaryName is not None:
        updates["beneficiaryName"] = req.beneficiaryName
    if req.petitionerName is not None:
        updates["petitionerName"] = req.petitionerName
    if req.foreignEntityName is not None:
        updates["foreignEntityName"] = req.foreignEntityName

    updated = storage.update_project_meta(project_id, updates)
    return updated


@router.get("/{project_id}/full")
def get_full_project(project_id: str):
    """获取项目完整数据（导出用）"""
    data = storage.get_full_project_data(project_id)
    if not data:
        raise HTTPException(status_code=404, detail="Project not found")
    return data


# ==================== 分析历史 ====================

@router.get("/{project_id}/analysis/versions")
def list_analysis_versions(project_id: str):
    """获取分析版本列表"""
    return storage.list_analysis_versions(project_id)


@router.get("/{project_id}/analysis")
def get_latest_analysis(project_id: str):
    """获取最新分析结果"""
    result = storage.get_analysis(project_id)
    if not result:
        return {"version_id": None, "results": {}}
    return result


@router.get("/{project_id}/analysis/{version_id}")
def get_analysis_version(project_id: str, version_id: str):
    """获取指定版本的分析结果"""
    result = storage.get_analysis(project_id, version_id)
    if not result:
        raise HTTPException(status_code=404, detail="Analysis version not found")
    return result


# ==================== 关系分析历史 ====================

@router.get("/{project_id}/relationship/versions")
def list_relationship_versions(project_id: str):
    """获取关系分析版本列表"""
    return storage.list_relationship_versions(project_id)


@router.get("/{project_id}/relationship")
def get_latest_relationship(project_id: str, raw: bool = False):
    """获取最新关系分析结果

    Args:
        raw: 如果为 True，返回原始格式；否则返回前端期望的格式
    """
    result = storage.get_relationship(project_id)
    if not result:
        return {"version_id": None, "data": None}
    if raw:
        return result
    return storage.convert_relationship_to_frontend_format(result)


@router.get("/{project_id}/relationship/{version_id}")
def get_relationship_version(project_id: str, version_id: str, raw: bool = False):
    """获取指定版本的关系分析结果

    Args:
        raw: 如果为 True，返回原始格式；否则返回前端期望的格式
    """
    result = storage.get_relationship(project_id, version_id)
    if not result:
        raise HTTPException(status_code=404, detail="Relationship version not found")
    if raw:
        return result
    return storage.convert_relationship_to_frontend_format(result)


# ==================== 写作历史 ====================

@router.get("/{project_id}/writing/versions")
def list_writing_versions(project_id: str, section: Optional[str] = None):
    """获取写作版本列表"""
    return storage.list_writing_versions(project_id, section)


@router.get("/{project_id}/writing/{version_id}")
def get_writing_version(project_id: str, version_id: str):
    """获取指定版本的写作结果"""
    result = storage.get_writing(project_id, version_id)
    if not result:
        raise HTTPException(status_code=404, detail="Writing version not found")
    return result
