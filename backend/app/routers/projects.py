"""
项目管理 API
所有数据保存到本地文件系统
支持受益人姓名等元数据更新 + 项目类型（EB-1A / NIW）
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.services import storage
from app.services.standards_registry import (
    get_standards_for_type,
    get_all_types_with_standards,
    PROJECT_TYPES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str
    projectType: str = "EB-1A"


class ProjectResponse(BaseModel):
    id: str
    name: str
    createdAt: str
    updatedAt: Optional[str] = None
    beneficiaryName: Optional[str] = None
    petitionerName: Optional[str] = None
    foreignEntityName: Optional[str] = None
    projectType: Optional[str] = "EB-1A"
    projectNumber: Optional[str] = None


class UpdateProjectRequest(BaseModel):
    beneficiaryName: Optional[str] = None
    petitionerName: Optional[str] = None
    foreignEntityName: Optional[str] = None
    projectType: Optional[str] = None


# ==================== 项目类型 & 标准 ====================
# IMPORTANT: These routes MUST be declared BEFORE /{project_id} to avoid
# FastAPI matching "types" as a project_id.

@router.get("/types")
def get_project_types():
    """获取所有可用的项目类型及其法律标准"""
    return {
        "success": True,
        "types": PROJECT_TYPES,
        "details": get_all_types_with_standards(),
    }


# ==================== 项目管理 ====================

@router.get("", response_model=List[ProjectResponse])
def list_projects():
    """获取所有项目列表"""
    return storage.list_projects()


@router.post("", response_model=ProjectResponse)
def create_project(req: CreateProjectRequest):
    """创建新项目"""
    if req.projectType not in PROJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid project type: {req.projectType}. Must be one of {PROJECT_TYPES}")
    return storage.create_project(req.name, req.projectType)


@router.get("/{project_id}")
def get_project(project_id: str):
    """获取项目详情"""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/standards")
def get_project_standards(project_id: str):
    """获取该项目对应的法律标准列表"""
    project_type = storage.get_project_type(project_id)
    standards = get_standards_for_type(project_type)
    return {
        "success": True,
        "projectType": project_type,
        "standards": [s.to_frontend_dict() for s in standards],
    }


@router.delete("/{project_id}")
def delete_project(project_id: str):
    """删除项目"""
    if storage.delete_project(project_id):
        return {"success": True, "message": "Project deleted"}
    raise HTTPException(status_code=404, detail="Project not found")


@router.patch("/{project_id}")
def update_project(project_id: str, req: UpdateProjectRequest):
    """更新项目信息（如受益人姓名、申请人公司、海外公司、项目类型）"""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    updates = {}
    if req.beneficiaryName is not None:
        updates["beneficiaryName"] = req.beneficiaryName
    if req.petitionerName is not None:
        updates["petitionerName"] = req.petitionerName
    if req.foreignEntityName is not None:
        updates["foreignEntityName"] = req.foreignEntityName
    if req.projectType is not None:
        if req.projectType not in PROJECT_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid project type: {req.projectType}")
        updates["projectType"] = req.projectType

    updated = storage.update_project_meta(project_id, updates)
    return updated
