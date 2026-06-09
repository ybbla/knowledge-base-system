from app.core.config import settings


def rrf_fusion(
    vector_results: list[tuple[str, float]],
    bm25_results: list[tuple[str, float]],
    k: int | None = None,
) -> dict[str, float]:
    """Reciprocal Rank Fusion of two ranked lists.

    Returns {chunk_id: fused_score}, higher is better.
    """
    k = k or settings.rrf_k
    scores: dict[str, float] = {}

    for rank, (chunk_id, _) in enumerate(vector_results, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    for rank, (chunk_id, _) in enumerate(bm25_results, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    return scores
