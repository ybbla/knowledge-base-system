"""Compute Recall@k and MRR metrics."""

import math


def recall_at_k(
    results: list[str],
    expected: list[str],
    k: int = 5,
) -> float | None:
    """Compute Recall@k.

    Returns:
        1.0 if any expected chunk_id appears in results[:k],
        0.0 if not found,
        None if expected list is empty (no annotation).
    """
    if not expected:
        return None
    top_k = set(results[:k])
    return 1.0 if top_k & set(expected) else 0.0


def mrr(
    results: list[str],
    expected: list[str],
) -> float | None:
    """Compute Mean Reciprocal Rank (single query).

    Returns:
        Reciprocal rank of first hit, 0.0 if not found,
        None if expected list is empty (no annotation).
    """
    if not expected:
        return None
    expected_set = set(expected)
    for rank, chunk_id in enumerate(results, 1):
        if chunk_id in expected_set:
            return 1.0 / rank
    return 0.0


def recall_by_keywords(
    results_content: list[str],
    expected_keywords: list[str],
    k: int = 5,
) -> float | None:
    """Compute keyword-based recall.

    Returns:
        1.0 if any result in top-k contains all expected keywords,
        0.0 if not found,
        None if expected_keywords is empty (no annotation).
    """
    if not expected_keywords:
        return None
    for content in results_content[:k]:
        if all(kw in content for kw in expected_keywords):
            return 1.0
    return 0.0


def safe_mean(values: list[float | None]) -> float | None:
    """Compute mean of non-None values. Returns None if all are None."""
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)
