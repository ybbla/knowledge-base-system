"""内存向量索引实现 — 基于 numpy 余弦相似度。

注意：MemoryVectorIndex 当前仅在测试中使用，生产环境统一使用 MilvusVectorIndex。
代码中没有任何生产路径引用此模块。保留此文件以供本地测试或无 Milvus 环境的快速验证。
"""

import numpy as np

from indexing.base import VectorIndex


class MemoryVectorIndex(VectorIndex):
    """基于 numpy 余弦相似度的内存向量索引实现（仅供测试使用）。"""

    def __init__(self) -> None:
        """初始化空的内存向量存储。"""
        self._chunk_ids: list[str] = []
        self._vectors: list[np.ndarray] = []
        self._metadata: dict[str, dict] = {}

    def add(
        self,
        chunk_id: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> None:
        """添加向量记录，若已存在则先删除再添加（幂等写入）。"""
        self.delete(chunk_id)
        self._chunk_ids.append(chunk_id)
        self._vectors.append(np.array(vector, dtype=np.float32))
        self._metadata[chunk_id] = metadata or {}

    def delete(self, chunk_id: str) -> None:
        """删除指定知识块的向量，不存在则静默跳过。"""
        try:
            idx = self._chunk_ids.index(chunk_id)
            self._chunk_ids.pop(idx)
            self._vectors.pop(idx)
            self._metadata.pop(chunk_id, None)
        except ValueError:
            pass

    def get_metadata(self, chunk_id: str) -> dict:
        """获取知识块的元数据字典。"""
        return self._metadata.get(chunk_id, {})

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        categories: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """余弦相似度检索，过滤 status=active 和 categories，返回 top_k 结果。"""
        if not self._vectors:
            return []

        q = np.array(query_vector, dtype=np.float32)
        matrix = np.stack(self._vectors)

        # Cosine similarity
        norms = np.linalg.norm(matrix, axis=1)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []

        # Avoid division by zero for zero-norm vectors
        safe_norms = np.where(norms == 0, 1.0, norms)
        cosine = np.dot(matrix, q) / (safe_norms * q_norm)

        eligible_indices = [
            i
            for i, chunk_id in enumerate(self._chunk_ids)
            if (
                self._metadata.get(chunk_id, {}).get("status", "active") == "active"
                and (
                    categories is None
                    or self._metadata.get(chunk_id, {}).get("category") in categories
                )
            )
        ]
        if not eligible_indices:
            return []

        sorted_indices = sorted(
            eligible_indices,
            key=lambda i: float(cosine[i]),
            reverse=True,
        )
        top_indices = sorted_indices[:top_k]

        return [
            (self._chunk_ids[int(i)], float(cosine[i]))
            for i in top_indices
            if float(cosine[i]) > 0
        ]
