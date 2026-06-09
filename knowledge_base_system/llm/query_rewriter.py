import logging

from app.core.errors import LLMError
from llm.prompts import QUERY_REWRITE_SCHEMA, build_rewrite_messages
from llm.volcengine_client import llm_client

logger = logging.getLogger(__name__)


class QueryRewriter:
    """Rewrite user queries for improved retrieval."""

    def rewrite(self, query: str) -> dict:
        """Rewrite a user query. Returns dict with rewritten_query, keywords, intent."""
        try:
            messages = build_rewrite_messages(query)
            result = llm_client.chat_json(messages, schema=QUERY_REWRITE_SCHEMA)
            return {
                "rewritten_query": result.get("rewritten_query", query),
                "keywords": result.get("keywords", []),
                "intent": result.get("intent", ""),
            }
        except LLMError:
            logger.exception("Query rewrite failed, falling back to original")
            return {
                "rewritten_query": query,
                "keywords": [query],
                "intent": "",
            }
