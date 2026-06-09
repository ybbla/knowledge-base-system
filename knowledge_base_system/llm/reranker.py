import json
import logging
from typing import Any

from app.core.errors import LLMError
from app.core.models import KnowledgeChunk
from llm.prompts import build_rerank_messages
from llm.volcengine_client import llm_client

logger = logging.getLogger(__name__)


class Reranker:
    """LLM-based reranker for candidate chunks."""

    def rerank(
        self, query: str, candidates: list[KnowledgeChunk]
    ) -> list[dict[str, Any]]:
        """Rerank candidate chunks by relevance to the query.

        Returns list of {chunk_id, relevance_score, reason} sorted by score descending.
        """
        if not candidates:
            return []

        # Build candidate JSON
        items = []
        for i, chunk in enumerate(candidates):
            items.append(
                {
                    "index": i,
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content[:500],  # truncate for LLM context
                }
            )

        try:
            messages = build_rerank_messages(query, json.dumps(items, ensure_ascii=False))
            result = llm_client.chat_json(messages)
            ranked = result.get("ranked_results", [])

            # Sort by relevance_score descending
            ranked.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
            return ranked

        except LLMError:
            logger.exception("Rerank failed, returning original candidates")
            return [
                {"chunk_id": c.chunk_id, "relevance_score": 0.5, "reason": "fallback"}
                for c in candidates
            ]
