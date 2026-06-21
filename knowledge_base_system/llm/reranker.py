import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.core.errors import LLMError
from app.core.models import KnowledgeChunk
from llm.prompts import RERANK_SCHEMA, build_rerank_message
from llm.volcengine_client import llm_client

logger = logging.getLogger(__name__)

# 并发打分线程数
_MAX_WORKERS = 15


def _score_one(query: str, chunk: KnowledgeChunk) -> dict[str, Any]:
    """对单条知识块调用 LLM 打分。失败返回不含 relevance_score 的条目。"""
    try:
        messages = build_rerank_message(query, chunk.content)
        result = llm_client.chat_json(messages, schema=RERANK_SCHEMA)
        return {
            "chunk_id": chunk.chunk_id,
            "relevance_score": result.get("relevance_score", 0),
            "reason": result.get("reason", ""),
        }
    except LLMError:
        logger.warning("单条打分失败 chunk=%s", chunk.chunk_id)
        # 不设 relevance_score，pipeline 会从 score_map 取 RRF 分数
        return {
            "chunk_id": chunk.chunk_id,
            "reason": "LLM 调用失败，使用 RRF 融合分数",
        }


class Reranker:
    """LLM-based reranker — 单条并行打分，代码负责排序。"""

    def rerank(
        self, query: str, candidates: list[KnowledgeChunk]
    ) -> list[dict[str, Any]]:
        """对每条候选独立调用 LLM 打分，并发执行，降序排列。

        Returns list of {chunk_id, relevance_score, reason} sorted by score descending.
        """
        if not candidates:
            return []

        if len(candidates) == 1:
            ranked = [_score_one(query, candidates[0])]
        else:
            workers = min(_MAX_WORKERS, len(candidates))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_score_one, query, c): c for c in candidates
                }
                ranked = []
                for future in as_completed(futures):
                    ranked.append(future.result())

        # 代码负责排序 — LLM 只管打分
        ranked.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return ranked
