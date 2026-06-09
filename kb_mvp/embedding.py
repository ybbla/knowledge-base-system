from __future__ import annotations

import hashlib
import math
from typing import Protocol

from .text import tokenize


class EmbeddingService(Protocol):
    """Embedding 服务抽象接口。

    业务流水线只依赖该协议。MVP 使用 hash embedding；正式版本可以实现
    Doubao-embedding-vision 客户端，并保持调用方不变。
    """

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本向量。

        参数:
            texts: 待向量化的文本列表。

        返回:
            与输入顺序一致的向量列表。
        """

        ...


class HashEmbeddingService:
    """用于本地端到端测试的确定性 hash embedding。

    该实现不具备真实语义理解能力，只是把 token hash 到固定维度向量，并做
    L2 归一化。它适合验证索引、召回、融合和重排流程，不适合评估真实效果。
    """

    def __init__(self, dimensions: int = 128) -> None:
        """初始化 hash embedding 服务。

        参数:
            dimensions: 输出向量维度。维度越高，hash 冲突越少，但 MVP 默认
                128 维已经足够演示。
        """

        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本 hash 向量。

        参数:
            texts: 待向量化文本列表。

        返回:
            每个文本对应一个固定维度、已归一化的浮点向量。
        """

        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        """生成单条文本的 hash 向量。

        参数:
            text: 待向量化文本。

        返回:
            固定维度、L2 归一化后的向量。
        """

        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算两个向量的余弦相似度。

    参数:
        left: 左侧向量。
        right: 右侧向量。

    返回:
        向量长度一致时返回点积相似度；向量为空或长度不一致时返回 0。
        因为 MVP embedding 已归一化，所以点积等价于余弦相似度。
    """

    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))
