"""检索参数网格搜索脚本。

运行方式：
    python knowledge_base_system/tests/evaluation/tune_params.py

脚本会复用当前仓库的评测数据集，遍历 VECTOR_TOP_K、BM25_TOP_K、
FUSION_TOP_K、RRF_K 参数组合，输出 Recall@5 和 MRR 最优组合。
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.config import settings
from app.core.deps import rebuild_retrieval_indexes_from_chunks, retrieval_pipeline
from tests.evaluation.dataset import load_dataset
from tests.evaluation.test_evaluation import run_evaluation


GRID = {
    "vector_top_k": [20, 50, 80],
    "bm25_top_k": [20, 50, 80],
    "fusion_top_k": [10, 20, 40],
    "rrf_k": [30, 60, 90],
}


class _IdentityRewriter:
    def rewrite(self, query: str) -> dict[str, Any]:
        return {"rewritten_query": query, "keywords": [query], "intent": ""}


class _PassthroughReranker:
    def rerank(self, query: str, candidates: list[Any]) -> list[dict[str, Any]]:
        return [
            {"chunk_id": chunk.chunk_id, "relevance_score": 1.0 - index * 0.01}
            for index, chunk in enumerate(candidates)
        ]


class _CachingEmbedder:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self._cache: dict[str, list[float]] = {}

    def embed_text(self, texts: list[str]) -> list[list[float]]:
        missing = [text for text in texts if text not in self._cache]
        if missing:
            vectors = self._delegate.embed_text(missing)
            for text, vector in zip(missing, vectors):
                self._cache[text] = vector
        return [self._cache[text] for text in texts]


def _enable_fast_retrieval_eval() -> None:
    """仅评测检索层，避免 query rewrite/rerank 的慢速 LLM 调用影响调参。"""
    from retrieval import pipeline as retrieval_module

    cached = _CachingEmbedder(retrieval_module.embedding_client)
    retrieval_module.embedding_client = cached
    retrieval_pipeline._rewriter = _IdentityRewriter()
    retrieval_pipeline._reranker = _PassthroughReranker()


def _search(query: str) -> list[dict[str, Any]]:
    result = retrieval_pipeline.search(query, top_k=5)
    return [
        {"chunk_id": item.chunk_id, "content": item.content}
        for item in result.results
    ]


def _score(result: dict[str, Any]) -> tuple[float, float]:
    recall = result.get("recall@5") or 0.0
    mrr = result.get("mrr") or 0.0
    return recall, mrr


def main() -> None:
    dataset = load_dataset()
    if os.getenv("EVAL_FAST_RETRIEVAL", "1") == "1":
        _enable_fast_retrieval_eval()

    rebuilt = rebuild_retrieval_indexes_from_chunks()
    if rebuilt == 0:
        print("没有可评测的持久化 chunk，请先完成入库。")
        return

    rows: list[dict[str, Any]] = []
    keys = list(GRID)
    original_mode = settings.milvus_enabled
    # 调参只覆盖外部服务检索路径，避免切换到非 Milvus 模式。
    os.environ.pop("MILVUS_ENABLED", None)
    modes = [("milvus_hybrid", True)]
    try:
        for mode_name, enabled in modes:
            settings.milvus_enabled = enabled
            for values in itertools.product(*(GRID[key] for key in keys)):
                params = dict(zip(keys, values))
                for key, value in params.items():
                    setattr(settings, key, value)

                result = run_evaluation(_search, dataset)
                row = {
                    **params,
                    "recall@5": result.get("recall@5"),
                    "mrr": result.get("mrr"),
                    "keyword_recall@5": result.get("keyword_recall@5"),
                    "mode": mode_name,
                }
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False))
    finally:
        settings.milvus_enabled = original_mode

    best = max(rows, key=lambda row: _score(row))
    print("\n最优参数：")
    print(json.dumps(best, ensure_ascii=False, indent=2))

    output = Path(__file__).parent.parent / "results" / "evaluation" / "tune_params.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"best": best, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入：{output}")


if __name__ == "__main__":
    main()
