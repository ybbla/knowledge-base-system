from __future__ import annotations

import math
from collections import Counter, defaultdict

from .embedding import cosine_similarity
from .models import KnowledgeChunk, SearchHit
from .text import tokenize


class InMemoryHybridIndex:
    """内存版混合检索索引。

    该索引同时保存知识块向量和 BM25 所需的词频统计，支持向量检索、关键词
    检索以及 RRF 融合。正式版本可用 Milvus 实现相同接口。
    """

    def __init__(self) -> None:
        """初始化内存索引和 BM25 统计结构。"""

        self.chunks: dict[str, KnowledgeChunk] = {}
        self._doc_terms: dict[str, Counter[str]] = {}
        self._doc_freq: Counter[str] = Counter()
        self._avg_doc_len = 0.0

    def add_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        """向索引中加入知识块并重建 BM25 统计。

        参数:
            chunks: 已经生成 embedding 的知识块列表。
        """

        for chunk in chunks:
            self.chunks[chunk.chunk_id] = chunk
        self._rebuild_bm25()

    def vector_search(self, query_embedding: list[float], top_k: int = 10) -> list[SearchHit]:
        """执行内存向量检索。

        参数:
            query_embedding: 查询向量。
            top_k: 返回结果数量。

        返回:
            按余弦相似度降序排列的命中结果。
        """

        hits = [
            SearchHit(
                chunk=chunk,
                score=cosine_similarity(query_embedding, chunk.embedding),
                score_detail={"vector_score": cosine_similarity(query_embedding, chunk.embedding)},
            )
            for chunk in self.chunks.values()
        ]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]

    def bm25_search(self, query: str, top_k: int = 10) -> list[SearchHit]:
        """执行内存 BM25 关键词检索。

        参数:
            query: 查询文本。
            top_k: 返回结果数量。

        返回:
            按 BM25 分数降序排列的命中结果。
        """

        query_terms = tokenize(query)
        total_docs = max(len(self.chunks), 1)
        hits: list[SearchHit] = []
        k1 = 1.5
        b = 0.75
        for chunk_id, term_counts in self._doc_terms.items():
            doc_len = sum(term_counts.values()) or 1
            score = 0.0
            for term in query_terms:
                tf = term_counts.get(term, 0)
                if tf == 0:
                    continue
                df = self._doc_freq.get(term, 0)
                idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
                denom = tf + k1 * (1 - b + b * doc_len / (self._avg_doc_len or 1))
                score += idf * (tf * (k1 + 1)) / denom
            if score > 0:
                hits.append(
                    SearchHit(
                        chunk=self.chunks[chunk_id],
                        score=score,
                        score_detail={"bm25_score": score},
                    )
                )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int = 5,
        recall_k: int = 20,
    ) -> list[SearchHit]:
        """执行向量 + BM25 的混合召回。

        参数:
            query: 查询文本，用于 BM25。
            query_embedding: 查询向量，用于向量检索。
            top_k: 融合后返回结果数量。
            recall_k: 每一路召回的候选数量。

        返回:
            经过 RRF 融合后的候选结果。
        """

        vector_hits = self.vector_search(query_embedding, top_k=recall_k)
        bm25_hits = self.bm25_search(query, top_k=recall_k)
        fused = reciprocal_rank_fusion(vector_hits, bm25_hits)
        return fused[:top_k]

    def _rebuild_bm25(self) -> None:
        """根据当前全部知识块重建 BM25 词频和文档频率统计。

        说明:
            MVP 为了简单，每次新增知识块后全量重建。正式版本应使用搜索引擎
            或 Milvus 稀疏检索能力维护倒排/稀疏索引。
        """

        self._doc_terms.clear()
        self._doc_freq.clear()
        total_len = 0
        for chunk_id, chunk in self.chunks.items():
            terms = Counter(tokenize(chunk.content))
            self._doc_terms[chunk_id] = terms
            total_len += sum(terms.values())
            for term in terms:
                self._doc_freq[term] += 1
        self._avg_doc_len = total_len / max(len(self._doc_terms), 1)


def reciprocal_rank_fusion(
    vector_hits: list[SearchHit],
    bm25_hits: list[SearchHit],
    k: int = 60,
) -> list[SearchHit]:
    """使用 Reciprocal Rank Fusion 融合多路召回结果。

    参数:
        vector_hits: 向量召回结果，已按相关性排序。
        bm25_hits: BM25 召回结果，已按相关性排序。
        k: RRF 平滑参数，常用值为 60。

    返回:
        融合后的命中结果列表，按 RRF 分数降序排列。
    """

    scores: defaultdict[str, float] = defaultdict(float)
    score_detail: dict[str, dict[str, float]] = defaultdict(dict)
    chunk_by_id: dict[str, KnowledgeChunk] = {}

    for rank, hit in enumerate(vector_hits, start=1):
        chunk_id = hit.chunk.chunk_id
        chunk_by_id[chunk_id] = hit.chunk
        scores[chunk_id] += 1 / (k + rank)
        score_detail[chunk_id]["vector_score"] = hit.score
        score_detail[chunk_id]["vector_rank"] = float(rank)

    for rank, hit in enumerate(bm25_hits, start=1):
        chunk_id = hit.chunk.chunk_id
        chunk_by_id[chunk_id] = hit.chunk
        scores[chunk_id] += 1 / (k + rank)
        score_detail[chunk_id]["bm25_score"] = hit.score
        score_detail[chunk_id]["bm25_rank"] = float(rank)

    fused = [
        SearchHit(chunk=chunk_by_id[chunk_id], score=score, score_detail=score_detail[chunk_id])
        for chunk_id, score in scores.items()
    ]
    return sorted(fused, key=lambda hit: hit.score, reverse=True)
