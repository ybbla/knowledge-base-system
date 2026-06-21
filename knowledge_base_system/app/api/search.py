"""旧版搜索 API — 已废弃，保留仅为向后兼容。

请使用 v1 接口替代：
- 知识库搜索：POST /api/v1/search

旧版接口将在后续大版本中移除。
"""

import logging

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.core.deps import retrieval_pipeline

router = APIRouter(prefix="/search", tags=["search (deprecated)"])
logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    """旧版搜索请求模型。"""

    query: str
    top_k: int = 5
    filters: dict = Field(default_factory=dict)


@router.post("", deprecated=True)
async def search(request: SearchRequest, response: Response):
    """执行知识库搜索并返回排序结果。已废弃：请使用 POST /api/v1/search。"""
    response.headers["X-Deprecated"] = "Use POST /api/v1/search"
    logger.warning("已废弃接口 POST /search 被调用")
    result = retrieval_pipeline.search(
        request.query,
        top_k=request.top_k,
        category=request.filters.get("category"),
    )
    return result.model_dump(mode="json")
