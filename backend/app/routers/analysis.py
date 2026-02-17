"""
Analysis Router - 证据提取和分析 API

Endpoints:
- POST /api/analysis/extract/{project_id} - 提取项目所有证据 snippets
- POST /api/analysis/extract/{project_id}/{exhibit_id} - 提取单个 exhibit 的 snippets
- GET /api/analysis/{project_id}/snippets - 获取提取的 snippets
- GET /api/analysis/{project_id}/snippets/stats - 获取 snippets 统计
- GET /api/analysis/{project_id}/stage - 获取 pipeline 阶段

NOTE: standard_key 分类已移至 Argument 层，Snippet 不再具备 standard 分类
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Dict, Optional
from pydantic import BaseModel
from datetime import datetime

from ..services.snippet_extractor import (
    extract_all_snippets,
    extract_snippets_for_exhibit,
    load_extracted_snippets,
    save_extracted_snippets,
    get_project_pipeline_stage,
    update_project_pipeline_stage,
)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ============================================
# Request/Response Models
# ============================================

class ExtractionRequest(BaseModel):
    pass  # 现在默认使用 OpenAI LLM 提取


class ExtractionResult(BaseModel):
    success: bool
    project_id: str
    snippet_count: int
    skipped_count: int      # 跳过的已提取文档数
    extracted_count: int    # 新提取的文档数
    message: str


class SnippetConfirmUpdate(BaseModel):
    """Snippet 确认更新（不含 standard_key，分类在 Argument 层）"""
    is_confirmed: bool = True


class PipelineStage(BaseModel):
    stage: str
    can_extract: bool
    can_confirm: bool
    can_generate: bool


# ============================================
# Extraction Endpoints
# ============================================

@router.post("/extract/{project_id}", response_model=ExtractionResult)
async def extract_project_snippets(
    project_id: str,
    skip_existing: bool = True  # 是否跳过已提取的文档（节省 API credits）
):
    """
    提取项目所有 exhibit 的证据 snippets

    这是 Pipeline Step 2 的核心操作。
    从 OCR text_blocks 中提取有意义的证据片段，并分配 EB-1A 标准类别。

    Args:
        project_id: 项目 ID
        skip_existing: 是否跳过已提取的文档（默认 True，节省 API credits）
    """
    try:
        result = await extract_all_snippets(project_id, skip_existing=skip_existing)

        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Extraction failed"))

        skipped = result.get("skipped_count", 0)
        extracted = result.get("extracted_count", 0)

        return ExtractionResult(
            success=True,
            project_id=project_id,
            snippet_count=result["snippet_count"],
            skipped_count=skipped,
            extracted_count=extracted,
            message=f"Extracted {extracted} new documents, skipped {skipped} existing. Total: {result['snippet_count']} snippets"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract/{project_id}/{exhibit_id}")
async def extract_exhibit_snippets(project_id: str, exhibit_id: str):
    """
    提取单个 exhibit 的证据 snippets 并保存到 registry
    """
    try:
        snippets = await extract_snippets_for_exhibit(project_id, exhibit_id)

        # 加载现有 snippets 并合并
        existing = load_extracted_snippets(project_id)

        # 过滤掉同一 exhibit 的旧 snippets
        filtered = [s for s in existing if s.get("exhibit_id") != exhibit_id]

        # 添加新提取的 snippets
        all_snippets = filtered + snippets

        # 保存到 extracted_snippets.json
        save_extracted_snippets(project_id, all_snippets)

        return {
            "success": True,
            "project_id": project_id,
            "exhibit_id": exhibit_id,
            "snippet_count": len(snippets),
            "snippets": snippets
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Snippet Query Endpoints
# ============================================

@router.get("/{project_id}/snippets")
async def get_snippets(
    project_id: str,
    limit: int = 100,
    offset: int = 0
):
    """
    获取提取的 snippets

    Args:
        project_id: 项目 ID
        limit: 返回数量限制
        offset: 偏移量

    NOTE: standard_key 过滤已移除，分类在 Argument 层进行
    """
    snippets = load_extracted_snippets(project_id)

    total = len(snippets)
    paginated = snippets[offset:offset + limit]

    return {
        "project_id": project_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "snippets": paginated
    }


@router.get("/{project_id}/snippets/stats")
async def get_snippets_stats(project_id: str):
    """
    获取 snippets 统计信息

    NOTE: by_standard 已移除，分类在 Argument 层进行
    """
    snippets = load_extracted_snippets(project_id)

    if not snippets:
        return {
            "project_id": project_id,
            "total": 0,
            "confirmed": 0,
            "ai_suggested": 0
        }

    confirmed = 0
    ai_suggested = 0

    for s in snippets:
        if s.get("is_confirmed"):
            confirmed += 1
        if s.get("is_ai_suggested"):
            ai_suggested += 1

    return {
        "project_id": project_id,
        "total": len(snippets),
        "confirmed": confirmed,
        "ai_suggested": ai_suggested,
        "confirmation_rate": round(confirmed / len(snippets) * 100, 1) if snippets else 0
    }


# ============================================
# Snippet Update Endpoints
# ============================================

@router.put("/{project_id}/snippets/{snippet_id}/confirm")
async def confirm_snippet(
    project_id: str,
    snippet_id: str,
    update: SnippetConfirmUpdate
):
    """
    确认 snippet

    NOTE: standard_key 分类已移至 Argument 层，此端点仅用于确认 snippet
    """
    snippets = load_extracted_snippets(project_id)

    found = False
    for s in snippets:
        if s.get("snippet_id") == snippet_id:
            s["is_confirmed"] = update.is_confirmed
            s["confirmed_at"] = datetime.now().isoformat()
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"Snippet not found: {snippet_id}")

    # 保存更新
    save_extracted_snippets(project_id, snippets)

    return {
        "success": True,
        "snippet_id": snippet_id,
        "is_confirmed": update.is_confirmed
    }


@router.post("/{project_id}/snippets/confirm-all")
async def confirm_all_snippets(project_id: str):
    """确认所有 AI 提取的 snippets"""
    snippets = load_extracted_snippets(project_id)

    confirmed_count = 0
    for s in snippets:
        if not s.get("is_confirmed"):
            s["is_confirmed"] = True
            s["confirmed_at"] = datetime.now().isoformat()
            confirmed_count += 1

    save_extracted_snippets(project_id, snippets)

    # 更新 pipeline 阶段
    update_project_pipeline_stage(project_id, "snippets_confirmed")

    return {
        "success": True,
        "confirmed_count": confirmed_count,
        "message": f"Confirmed {confirmed_count} snippets"
    }


# ============================================
# Pipeline Stage Endpoints
# ============================================

@router.get("/{project_id}/stage", response_model=PipelineStage)
async def get_pipeline_stage(project_id: str):
    """获取项目当前 pipeline 阶段"""
    stage = get_project_pipeline_stage(project_id)

    return PipelineStage(
        stage=stage,
        can_extract=stage == "ocr_complete",
        can_confirm=stage == "snippets_ready",
        can_generate=stage == "mapping_confirmed"
    )


@router.put("/{project_id}/stage/{new_stage}")
async def set_pipeline_stage(project_id: str, new_stage: str):
    """手动设置 pipeline 阶段 (调试用)"""
    valid_stages = [
        "ocr_complete",
        "extracting",
        "snippets_ready",
        "confirming",
        "mapping_confirmed",
        "generating",
        "petition_ready"
    ]

    if new_stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage. Valid stages: {valid_stages}"
        )

    update_project_pipeline_stage(project_id, new_stage)

    return {
        "success": True,
        "project_id": project_id,
        "stage": new_stage
    }


# NOTE: /standards endpoint removed - EB-1A standards info is now handled by frontend
