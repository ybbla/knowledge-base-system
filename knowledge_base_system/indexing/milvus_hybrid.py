import logging
from typing import Any

from indexing.milvus_vector import MilvusCollectionManager, _escape_expr_value

logger = logging.getLogger(__name__)


def hybrid_search(
    manager: MilvusCollectionManager,
    dense_vector: list[float],
    sparse_vector: dict[int, float],
    top_k: int,
    category: str | None = None,
    rrf_k: int = 60,
) -> list[tuple[str, float]]:
    """调用 Milvus Hybrid Search，返回融合后的 chunk_id 与分数。"""
    manager.ensure_collection()
    collection = manager.collection
    if collection is None:
        raise RuntimeError("Milvus collection is not initialized")
    if not sparse_vector:
        return []

    from pymilvus import AnnSearchRequest, RRFRanker

    expr = 'status == "active"'
    if category is not None:
        expr = f'(category == "{_escape_expr_value(category)}") && (status == "active")'

    dense_req = AnnSearchRequest(
        data=[[float(v) for v in dense_vector]],
        anns_field="dense_vector",
        param={"metric_type": "COSINE", "params": {"nprobe": 16}},
        limit=top_k,
        expr=expr,
    )
    sparse_req = AnnSearchRequest(
        data=[sparse_vector],
        anns_field="sparse_vector",
        param={"metric_type": "IP", "params": {}},
        limit=top_k,
        expr=expr,
    )
    results: Any = collection.hybrid_search(
        [dense_req, sparse_req],
        RRFRanker(rrf_k),
        limit=top_k,
        output_fields=["chunk_id"],
    )
    if not results:
        return []
    return [(hit.entity.get("chunk_id"), float(hit.score)) for hit in results[0]]
