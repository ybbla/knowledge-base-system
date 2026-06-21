"""v1 真实端点测试 — 覆盖状态码、错误结构和检索过滤行为。"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_missing_document_returns_404_error_response():
    response = client.get("/api/v1/documents/__missing_doc_for_v1_test__")

    assert response.status_code == 404
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_missing_chunk_returns_404_error_response():
    response = client.get("/api/v1/chunks/__missing_chunk_for_v1_test__")

    assert response.status_code == 404
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "CHUNK_NOT_FOUND"


def test_health_ready_returns_object_not_tuple_array():
    response = client.get("/api/v1/health/ready")

    assert response.status_code in {200, 503}
    body = response.json()
    assert isinstance(body, dict)
    assert "data" in body
    assert "checks" in body["data"]


def test_search_filters_are_applied(monkeypatch):
    from app.api.v1 import search as search_api

    matching_chunk = SimpleNamespace(
        chunk_id="chunk_match",
        doc_id="doc_match",
        doc_version=1,
        title="匹配知识块",
        content="设备需要定期保养",
        category="设备维护",
        knowledge_type="procedural",
        status="active",
        metadata={"title": "匹配文档"},
        asset_refs=[],
        source_refs=[],
    )
    other_chunk = SimpleNamespace(
        chunk_id="chunk_other",
        doc_id="doc_other",
        doc_version=1,
        title="其他知识块",
        content="无关内容",
        category="其他",
        knowledge_type="declarative",
        status="active",
        metadata={"title": "其他文档"},
        asset_refs=[],
        source_refs=[],
    )

    class FakeResult:
        def model_dump(self, mode="json"):
            return {
                "search_id": "search_test",
                "query": "保养",
                "rewritten_query": "保养",
                "total_count": 2,
                "results": [
                    {
                        "chunk_id": "chunk_match",
                        "title": "匹配知识块",
                        "content": "设备需要定期保养",
                        "score": 0.9,
                        "category": "设备维护",
                        "knowledge_type": "procedural",
                        "score_components": {"vector": 0.8, "bm25": 0.7, "rerank": 0.9},
                        "asset_refs": [],
                        "source_refs": [],
                        "metadata": {},
                    },
                    {
                        "chunk_id": "chunk_other",
                        "title": "其他知识块",
                        "content": "无关内容",
                        "score": 0.8,
                        "category": "其他",
                        "knowledge_type": "declarative",
                        "score_components": {"vector": 0.8, "bm25": 0.7, "rerank": 0.8},
                        "asset_refs": [],
                        "source_refs": [],
                        "metadata": {},
                    },
                ],
            }

    class FakePipeline:
        def search(self, *args, **kwargs):
            return FakeResult()

    class FakeChunkStore:
        def get(self, chunk_id):
            return {"chunk_match": matching_chunk, "chunk_other": other_chunk}.get(chunk_id)

    monkeypatch.setattr(search_api, "retrieval_pipeline", FakePipeline())
    monkeypatch.setattr(search_api, "chunk_store", FakeChunkStore())
    monkeypatch.setattr(search_api, "document_repo", None)

    response = client.post(
        "/api/v1/search",
        json={
            "query": "保养",
            "top_k": 10,
            "filters": {
                "doc_ids": ["doc_match"],
                "categories": ["设备维护"],
                "knowledge_types": ["procedural"],
                "chunk_status": ["active"],
            },
            "options": {"highlight": True},
        },
    )

    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert [item["chunk_id"] for item in results] == ["chunk_match"]
    assert results[0]["doc_id"] == "doc_match"
    assert results[0]["doc_title"] == "匹配文档"
    assert "highlight" in results[0]


def test_debug_search_contains_stage_keys(monkeypatch):
    from app.api.v1 import search as search_api

    class FakeResult:
        def model_dump(self, mode="json"):
            return {
                "search_id": "search_test",
                "query": "测试",
                "rewritten_query": "测试",
                "total_count": 0,
                "results": [],
            }

    class FakeDebugInfo:
        def __init__(self):
            self.original_query = "测试"
            self.rewritten_query = "测试"
            self.keywords = ["测试"]
            self.vector_candidates = []
            self.bm25_candidates = []
            self.fused_candidates = []
            self.rerank_results = []
            self.vector_count = 0
            self.bm25_count = 0
            self.fused_count = 0
            self.rerank_count = 0
            self.errors = []

    class FakePipeline:
        def search(self, *args, **kwargs):
            if kwargs.get("debug"):
                return (FakeResult(), FakeDebugInfo())
            return FakeResult()

    monkeypatch.setattr(search_api, "retrieval_pipeline", FakePipeline())

    response = client.post("/api/v1/search/debug", json={"query": "测试"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert "vector_candidates" in data
    assert "bm25_candidates" in data
    assert "fused_candidates" in data
    assert "rerank_results" in data
