import json
import logging
import re
from typing import Any

from openai import OpenAI
from volcenginesdkarkruntime import Ark

from app.core.config import get_settings
from app.core.errors import LLMError

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    """从 LLM 响应中提取 JSON，处理 markdown 代码块。"""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return m.group(0).strip()
    return text.strip()


def _build_openai_client() -> OpenAI:
    """创建 OpenAI 客户端。"""
    settings = get_settings(reload_env=True)
    return OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
    )


class LLMClient:
    """火山引擎方舟 LLM 客户端 — 基于 OpenAI SDK 直连。"""

    def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """发送聊天请求，返回解析后的 JSON。失败自动重试。"""
        settings = get_settings(reload_env=True)
        model = settings.llm_model
        max_retries = settings.max_json_retries

        if not settings.api_key:
            raise LLMError("VOLCENGINE_API_KEY 未配置")

        client = _build_openai_client()
        last_error: str = ""

        for attempt in range(max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                )
                text = response.choices[0].message.content or ""

                json_text = _extract_json(text)
                result = json.loads(json_text)

                if schema is not None:
                    self._validate(result, schema)

                return result

            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                last_error = str(exc)
                logger.warning(
                    "LLM 调用第 %d/%d 次失败: %s",
                    attempt + 1,
                    max_retries + 1,
                    last_error,
                )
                if attempt == max_retries:
                    raise LLMError(
                        f"LLM 调用在 {max_retries + 1} 次尝试后失败: {last_error}"
                    ) from exc

        raise LLMError(f"LLM 调用失败: {last_error}")

    @staticmethod
    def _validate(data: dict[str, Any], schema: dict[str, Any]) -> None:
        """基础 JSON Schema 校验（必填字段检查）。"""
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                raise ValueError(f"缺少必填字段: {field}")


class EmbeddingClient:
    """火山引擎方舟 Embedding 客户端 — 基于 Ark SDK，调用 multimodal_embeddings。"""

    def embed_text(self, texts: list[str]) -> list[list[float]]:
        """生成文本嵌入向量，逐条调用 multimodal_embeddings API。

        参数:
            texts: 待嵌入的文本列表

        返回:
            嵌入向量列表，与输入顺序一一对应
        """
        if not texts:
            return []

        settings = get_settings(reload_env=True)

        if not settings.api_key:
            raise LLMError("VOLCENGINE_API_KEY 未配置")

        client = Ark(api_key=settings.api_key)
        model = settings.embedding_model
        embeddings: list[list[float]] = []

        try:
            for text in texts:
                resp = client.multimodal_embeddings.create(
                    model=model,
                    input=[{"type": "text", "text": text}],
                    dimensions=1024,
                )
                embeddings.append(list(resp.data.embedding))
            return embeddings

        except Exception as exc:
            raise LLMError(f"Embedding 调用失败: {exc}") from exc


# 模块级单例
llm_client = LLMClient()
embedding_client = EmbeddingClient()
