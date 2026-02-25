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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone

from ..services.snippet_extractor import (
    extract_all_snippets,
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


@router.post("/{project_id}/snippets/confirm-all")
async def confirm_all_snippets(project_id: str):
    """确认所有 AI 提取的 snippets"""
    snippets = load_extracted_snippets(project_id)

    confirmed_count = 0
    for s in snippets:
        if not s.get("is_confirmed"):
            s["is_confirmed"] = True
            s["confirmed_at"] = datetime.now(timezone.utc).isoformat()
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


