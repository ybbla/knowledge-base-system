from __future__ import annotations

from dataclasses import asdict

from .embedding import EmbeddingService, HashEmbeddingService
from .index import InMemoryHybridIndex
from .llm import LLMService, MockLLMService
from .models import KnowledgeChunk, ParsedDocument, RawDocument, SearchHit
from .parser import MarkdownParser, ParseOptions


class InMemoryKnowledgeBase:
    def __init__(
        self,
        llm: LLMService | None = None,
        embedding: EmbeddingService | None = None,
        parser: MarkdownParser | None = None,
        index: InMemoryHybridIndex | None = None,
        max_depth: int = 2,
    ) -> None:
        self.llm = llm or MockLLMService()
        self.embedding = embedding or HashEmbeddingService()
        self.parser = parser or MarkdownParser()
        self.index = index or InMemoryHybridIndex()
        self.max_depth = max_depth
        self.documents: dict[str, RawDocument] = {}
        self.parsed_documents: dict[str, ParsedDocument] = {}
        self.chunks: dict[str, KnowledgeChunk] = {}

    def ingest(
        self,
        documents: list[RawDocument],
        embedded_content_by_uri: dict[str, str] | None = None,
    ) -> dict:
        embedded_content_by_uri = embedded_content_by_uri or {}
        queue = list(documents)
        visited: set[str] = set()
        new_chunks: list[KnowledgeChunk] = []
        warnings: list[str] = []

        while queue:
            document = queue.pop(0)
            visit_key = document.source_uri or document.doc_id
            if visit_key in visited:
                warnings.append(f"Skipped duplicate document: {visit_key}")
                continue
            if document.depth > self.max_depth:
                warnings.append(f"Skipped document over max depth: {visit_key}")
                continue
            visited.add(visit_key)
            self.documents[document.doc_id] = document

            parsed = self.parser.parse(
                document,
                embedded_content_by_uri=embedded_content_by_uri,
                options=ParseOptions(max_depth=self.max_depth),
            )
            self.parsed_documents[parsed.doc_id] = parsed
            queue.extend(parsed.embedded_documents)

            chunks = self.llm.extract_chunks(parsed)
            embedding_inputs = [self._embedding_text(chunk) for chunk in chunks]
            embeddings = self.embedding.embed_texts(embedding_inputs)
            for chunk, vector in zip(chunks, embeddings):
                chunk.embedding = vector
                self.chunks[chunk.chunk_id] = chunk
            new_chunks.extend(chunks)

        self.index.add_chunks(new_chunks)
        return {
            "status": "completed",
            "doc_count": len(visited),
            "chunk_count": len(new_chunks),
            "warnings": warnings,
            "chunk_ids": [chunk.chunk_id for chunk in new_chunks],
        }

    def search(self, query: str, top_k: int = 5) -> dict:
        rewritten = self.llm.rewrite_query(query)
        rewritten_query = rewritten["rewritten_query"]
        query_embedding = self.embedding.embed_texts([rewritten_query])[0]
        candidates = self.index.hybrid_search(
            rewritten_query,
            query_embedding,
            top_k=max(top_k * 3, top_k),
            recall_k=20,
        )
        reranked = self.llm.rerank(rewritten_query, [hit.chunk for hit in candidates])
        rerank_score_by_id = {chunk_id: score for chunk_id, score, _ in reranked}
        final_hits = sorted(
            candidates,
            key=lambda hit: (rerank_score_by_id.get(hit.chunk.chunk_id, 0.0), hit.score),
            reverse=True,
        )[:top_k]
        return {
            "query": query,
            "rewritten_query": rewritten_query,
            "keywords": rewritten.get("keywords", []),
            "results": [self._hit_to_dict(hit, rerank_score_by_id) for hit in final_hits],
        }

    def get_chunk(self, chunk_id: str) -> dict | None:
        chunk = self.chunks.get(chunk_id)
        return asdict(chunk) if chunk else None

    @staticmethod
    def _embedding_text(chunk: KnowledgeChunk) -> str:
        title_path = " > ".join(chunk.metadata.get("title_path", []))
        return f"Title: {title_path}\nContent: {chunk.content}\nType: {chunk.knowledge_type}"

    @staticmethod
    def _hit_to_dict(hit: SearchHit, rerank_score_by_id: dict[str, float]) -> dict:
        return {
            "chunk_id": hit.chunk.chunk_id,
            "content": hit.chunk.content,
            "score": hit.score,
            "score_detail": {
                **hit.score_detail,
                "rerank_score": rerank_score_by_id.get(hit.chunk.chunk_id, 0.0),
            },
            "assets": [asdict(asset) for asset in hit.chunk.assets],
            "metadata": hit.chunk.metadata,
        }

