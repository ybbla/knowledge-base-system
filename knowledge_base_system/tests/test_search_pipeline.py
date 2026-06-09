"""
Integration test for the search pipeline.

Requires VOLCENGINE_API_KEY in environment or config.
Run with: pytest tests/test_search_pipeline.py -v
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SAMPLE_MARKDOWN = """\
# 产品使用手册

## 上传知识文档

用户可以在知识库页面上传文档，支持 Markdown 和 TXT 格式。

上传后系统会显示解析状态：

| 状态 | 说明 |
|------|------|
| 处理中 | 系统正在解析文档 |
| 成功 | 文档已经进入知识库 |
| 失败 | 需要查看失败原因并重新上传 |

### 注意事项

- 单文件不超过 10 MB
- 支持批量上传

界面截图如下：

![上传状态截图](https://example.com/upload-status.png)
"""


class TestSearchPipeline:
    """End-to-end search pipeline tests with real LLM API."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Ingest a test document and wait for completion."""
        # Ingest
        resp = client.post(
            "/ingest",
            json={
                "documents": [
                    {
                        "title": "产品使用手册",
                        "source_type": "markdown",
                        "content": SAMPLE_MARKDOWN,
                    }
                ],
                "options": {"max_depth": 1},
            },
        )
        assert resp.status_code == 200, f"Ingest failed: {resp.text}"
        data = resp.json()
        assert data["status"] == "accepted"

        job_id = data["job_id"]
        self.job_id = job_id

        # Poll until completed or failed
        for _ in range(60):
            status_resp = client.get(f"/ingest/{job_id}")
            assert status_resp.status_code == 200
            job = status_resp.json()
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(2)

        self.job_result = job

    def test_ingest_completed(self):
        """Ingestion should complete successfully."""
        assert self.job_result["status"] == "completed", (
            f"Ingestion failed: {self.job_result.get('error')}"
        )
        assert self.job_result["chunk_count"] > 0
        assert len(self.job_result["doc_ids"]) > 0

    def test_search_returns_results(self):
        """Search should return ranked results with all required fields."""
        resp = client.post(
            "/search",
            json={"query": "上传文档后如何判断解析成功？", "top_k": 5},
        )
        assert resp.status_code == 200, f"Search failed: {resp.text}"
        data = resp.json()

        # Top-level fields
        assert "search_id" in data
        assert data["search_id"].startswith("search_")
        assert "query" in data
        assert "rewritten_query" in data
        assert "total_count" in data
        assert data["total_count"] > 0

        # Results
        assert "results" in data
        results = data["results"]
        assert len(results) > 0
        assert len(results) <= 5

        # First result
        r = results[0]
        assert "chunk_id" in r
        assert r["chunk_id"].startswith("chunk_")
        assert "title" in r
        assert "content" in r
        assert len(r["content"]) > 0
        assert "score" in r
        assert r["score"] > 0

        # Score components
        assert "score_components" in r
        sc = r["score_components"]
        assert "vector" in sc
        assert "bm25" in sc
        assert "rerank" in sc

        # Source refs
        assert "source_refs" in r
        assert len(r["source_refs"]) > 0
        sr = r["source_refs"][0]
        assert "doc_id" in sr
        assert "element_id" in sr

        # Metadata
        assert "metadata" in r
        assert "title_path" in r["metadata"]
        assert "knowledge_type" in r["metadata"]

    def test_search_content_relevant(self):
        """Search results should contain content related to the query."""
        resp = client.post(
            "/search",
            json={"query": "上传文档", "top_k": 5},
        )
        assert resp.status_code == 200
        data = resp.json()

        contents = " ".join(r["content"] for r in data["results"])
        # Should mention upload-related terms
        assert any(
            term in contents for term in ["上传", "文档"]
        ), f"No relevant content found in: {contents[:200]}"
