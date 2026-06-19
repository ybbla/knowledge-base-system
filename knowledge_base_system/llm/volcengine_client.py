import base64
import json
import logging
import re
from typing import Any

from volcenginesdkarkruntime import Ark

from app.core.config import get_settings
from app.core.errors import LLMError
from llm.prompts import IMAGE_DESCRIPTION_SYSTEM, VIDEO_DESCRIPTION_SYSTEM

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


def _create_ark_client(settings) -> Ark:
    """创建带统一超时的火山方舟客户端。"""
    return Ark(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
        max_retries=0,
    )


class LLMClient:
    """火山引擎方舟 LLM 客户端 — 基于 Ark SDK。"""

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

        client = _create_ark_client(settings)
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
            except Exception as exc:
                logger.exception("LLM 调用失败")
                raise LLMError(f"LLM 调用失败: {exc}") from exc

        raise LLMError(f"LLM 调用失败: {last_error}")

    @staticmethod
    def _validate(data: dict[str, Any], schema: dict[str, Any]) -> None:
        """基础 JSON Schema 校验（必填字段检查）。"""
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                raise ValueError(f"缺少必填字段: {field}")

    # ── vision methods ────────────────────────────────────────────

    def describe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        image_url: str | None = None,
    ) -> str | None:
        """调用多模态模型对图片内容进行中文描述。

        参数:
            image_bytes: 图片原始字节。
            mime_type: 图片 MIME 类型（如 image/png）。
            image_url: 可选，图片的公网 URL。传入时跳过 base64 编码，
                       直接通过 URL 传递。当前默认 None，使用 base64 方式。

        返回:
            模型生成的图片描述文本；失败时返回 None。
        """
        settings = get_settings(reload_env=True)

        if not settings.api_key:
            logger.warning("VOLCENGINE_API_KEY 未配置，跳过图片视觉提取")
            return None

        # 构造图片内容：优先使用传入的 URL，否则 base64 编码
        if image_url:
            image_content = {"type": "image_url", "image_url": {"url": image_url}}
        else:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            data_uri = f"data:{mime_type};base64,{b64}"
            image_content = {"type": "image_url", "image_url": {"url": data_uri}}

        messages = [
            {"role": "system", "content": IMAGE_DESCRIPTION_SYSTEM},
            {"role": "user", "content": [image_content]},
        ]

        try:
            client = _create_ark_client(settings)
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.3,
            )
            text = response.choices[0].message.content
            return text.strip() if text else None
        except Exception:
            logger.exception("图片视觉理解失败")
            return None

    def describe_video(
        self,
        video_bytes: bytes,
        mime_type: str,
        fps: float = 0.5,
        video_url: str | None = None,
    ) -> str | None:
        """调用多模态模型对视频内容进行中文总结。

        参数:
            video_bytes: 视频原始字节。
            mime_type: 视频 MIME 类型（如 video/mp4）。
            fps: 采样帧率，默认 0.5（每秒取 0.5 帧）。
            video_url: 可选，视频的公网 URL。传入时跳过 base64 编码。

        返回:
            模型生成的视频总结文本；失败时返回 None。
        """
        settings = get_settings(reload_env=True)

        if not settings.api_key:
            logger.warning("VOLCENGINE_API_KEY 未配置，跳过视频视觉提取")
            return None

        if video_url:
            video_content = {
                "type": "video_url",
                "video_url": {"url": video_url, "fps": fps},
            }
        else:
            b64 = base64.b64encode(video_bytes).decode("ascii")
            data_uri = f"data:{mime_type};base64,{b64}"
            video_content = {
                "type": "video_url",
                "video_url": {"url": data_uri, "fps": fps},
            }

        messages = [
            {"role": "system", "content": VIDEO_DESCRIPTION_SYSTEM},
            {"role": "user", "content": [video_content]},
        ]

        try:
            client = _create_ark_client(settings)
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.3,
            )
            text = response.choices[0].message.content
            return text.strip() if text else None
        except Exception:
            logger.exception("视频视觉理解失败")
            return None


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

        client = _create_ark_client(settings)
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
