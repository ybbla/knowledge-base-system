"""LLM 重排序模块 — 对候选知识块逐条独立打分后按相关性降序排列。

采用并发打分策略：每条 chunk 独立调用 LLM 获取 0~1 的相关性评分，
代码层负责按分数排序。单条 LLM 失败不影响其他候选，失败条目回退使用 RRF 融合分。
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.core.errors import LLMError
from app.core.models import KnowledgeChunk
from llm.prompts import RERANK_SCHEMA, build_rerank_message
from llm.volcengine_client import llm_client

logger = logging.getLogger(__name__)

# 并发打分最大线程数
_MAX_WORKERS = 15


def _score_one(query: str, chunk: KnowledgeChunk) -> dict[str, Any]:
    """对单条知识块调用 LLM 进行相关性打分（0~1）。

    LLM 调用失败时返回不含 relevance_score 的条目，
    由 pipeline 层从 RRF 融合分数中取回退值。
    """
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
    """LLM 重排序器 — 对候选知识块逐条并行打分，代码层负责降序排列。

    并发策略：
    - 候选数 = 1：串行打分
    - 候选数 > 1：ThreadPoolExecutor 并发，最大 _MAX_WORKERS 个线程
    """

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
