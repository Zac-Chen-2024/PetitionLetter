"""
Arguments Router - AI 论据组装 API

Endpoints:
- POST /api/arguments/{project_id}/generate - 一键生成论据
- GET /api/arguments/{project_id} - 获取生成的论据列表
- POST /api/arguments/{project_id}/recommend-snippets - 推荐 snippets
- POST /api/arguments/{project_id}/subarguments - 创建 SubArgument
- PUT /api/arguments/{project_id}/subarguments/{id} - 更新 SubArgument
- DELETE /api/arguments/{project_id}/subarguments/{id} - 删除 SubArgument
- POST /api/arguments/{project_id}/infer-relationship - 推断关系
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Optional
from pydantic import BaseModel

from ..services.argument_generator import (
    ArgumentGenerator,
)
from ..services.argument_qualifier import (
    qualify_all_arguments,
    get_qualification_summary
)
from ..services.legal_argument_organizer import (
    full_legal_pipeline,
    regenerate_standard_pipeline,
)
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/arguments", tags=["arguments"])


# ============================================
# Request/Response Models
# ============================================

class GenerateRequest(BaseModel):
    force_reanalyze: bool = False
    applicant_name: Optional[str] = None
    provider: str = "deepseek"  # LLM provider: "deepseek" or "openai"


class ArgumentResponse(BaseModel):
    id: str
    title: str
    subject: str
    snippet_ids: List[str]
    standard_key: str
    confidence: float
    created_at: str
    is_ai_generated: bool


class GenerateResponse(BaseModel):
    success: bool
    main_subject: Optional[str]
    argument_count: int
    arguments: List[ArgumentResponse]
    stats: Dict


# ============================================
# Generation Endpoints
# ============================================

@router.post("/{project_id}/generate", response_model=GenerateResponse)
async def generate_arguments(
    project_id: str,
    request: GenerateRequest = GenerateRequest()
):
    """
    一键生成论据 (LLM + 法律条例驱动)

    Pipeline:
    1. LLM + 法律条例 → 组织子论点 (~7-8个，符合律师论证风格)
    2. LLM → 划分次级子论点 (每个2-4个 SubArguments)
    3. 智能过滤弱证据（如普通认证）

    Args:
        project_id: 项目 ID
        force_reanalyze: 是否强制重新生成
        applicant_name: 申请人姓名
        provider: LLM provider (deepseek/openai)
    """
    try:
        # 使用新的 LLM + 法律条例驱动流程
        result = await full_legal_pipeline(
            project_id=project_id,
            applicant_name=request.applicant_name or "the applicant",
            provider=request.provider
        )

        return GenerateResponse(
            success=True,
            main_subject=request.applicant_name,
            argument_count=result.get("stats", {}).get("argument_count", 0),
            arguments=result.get("arguments", []),
            stats=result.get("stats", {})
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RegenerateStandardRequest(BaseModel):
    standard_key: str
    applicant_name: Optional[str] = None
    provider: str = "deepseek"


@router.post("/{project_id}/regenerate-standard")
async def regenerate_standard(project_id: str, request: RegenerateStandardRequest):
    """
    按单个 standard 重新生成 Arguments + SubArguments。

    只替换该 standard_key 下的 arguments 和 sub_arguments，
    其余标准的数据保持不动。省去重跑全部标准的时间和 API credits。
    """
    result = await regenerate_standard_pipeline(
        project_id=project_id,
        standard_key=request.standard_key,
        applicant_name=request.applicant_name or "the applicant",
        provider=request.provider
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


# ============================================
# Arguments CRUD
# ============================================

@router.get("/{project_id}")
async def get_arguments(project_id: str, include_qualification: bool = False):
    """
    获取生成的论据列表

    Args:
        project_id: 项目 ID
        include_qualification: 是否包含资格检查结果

    Returns:
        - arguments: 论据列表 (LLM + 法律条例生成的精华子论点)
        - sub_arguments: 次级子论点列表
        - main_subject: 识别的主体（申请人）
        - generated_at: 生成时间
        - stats: 统计信息
        - filtered: 过滤掉的弱证据
    """
    # 优先读取新的 legal_arguments.json (使用文件锁)
    from ..services.snippet_recommender import load_legal_arguments
    legal_data = load_legal_arguments(project_id)
    result = legal_data if legal_data.get("arguments") else None

    # Fallback: 读取旧格式
    if not result:
        generator = ArgumentGenerator(project_id)
        result = generator.load_generated_arguments()

    if not result:
        return {
            "project_id": project_id,
            "arguments": [],
            "sub_arguments": [],
            "main_subject": None,
            "generated_at": None
        }

    arguments = result.get("arguments", [])
    sub_arguments = result.get("sub_arguments", [])
    filtered = result.get("filtered", [])

    # 如果需要包含资格检查
    if include_qualification:
        generator = ArgumentGenerator(project_id)
        snippets = generator.load_snippets()
        arguments = qualify_all_arguments(arguments, snippets)
        qual_summary = get_qualification_summary(arguments)
    else:
        qual_summary = None

    return {
        "project_id": project_id,
        "arguments": arguments,
        "sub_arguments": sub_arguments,
        "main_subject": result.get("main_subject"),
        "generated_at": result.get("generated_at"),
        "stats": result.get("stats", {}),
        "filtered": filtered,
        "qualification_summary": qual_summary
    }


# ============================================
# SubArgument Management Endpoints
# ============================================

from ..services.snippet_recommender import (
    recommend_snippets_for_subargument,
    create_subargument,
    get_assigned_snippet_ids,
    infer_relationship,
    merge_subarguments,
)


class SnippetRecommendRequest(BaseModel):
    """Snippet 推荐请求"""
    argument_id: str
    title: str
    description: Optional[str] = None
    exclude_snippet_ids: List[str] = []
    provider: str = "deepseek"


class RecommendedSnippet(BaseModel):
    """推荐的 Snippet"""
    snippet_id: str
    text: str
    exhibit_id: str
    page: int
    relevance_score: float
    reason: str


class SnippetRecommendResponse(BaseModel):
    """Snippet 推荐响应"""
    success: bool
    recommended_snippets: List[RecommendedSnippet]
    total_available: int


class CreateSubArgumentRequest(BaseModel):
    """创建 SubArgument 请求"""
    argument_id: str
    title: str
    purpose: str = ""
    relationship: str = ""
    snippet_ids: List[str] = []


class SubArgumentResponse(BaseModel):
    """SubArgument 响应"""
    id: str
    argument_id: str
    title: str
    purpose: str
    relationship: str
    snippet_ids: List[str]
    is_ai_generated: bool
    status: str
    created_at: str


@router.post("/{project_id}/recommend-snippets", response_model=SnippetRecommendResponse)
async def recommend_snippets(
    project_id: str,
    request: SnippetRecommendRequest
):
    """
    为新 SubArgument 推荐相关 Snippets

    使用 LLM 进行语义相关性排序，推荐最相关的 snippets。

    Args:
        project_id: 项目 ID
        request: 包含 argument_id, title, description 等信息

    Returns:
        推荐的 snippets 列表，包含 relevance_score 和 reason
    """
    try:
        # 获取已分配的 snippet IDs
        assigned_ids = get_assigned_snippet_ids(project_id)

        # 合并排除列表
        exclude_ids = list(set(request.exclude_snippet_ids) | assigned_ids)

        # 调用推荐服务
        recommended = await recommend_snippets_for_subargument(
            project_id=project_id,
            argument_id=request.argument_id,
            title=request.title,
            description=request.description,
            exclude_snippet_ids=exclude_ids,
            provider=request.provider
        )

        return SnippetRecommendResponse(
            success=True,
            recommended_snippets=[
                RecommendedSnippet(
                    snippet_id=s.get("snippet_id", ""),
                    text=s.get("text", ""),
                    exhibit_id=s.get("exhibit_id", ""),
                    page=s.get("page", 0),
                    relevance_score=s.get("relevance_score", 0.5),
                    reason=s.get("reason", "")
                )
                for s in recommended
            ],
            total_available=len(recommended)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class MergeSubArgumentsRequest(BaseModel):
    """合并 SubArguments 请求"""
    subargument_ids: List[str]  # min 2
    merged_title: str
    merged_purpose: str = ""
    merged_relationship: str = ""


@router.post("/{project_id}/subarguments/merge")
async def merge_subarguments_endpoint(
    project_id: str,
    request: MergeSubArgumentsRequest
):
    """
    合并多个 SubArguments → 新建 Argument + SubArgument

    要求：
    - subargument_ids 至少 2 个
    - 所有 sub-args 必须属于同一个 standard（可跨 Argument）

    Returns:
        {success, new_argument, merged_subargument, deleted_subargument_ids, writing_changes}
    """
    try:
        result = merge_subarguments(
            project_id=project_id,
            subargument_ids=request.subargument_ids,
            merged_title=request.merged_title,
            merged_purpose=request.merged_purpose,
            merged_relationship=request.merged_relationship,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Merge sub-arguments failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_id}/subarguments")
async def create_new_subargument(
    project_id: str,
    request: CreateSubArgumentRequest
):
    """
    创建新的 SubArgument

    将新的 SubArgument 添加到 legal_arguments.json，
    并更新父 Argument 的 sub_argument_ids。

    Args:
        project_id: 项目 ID
        request: 包含 argument_id, title, purpose, relationship, snippet_ids

    Returns:
        新创建的 SubArgument 对象
    """
    try:
        new_subarg = create_subargument(
            project_id=project_id,
            argument_id=request.argument_id,
            title=request.title,
            purpose=request.purpose,
            relationship=request.relationship,
            snippet_ids=request.snippet_ids
        )

        return {
            "success": True,
            "subargument": new_subarg
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class InferRelationshipRequest(BaseModel):
    """推断 Relationship 请求"""
    argument_id: str
    subargument_title: str
    provider: str = "deepseek"


class UpdateSubArgumentRequest(BaseModel):
    """更新 SubArgument 请求"""
    title: Optional[str] = None
    purpose: Optional[str] = None
    relationship: Optional[str] = None
    snippet_ids: Optional[List[str]] = None
    pending_snippet_ids: Optional[List[str]] = None
    needs_snippet_confirmation: Optional[bool] = None
    status: Optional[str] = None


@router.put("/{project_id}/subarguments/{subargument_id}")
async def update_subargument(
    project_id: str,
    subargument_id: str,
    request: UpdateSubArgumentRequest
):
    """
    更新 SubArgument

    可更新字段:
    - title: 标题
    - purpose: 目的描述
    - relationship: 与父论点的关系
    - snippet_ids: 已确认的 snippet IDs
    - pending_snippet_ids: 待确认的 snippet IDs
    - needs_snippet_confirmation: 是否需要确认 snippets
    - status: 状态 (draft/verified)
    """
    from ..services.snippet_recommender import load_legal_arguments, save_legal_arguments

    legal_args = load_legal_arguments(project_id)
    sub_arguments = legal_args.get("sub_arguments", [])

    found = False
    for sub_arg in sub_arguments:
        if sub_arg.get("id") == subargument_id:
            if request.title is not None:
                sub_arg["title"] = request.title
            if request.purpose is not None:
                sub_arg["purpose"] = request.purpose
            if request.relationship is not None:
                sub_arg["relationship"] = request.relationship
            if request.snippet_ids is not None:
                sub_arg["snippet_ids"] = request.snippet_ids
            if request.pending_snippet_ids is not None:
                sub_arg["pending_snippet_ids"] = request.pending_snippet_ids
            if request.needs_snippet_confirmation is not None:
                sub_arg["needs_snippet_confirmation"] = request.needs_snippet_confirmation
            if request.status is not None:
                sub_arg["status"] = request.status
            sub_arg["updated_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"SubArgument not found: {subargument_id}")

    save_legal_arguments(project_id, legal_args)

    return {
        "success": True,
        "subargument_id": subargument_id,
        "message": "SubArgument updated"
    }


@router.delete("/{project_id}/subarguments/{subargument_id}")
async def delete_subargument(
    project_id: str,
    subargument_id: str
):
    """
    删除 SubArgument

    同时从父 Argument 的 sub_argument_ids 中移除引用，
    并级联清理 writing_v3 文件中对应的句子。
    """
    logger.debug(f"DELETE SubArgument: project_id={project_id}, subargument_id={subargument_id}")

    from ..services.snippet_recommender import load_legal_arguments, save_legal_arguments
    from ..services.petition_writer_v3 import remove_subargument_from_writing

    legal_args = load_legal_arguments(project_id)
    sub_arguments = legal_args.get("sub_arguments", [])
    arguments = legal_args.get("arguments", [])

    logger.debug(f"DELETE SubArgument: before={len(sub_arguments)}")

    # Find and remove the SubArgument
    original_count = len(sub_arguments)
    sub_arguments = [sa for sa in sub_arguments if sa.get("id") != subargument_id]

    if len(sub_arguments) == original_count:
        logger.warning(f"DELETE SubArgument: not found {subargument_id}")
        raise HTTPException(status_code=404, detail=f"SubArgument not found: {subargument_id}")

    legal_args["sub_arguments"] = sub_arguments

    # Find parent Argument's standard_key before removing reference
    parent_standard_key = None
    for arg in arguments:
        if "sub_argument_ids" in arg and subargument_id in arg["sub_argument_ids"]:
            parent_standard_key = arg.get("standard_key")
            arg["sub_argument_ids"].remove(subargument_id)

    save_legal_arguments(project_id, legal_args)
    logger.debug(f"DELETE SubArgument: after={len(sub_arguments)}, saved")

    # Layer 1: Cascade - clean up writing_v3 files
    writing_changes = None
    if parent_standard_key:
        try:
            result = remove_subargument_from_writing(project_id, subargument_id, parent_standard_key)
            if result.get("changed"):
                writing_changes = {
                    "section": parent_standard_key,
                    "removed_indices": result["removed_indices"],
                    "remaining_sentence_count": len(result["new_sentences"])
                }
                logger.debug(f"DELETE SubArgument: cleaned writing_v3 for {parent_standard_key}, removed {len(result['removed_indices'])} sentences")
        except Exception as e:
            logger.warning(f"DELETE SubArgument: writing cascade failed: {e}")

    return {
        "success": True,
        "subargument_id": subargument_id,
        "message": "SubArgument deleted",
        "writing_changes": writing_changes
    }


@router.delete("/{project_id}/standards/{standard_key}")
async def remove_standard_endpoint(
    project_id: str,
    standard_key: str
):
    """
    移除一个 Standard 下的所有 Arguments、SubArguments，
    同时清理对应的 writing_v3 文件。
    """
    logger.debug(f"DELETE Standard: project_id={project_id}, standard_key={standard_key}")

    from ..services.snippet_recommender import remove_standard

    result = remove_standard(project_id, standard_key)

    logger.debug(
        f"DELETE Standard: removed {len(result['deleted_argument_ids'])} arguments, "
        f"{len(result['deleted_subargument_ids'])} sub-arguments, "
        f"{len(result['deleted_writing_files'])} writing files"
    )

    return result


@router.post("/{project_id}/infer-relationship")
async def infer_subargument_relationship(
    project_id: str,
    request: InferRelationshipRequest
):
    """
    根据子论点标题推断与父论点的关系

    使用 LLM 分析子论点标题与父论点的语义关系，
    返回最合适的 relationship 标签。

    Args:
        project_id: 项目 ID
        request: 包含 argument_id 和 subargument_title

    Returns:
        推断出的 relationship 字符串
    """
    try:
        relationship = await infer_relationship(
            project_id=project_id,
            argument_id=request.argument_id,
            subargument_title=request.subargument_title,
            provider=request.provider
        )

        return {
            "success": True,
            "relationship": relationship
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
