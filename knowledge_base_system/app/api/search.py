from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.deps import retrieval_pipeline

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    filters: dict = Field(default_factory=dict)


@router.post("")
async def search(request: SearchRequest):
    """Search knowledge base and return ranked results."""
    result = retrieval_pipeline.search(
        request.query,
        top_k=request.top_k,
        category=request.filters.get("category"),
    )
    return result.model_dump(mode="json")
