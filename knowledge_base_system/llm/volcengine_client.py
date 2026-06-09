import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import LLMError

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    """Extract JSON from LLM response, handling markdown code fences."""
    # Try to find JSON in ```json ... ``` block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    # Try to find a JSON object directly
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return m.group(0).strip()
    return text.strip()


class LLMClient:
    """Volcengine ARK LLM client."""

    def __init__(self) -> None:
        self._base = settings.base_url.rstrip("/")
        self._model = settings.llm_model
        self._api_key = settings.api_key
        self._max_retries = settings.max_json_retries

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Send a chat request and return parsed JSON. Retries on failure."""
        last_error: str = ""
        for attempt in range(self._max_retries + 1):
            try:
                body: dict[str, Any] = {
                    "model": self._model,
                    "messages": messages,
                    "temperature": temperature,
                }

                resp = httpx.post(
                    f"{self._base}/chat/completions",
                    headers=self._headers(),
                    json=body,
                    timeout=120.0,
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]

                # Extract and parse JSON from response
                json_text = _extract_json(text)
                result = json.loads(json_text)

                # Validate against schema if provided
                if schema is not None:
                    self._validate(result, schema)

                return result

            except (json.JSONDecodeError, KeyError, httpx.HTTPError) as exc:
                last_error = str(exc)
                logger.warning(
                    "LLM call attempt %d/%d failed: %s",
                    attempt + 1,
                    self._max_retries + 1,
                    last_error,
                )
                if attempt == self._max_retries:
                    raise LLMError(
                        f"LLM call failed after {self._max_retries + 1} attempts: {last_error}"
                    ) from exc

        raise LLMError(f"LLM call failed: {last_error}")

    @staticmethod
    def _validate(data: dict[str, Any], schema: dict[str, Any]) -> None:
        """Basic JSON schema validation (required fields check)."""
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")


class EmbeddingClient:
    """Volcengine ARK Embedding client (multimodal API)."""

    def __init__(self) -> None:
        self._base = settings.base_url.rstrip("/")
        self._model = settings.embedding_model
        self._api_key = settings.api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def embed_text(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts. Calls API once per text."""
        embeddings: list[list[float]] = []
        for text in texts:
            try:
                resp = httpx.post(
                    f"{self._base}/embeddings/multimodal",
                    headers=self._headers(),
                    json={
                        "model": self._model,
                        "input": [{"type": "text", "text": text}],
                        "dimensions": 1024,
                        "encoding_format": "float",
                    },
                    timeout=60.0,
                )
                resp.raise_for_status()
                data = resp.json()
                # Response: {"data": {"embedding": [...], "object": "embedding"}}
                emb = data["data"]["embedding"]
                embeddings.append(emb)
            except (KeyError, httpx.HTTPError) as exc:
                raise LLMError(f"Embedding call failed: {exc}") from exc

        return embeddings


# Singleton instances
llm_client = LLMClient()
embedding_client = EmbeddingClient()
