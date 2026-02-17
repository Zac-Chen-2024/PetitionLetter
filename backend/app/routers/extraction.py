"""
Extraction Router - 统一提取 API

提供新的统一提取流程：
1. 一次性提取 snippets + entities + relations
2. 生成实体合并建议
3. 确认/拒绝合并
4. 应用合并

这将替代旧的 analysis router 的提取功能。
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from ..services.unified_extractor import (
    extract_exhibit_unified,
    extract_all_unified,
    load_combined_extraction,
    load_exhibit_extraction,
    get_extraction_status
)
from ..services.entity_merger import (
    suggest_entity_merges,
    load_merge_suggestions,
    update_merge_suggestion_status,
    apply_entity_merges,
    add_manual_merge,
    get_all_entities,
    get_merge_status
)

router = APIRouter(prefix="/api/extraction", tags=["extraction"])


# ==================== Request/Response Models ====================

class ExtractionRequest(BaseModel):
    applicant_name: str


class MergeConfirmation(BaseModel):
    suggestion_id: str
    status: str  # "accepted" or "rejected"


class ManualMergeRequest(BaseModel):
    primary_name: str
    merge_names: List[str]
    entity_type: str = "person"


# ==================== Extraction Endpoints ====================

@router.post("/{project_id}/extract")
async def extract_project(
    project_id: str,
    request: ExtractionRequest
):
    """
    统一提取整个项目

    一次性提取所有 exhibits 的 snippets + entities + relations
    """
    applicant_name = request.applicant_name

    if not applicant_name:
        raise HTTPException(status_code=400, detail="applicant_name is required")

    try:
        result = await extract_all_unified(
            project_id=project_id,
            applicant_name=applicant_name
        )

        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Extraction failed"))

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_id}/extract/{exhibit_id}")
async def extract_exhibit(
    project_id: str,
    exhibit_id: str,
    request: ExtractionRequest
):
    """
    提取单个 exhibit
    """
    applicant_name = request.applicant_name

    if not applicant_name:
        raise HTTPException(status_code=400, detail="applicant_name is required")

    try:
        result = await extract_exhibit_unified(
            project_id=project_id,
            exhibit_id=exhibit_id,
            applicant_name=applicant_name
        )

        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Extraction failed"))

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}/status")
async def get_project_extraction_status(project_id: str):
    """
    获取提取状态
    """
    return get_extraction_status(project_id)


@router.get("/{project_id}/combined")
async def get_combined_extraction(project_id: str):
    """
    获取合并后的提取结果
    """
    result = load_combined_extraction(project_id)
    if not result:
        raise HTTPException(status_code=404, detail="No extraction found")
    return result


@router.get("/{project_id}/exhibit/{exhibit_id}")
async def get_exhibit_extraction(project_id: str, exhibit_id: str):
    """
    获取单个 exhibit 的提取结果
    """
    result = load_exhibit_extraction(project_id, exhibit_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Extraction not found for exhibit {exhibit_id}")
    return result


# ==================== Snippet Query Endpoints ====================

@router.get("/{project_id}/snippets")
async def get_snippets(
    project_id: str,
    subject: Optional[str] = None,
    is_applicant: Optional[bool] = None,
    evidence_type: Optional[str] = None,
    limit: int = 500,
    offset: int = 0
):
    """
    查询 snippets

    支持过滤：
    - subject: 按主体过滤
    - is_applicant: 只看申请人/非申请人的成就
    - evidence_type: 按证据类型过滤
    """
    combined = load_combined_extraction(project_id)
    if not combined:
        return {
            "project_id": project_id,
            "total": 0,
            "snippets": []
        }

    snippets = combined.get("snippets", [])

    # 过滤
    if subject:
        snippets = [s for s in snippets if s.get("subject", "").lower() == subject.lower()]

    if is_applicant is not None:
        snippets = [s for s in snippets if s.get("is_applicant_achievement") == is_applicant]

    if evidence_type:
        snippets = [s for s in snippets if s.get("evidence_type") == evidence_type]

    total = len(snippets)
    paginated = snippets[offset:offset + limit]

    return {
        "project_id": project_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "filters": {
            "subject": subject,
            "is_applicant": is_applicant,
            "evidence_type": evidence_type
        },
        "snippets": paginated
    }


# ==================== Entity Endpoints ====================

@router.get("/{project_id}/entities")
async def get_entities(project_id: str):
    """
    获取所有实体
    """
    entities = get_all_entities(project_id)
    return {
        "project_id": project_id,
        "entity_count": len(entities),
        "entities": entities
    }


# ==================== Merge Suggestion Endpoints ====================

@router.post("/{project_id}/merge-suggestions/generate")
async def generate_merge_suggestions(
    project_id: str,
    request: ExtractionRequest
):
    """
    生成实体合并建议
    """
    applicant_name = request.applicant_name

    if not applicant_name:
        raise HTTPException(status_code=400, detail="applicant_name is required")

    try:
        suggestions = await suggest_entity_merges(
            project_id=project_id,
            applicant_name=applicant_name
        )

        return {
            "success": True,
            "suggestion_count": len(suggestions),
            "suggestions": suggestions
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}/merge-suggestions")
async def get_merge_suggestions(project_id: str):
    """
    获取合并建议
    """
    suggestions = load_merge_suggestions(project_id)
    status = get_merge_status(project_id)

    return {
        "project_id": project_id,
        "suggestions": suggestions,
        "status": status
    }


@router.post("/{project_id}/merges/confirm")
async def confirm_merges(
    project_id: str,
    confirmations: List[MergeConfirmation]
):
    """
    确认/拒绝合并建议
    """
    updated = 0
    for conf in confirmations:
        if conf.status not in ["accepted", "rejected"]:
            raise HTTPException(status_code=400, detail=f"Invalid status: {conf.status}")

        if update_merge_suggestion_status(project_id, conf.suggestion_id, conf.status):
            updated += 1

    return {
        "success": True,
        "updated": updated
    }


@router.post("/{project_id}/merges/confirm-all")
async def confirm_all_merges(project_id: str):
    """
    接受所有待处理的合并建议
    """
    suggestions = load_merge_suggestions(project_id)
    updated = 0

    for s in suggestions:
        if s.get("status") == "pending":
            if update_merge_suggestion_status(project_id, s["id"], "accepted"):
                updated += 1

    return {
        "success": True,
        "updated": updated
    }


@router.post("/{project_id}/merges/apply")
async def apply_merges(project_id: str):
    """
    应用已确认的合并
    """
    result = apply_entity_merges(project_id)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Apply failed"))

    return result


@router.post("/{project_id}/merges/manual")
async def manual_merge(
    project_id: str,
    request: ManualMergeRequest
):
    """
    手动添加合并
    """
    suggestion = add_manual_merge(
        project_id=project_id,
        primary_name=request.primary_name,
        merge_names=request.merge_names,
        entity_type=request.entity_type
    )

    return {
        "success": True,
        "suggestion": suggestion
    }


@router.get("/{project_id}/merges/status")
async def get_merges_status(project_id: str):
    """
    获取合并状态
    """
    return get_merge_status(project_id)


# ==================== Relationship Endpoints ====================

@router.get("/{project_id}/relationships")
async def get_relationships(project_id: str):
    """
    获取关系图
    """
    combined = load_combined_extraction(project_id)
    if not combined:
        return {
            "project_id": project_id,
            "entities": [],
            "relations": []
        }

    return {
        "project_id": project_id,
        "entities": combined.get("entities", []),
        "relations": combined.get("relations", []),
        "stats": combined.get("stats", {})
    }
