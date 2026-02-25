"""
Data Router - 数据查询 API

Endpoints:
- GET /api/data/projects/{project_id}/snippets - 获取项目的 snippets (fallback)
"""

from fastapi import APIRouter, HTTPException

from ..services.snippet_registry import load_registry

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/projects/{project_id}/snippets")
async def get_project_snippets(project_id: str, limit: int = 100, offset: int = 0):
    """
    获取项目的 snippets

    Args:
        project_id: 项目 ID
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        snippets 列表
    """
    snippets = load_registry(project_id)

    if not snippets:
        raise HTTPException(status_code=404, detail=f"No snippets found for project: {project_id}")

    # 分页
    total = len(snippets)
    paginated = snippets[offset:offset + limit]

    return {
        "project_id": project_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "snippets": paginated
    }
