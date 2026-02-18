"""
Arguments Router - AI 论据组装 API

Endpoints:
- POST /api/arguments/{project_id}/generate - 一键生成论据
- GET /api/arguments/{project_id}/status - 获取生成状态
- GET /api/arguments/{project_id} - 获取生成的论据列表
- GET /api/arguments/{project_id}/relationship - 获取关系图数据
- PUT /api/arguments/{project_id}/{argument_id} - 更新论据
- DELETE /api/arguments/{project_id}/{argument_id} - 删除论据
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Optional
from pydantic import BaseModel

from ..services.argument_generator import (
    ArgumentGenerator,
    generate_arguments_for_project
)
from ..services.argument_qualifier import (
    qualify_all_arguments,
    get_qualification_summary
)
from ..services.argument_composer import (
    compose_project_arguments,
    ArgumentComposer
)
from dataclasses import asdict
import json
from datetime import datetime

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


class StatusResponse(BaseModel):
    has_relationship_analysis: bool
    has_generated_arguments: bool
    argument_count: int
    main_subject: Optional[str]
    generated_at: Optional[str]


class ArgumentUpdate(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    snippet_ids: Optional[List[str]] = None
    standard_key: Optional[str] = None


# ============================================
# Generation Endpoints
# ============================================

@router.post("/{project_id}/generate", response_model=GenerateResponse)
async def generate_arguments(
    project_id: str,
    request: GenerateRequest = GenerateRequest()
):
    """
    一键生成论据

    Pipeline:
    1. 加载 L1 Snippets (extracted_snippets.json)
    2. 运行关系分析（按 exhibit 分批）
    3. 识别主体（申请人）
    4. 按 standard_key 分组生成 Arguments
    5. 自动映射到 EB-1A Standards

    Args:
        project_id: 项目 ID
        force_reanalyze: 是否强制重新运行关系分析
        applicant_name: 申请人姓名（可选，用于精确识别主体）
    """
    try:
        result = await generate_arguments_for_project(
            project_id=project_id,
            force_reanalyze=request.force_reanalyze,
            applicant_name=request.applicant_name,
            provider=request.provider
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Generation failed")
            )

        return GenerateResponse(
            success=True,
            main_subject=result.get("main_subject"),
            argument_count=len(result.get("arguments", [])),
            arguments=result.get("arguments", []),
            stats=result.get("stats", {})
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}/status", response_model=StatusResponse)
async def get_generation_status(project_id: str):
    """
    获取论据生成状态

    返回:
    - has_relationship_analysis: 是否已完成关系分析
    - has_generated_arguments: 是否已生成论据
    - argument_count: 论据数量
    - main_subject: 识别的主体（申请人）
    - generated_at: 生成时间
    """
    generator = ArgumentGenerator(project_id)
    status = generator.get_generation_status()

    return StatusResponse(**status)


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
    """
    generator = ArgumentGenerator(project_id)
    result = generator.load_generated_arguments()

    if not result:
        return {
            "project_id": project_id,
            "arguments": [],
            "main_subject": None,
            "generated_at": None
        }

    arguments = result.get("arguments", [])

    # 如果需要包含资格检查
    if include_qualification:
        # 加载 snippets
        snippets = generator.load_snippets()
        arguments = qualify_all_arguments(arguments, snippets)
        qual_summary = get_qualification_summary(arguments)
    else:
        qual_summary = None

    return {
        "project_id": project_id,
        "arguments": arguments,
        "main_subject": result.get("main_subject"),
        "generated_at": result.get("generated_at"),
        "stats": result.get("stats", {}),
        "qualification_summary": qual_summary
    }


@router.put("/{project_id}/{argument_id}")
async def update_argument(
    project_id: str,
    argument_id: str,
    update: ArgumentUpdate
):
    """
    更新论据

    可更新字段:
    - title: 论据标题
    - subject: 主体
    - snippet_ids: 关联的 snippet IDs
    - standard_key: 映射的标准
    """
    generator = ArgumentGenerator(project_id)
    result = generator.load_generated_arguments()

    if not result:
        raise HTTPException(status_code=404, detail="No arguments found")

    arguments = result.get("arguments", [])
    found = False

    for arg in arguments:
        if arg.get("id") == argument_id:
            if update.title is not None:
                arg["title"] = update.title
            if update.subject is not None:
                arg["subject"] = update.subject
            if update.snippet_ids is not None:
                arg["snippet_ids"] = update.snippet_ids
            if update.standard_key is not None:
                arg["standard_key"] = update.standard_key
            arg["is_ai_generated"] = False  # Mark as manually edited
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"Argument not found: {argument_id}")

    # Save updated arguments
    import json
    args_file = generator.get_arguments_file()
    with open(args_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "argument_id": argument_id,
        "message": "Argument updated"
    }


@router.delete("/{project_id}/{argument_id}")
async def delete_argument(project_id: str, argument_id: str):
    """
    删除论据
    """
    generator = ArgumentGenerator(project_id)
    result = generator.load_generated_arguments()

    if not result:
        raise HTTPException(status_code=404, detail="No arguments found")

    arguments = result.get("arguments", [])
    original_count = len(arguments)

    # Filter out the argument to delete
    arguments = [arg for arg in arguments if arg.get("id") != argument_id]

    if len(arguments) == original_count:
        raise HTTPException(status_code=404, detail=f"Argument not found: {argument_id}")

    result["arguments"] = arguments

    # Save updated arguments
    import json
    args_file = generator.get_arguments_file()
    with open(args_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "argument_id": argument_id,
        "message": "Argument deleted"
    }


# ============================================
# Relationship Graph Endpoints
# ============================================

@router.get("/{project_id}/relationship")
async def get_relationship_graph(project_id: str):
    """
    获取关系图数据

    返回:
    - entities: 实体列表
    - relations: 关系列表
    - main_subject: 识别的主体（申请人）
    - attributions: snippet 归属列表
    - stats: 统计信息
    """
    generator = ArgumentGenerator(project_id)
    graph = generator.load_relationship_graph()

    if not graph:
        return {
            "project_id": project_id,
            "has_relationship_analysis": False,
            "entities": [],
            "relations": [],
            "main_subject": None,
            "attributions": [],
            "stats": {}
        }

    return {
        "project_id": project_id,
        "has_relationship_analysis": True,
        "entities": graph.get("entities", []),
        "relations": graph.get("relations", []),
        "main_subject": graph.get("main_subject"),
        "attributions": graph.get("attributions", []),
        "stats": graph.get("stats", {})
    }


@router.post("/{project_id}/relationship/analyze")
async def run_relationship_analysis(project_id: str, force: bool = False):
    """
    单独运行关系分析（不生成论据）

    用于测试或查看关系图
    """
    try:
        generator = ArgumentGenerator(project_id)
        result = await generator.run_relationship_analysis(force=force)

        return {
            "success": True,
            "entity_count": len(result.get("entities", [])),
            "relation_count": len(result.get("relations", [])),
            "stats": result.get("stats", {})
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Composed Arguments Endpoint (律师风格组合)
# ============================================

@router.get("/{project_id}/composed")
async def get_composed_arguments(project_id: str, applicant_name: str = "Ms. Qu"):
    """
    获取律师风格组合论点

    使用 argument_composer 将碎片化的 snippets 组合成结构化论点:
    - Membership: 按协会分组，过滤普通会员
    - Published Material: 按媒体分组
    - Original Contribution: 合并成整体
    - Leading Role: 按组织分组，合并变体
    - Awards: 合并成整体

    每个论点包含: Claim + Proof + Significance + Context + Conclusion
    """
    try:
        result = compose_project_arguments(project_id, applicant_name)

        # 转换成前端友好的格式 (flat list with standard_key)
        arguments = []
        for standard, args in result.get("composed", {}).items():
            for idx, arg in enumerate(args):
                # 生成唯一 ID
                arg_id = f"{standard}_{idx}"

                # 收集所有 snippet_ids
                snippet_ids = []
                for layer in ["claim", "proof", "significance", "context"]:
                    for item in arg.get(layer, []):
                        if item.get("snippet_id"):
                            snippet_ids.append(item["snippet_id"])

                arguments.append({
                    "id": arg_id,
                    "title": arg.get("title", ""),
                    "subject": arg.get("group_key", ""),
                    "standard_key": standard,
                    "snippet_ids": snippet_ids,
                    "exhibits": arg.get("exhibits", []),
                    "confidence": arg.get("completeness", {}).get("score", 0) / 100.0,
                    "is_ai_generated": True,
                    "created_at": datetime.now().isoformat(),
                    # 新增：律师风格结构
                    "layers": {
                        "claim": arg.get("claim", []),
                        "proof": arg.get("proof", []),
                        "significance": arg.get("significance", []),
                        "context": arg.get("context", [])
                    },
                    "conclusion": arg.get("conclusion", ""),
                    "completeness": arg.get("completeness", {})
                })

        return {
            "project_id": project_id,
            "arguments": arguments,
            "main_subject": applicant_name,
            "generated_at": datetime.now().isoformat(),
            "stats": result.get("statistics", {}),
            "lawyer_output": result.get("lawyer_output", "")
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
