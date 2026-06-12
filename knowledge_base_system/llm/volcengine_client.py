import json
import logging
import re
from typing import Any

import httpx

from app.core.config import get_settings
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

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Send a chat request and return parsed JSON. Retries on failure."""
        settings = get_settings(reload_env=True)
        base = settings.base_url.rstrip("/")
        model = settings.llm_model
        api_key = settings.api_key
        max_retries = settings.max_json_retries
        if not api_key:
            raise LLMError("VOLCENGINE_API_KEY is not configured")
        last_error: str = ""
        for attempt in range(max_retries + 1):
            try:
                body: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }

                resp = httpx.post(
                    f"{base}/chat/completions",
                    headers=self._headers(api_key),
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

            except (json.JSONDecodeError, KeyError, ValueError, httpx.HTTPError) as exc:
                last_error = str(exc)
                logger.warning(
                    "LLM call attempt %d/%d failed: %s",
                    attempt + 1,
                    max_retries + 1,
                    last_error,
                )
                if attempt == max_retries:
                    raise LLMError(
                        f"LLM call failed after {max_retries + 1} attempts: {last_error}"
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

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def embed_text(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts. Calls API once per text."""
        settings = get_settings(reload_env=True)
        base = settings.base_url.rstrip("/")
        model = settings.embedding_model
        api_key = settings.api_key
        if not api_key:
            raise LLMError("VOLCENGINE_API_KEY is not configured")
        embeddings: list[list[float]] = []
        for text in texts:
            try:
                resp = httpx.post(
                    f"{base}/embeddings/multimodal",
                    headers=self._headers(api_key),
                    json={
                        "model": model,
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
