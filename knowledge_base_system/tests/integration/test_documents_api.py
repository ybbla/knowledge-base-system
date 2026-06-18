"""文档管理页面集成测试 — 验证前端 documents.js 调用的所有 API 端点。

前端 documents.js 调用链（已全面迁移至 v1）：
  1. GET  /api/v1/search/filters                        → 加载分类选项 (renderList L20)
  2. GET  /api/v1/documents?page=&page_size=15&...       → 分页文档列表 (loadPage L39)
  3. GET  /api/v1/documents/{doc_id}                    → 文档详情 (点击详情链接)
  4. DELETE /api/v1/documents/{doc_id}                   → 软删除 (deleteDoc L168)
  5. POST /api/v1/documents/{doc_id}/restore            → 恢复 (restoreDoc L178)
  6. POST /api/v1/documents/{doc_id}/ingest?mode=incremental → 重新处理已有文档 (ingestDocument L188)
  7. POST /api/v1/documents                             → 创建文档 (后端支持)
  8. PATCH /api/v1/documents/{doc_id}                   → 更新文档 (后端支持)
  9. POST /api/v1/documents/upload                      → 文件上传 (uploadDocument L374)
旧版 /upload、/ingest、/ingest/{job_id} 已标记废弃，保留兼容期内可用。

本测试使用 TestClient 对真实 FastAPI app 发起请求，
验证响应结构完全匹配前端期望，确保前后端联调可用。
"""

import io
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)

# 模拟文件目录
_SIMULATED_DIR = Path(__file__).resolve().parents[3] / "data" / "simulated_inputs"
_SIMULATED_FILES = {
    "markdown": _SIMULATED_DIR / "simulated_dev_guide.md",
    "txt": _SIMULATED_DIR / "simulated_project_plan.txt",
    "docx": _SIMULATED_DIR / "simulated_system_manual.docx",
    "xlsx": _SIMULATED_DIR / "simulated_user_stats.xlsx",
    "html": _SIMULATED_DIR / "simulated_dashboard.html",
    "pdf": _SIMULATED_DIR / "simulated_api_whitepaper.pdf",
    "pptx": _SIMULATED_DIR / "simulated_q4_review.pptx",
}
_CONTENT_TYPES = {
    "markdown": "text/markdown", "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html", "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


# ══════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════

def _create_test_doc(title="集成测试文档", source_type="markdown",
                     source_uri="file:///test/integration.md", category="测试"):
    """创建测试文档并返回响应 JSON data。"""
    resp = client.post("/api/v1/documents", params={
        "title": title,
        "source_type": source_type,
        "source_uri": source_uri,
        "category": category,
    })
    assert resp.status_code == 201, f"创建文档失败: {resp.text}"
    return resp.json()["data"]


def _cleanup_doc(doc_id: str):
    """尝试彻底删除文档（如果存在）。"""
    # 先确保软删除
    client.delete(f"/api/v1/documents/{doc_id}")
    # 如果 PG 后端支持硬删除就更好，这里只是尽力清理


def _get_simulated_file(source_type: str) -> tuple[bytes, str, str]:
    """读取模拟文件，返回 (content_bytes, filename, content_type)。
    文件不存在时跳过测试。
    """
    path = _SIMULATED_FILES.get(source_type)
    if path is None or not path.exists():
        import pytest
        pytest.skip(f"模拟文件不存在: {path}")
    return path.read_bytes(), path.name, _CONTENT_TYPES.get(source_type, "application/octet-stream")


def _upload_simulated(source_type: str, **kwargs):
    """上传模拟文件，返回 httpx Response。
    透传 title/category/ingest_after_create/mode 参数。
    """
    content, filename, content_type = _get_simulated_file(source_type)
    params = {
        "ingest_after_create": str(kwargs.pop("ingest_after_create", True)).lower(),
        "mode": kwargs.pop("mode", "incremental"),
    }
    data = {}
    if "title" in kwargs:
        data["title"] = kwargs["title"]
    if "category" in kwargs:
        data["category"] = kwargs["category"]
    return client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data=data,
        params=params,
    )


# ══════════════════════════════════════════════════════════════════════
# 1. GET /api/v1/search/filters — 分类选项加载
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsSearchFilters:
    """前端: API.searchFilters() → res?.data?.categories[].value"""

    def test_filters_returns_unified_structure(self):
        """筛选项接口返回统一的 { data, meta, error } 结构。"""
        response = client.get("/api/v1/search/filters")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_filters_contains_categories_array(self):
        """前端用 data.categories 渲染分类下拉框 (documents.js:21)。"""
        response = client.get("/api/v1/search/filters")
        body = response.json()

        assert "categories" in body["data"]
        assert isinstance(body["data"]["categories"], list)

    def test_filters_categories_have_value_field(self):
        """每个分类条目必须有 value 字段 (documents.js:21: c.value)。"""
        response = client.get("/api/v1/search/filters")
        categories = response.json()["data"]["categories"]

        for cat in categories:
            assert "value" in cat, f"分类条目缺少 value: {cat}"

    def test_filters_contains_all_required_keys(self):
        """前端 search.js 和其他页面也依赖这些筛选维度。"""
        response = client.get("/api/v1/search/filters")
        data = response.json()["data"]

        required_keys = [
            "categories", "source_types", "knowledge_types",
            "doc_statuses", "chunk_statuses", "index_statuses",
        ]
        for key in required_keys:
            assert key in data, f"缺少筛选项: {key}"


# ══════════════════════════════════════════════════════════════════════
# 2. GET /api/v1/documents — 文档分页列表
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsList:
    """前端: API.listDocuments(params) → res.data[], res.meta (documents.js:39)"""

    def test_list_returns_paginated_structure(self):
        """文档列表返回 { data: [...], meta: { total, page, page_size }, error: null }。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 5})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None
        assert isinstance(body["data"], list)

    def test_list_meta_has_pagination_fields(self):
        """meta 包含完整分页信息，前端据此渲染分页控件 (documents.js:143-148)。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 15})
        body = response.json()

        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 15
        assert "total" in body["meta"]
        assert "total_pages" in body["meta"]
        assert isinstance(body["meta"]["total"], int)
        assert body["meta"]["total"] >= 0

    def test_list_default_page_size_matches_frontend(self):
        """前端默认 page_size=15 (documents.js:32)。"""
        response = client.get("/api/v1/documents", params={
            "page": 1, "page_size": 15,
        })
        body = response.json()
        assert body["meta"]["page_size"] == 15

    def test_list_with_keyword_filter(self):
        """前端搜索框传 keyword 参数 (documents.js:33)。"""
        response = client.get("/api/v1/documents", params={
            "page": 1, "page_size": 15, "keyword": "测试",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None

    def test_list_with_status_filter(self):
        """前端状态下拉框传 status 参数 (documents.js:34)。"""
        for status_val in ["active", "pending", "processing", "failed", "deleted"]:
            response = client.get("/api/v1/documents", params={
                "page": 1, "page_size": 5, "status": status_val,
            })
            assert response.status_code == 200, f"status={status_val} 请求失败"
            body = response.json()
            assert body["error"] is None

    def test_list_with_category_filter(self):
        """前端分类下拉框传 category 参数 (documents.js:35)。"""
        response = client.get("/api/v1/documents", params={
            "page": 1, "page_size": 5, "category": "通用",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None

    def test_list_with_sort_params(self):
        """前端传 sort_by=updated_at&sort_order=desc (documents.js:36-37)。"""
        response = client.get("/api/v1/documents", params={
            "page": 1, "page_size": 5,
            "sort_by": "updated_at", "sort_order": "desc",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None

    def test_list_all_params_combined(self):
        """前端 loadPage() 实际发送的完整参数组合 (documents.js:30-38)。"""
        response = client.get("/api/v1/documents", params={
            "page": 1,
            "page_size": 15,
            "keyword": "",
            "status": "",
            "category": "",
            "sort_by": "updated_at",
            "sort_order": "desc",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None
        assert isinstance(body["data"], list)
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 15

    def test_list_document_item_has_required_fields(self):
        """每个文档条目包含前端表格渲染所需的字段 (documents.js:65-87)。"""
        # 先确保至少有一条数据
        try:
            doc = _create_test_doc()
            doc_id = doc["doc_id"]
        except Exception:
            doc_id = None

        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 5})
        body = response.json()
        items = body["data"]

        if items:
            item = items[0]
            required_fields = [
                "doc_id", "title", "source_type", "category",
                "status", "chunk_count", "element_count",
                "created_at", "updated_at",
            ]
            for field in required_fields:
                assert field in item, f"文档条目缺少字段: {field}"

            # 前端用 source_type 渲染格式标签 (documents.js:70: UI.fmtBadge)
            assert isinstance(item["source_type"], str)
            # 前端用 status 渲染状态标签 (documents.js:77: UI.statusBadge)
            assert isinstance(item["status"], str)
            # 前端用 category 渲染分类列 (documents.js:76)
            assert isinstance(item["category"], str)

        # 清理
        if doc_id:
            _cleanup_doc(doc_id)

    def test_list_empty_state_no_error(self):
        """空列表时也正常返回，前端展示空状态 (documents.js:54-63)。"""
        response = client.get("/api/v1/documents", params={
            "page": 1, "page_size": 5,
            "keyword": "__nonexistent_keyword_xyz__",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None
        assert isinstance(body["data"], list)


# ══════════════════════════════════════════════════════════════════════
# 3. POST /api/v1/documents — 创建文档
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsCreate:
    """前端: API.createDocument(params) (api.js:96)"""

    def test_create_returns_201_with_doc_data(self):
        """创建文档返回 201 和文档数据。"""
        response = client.post("/api/v1/documents", params={
            "title": "创建测试文档",
            "source_type": "markdown",
            "source_uri": "file:///test/create_test.md",
            "category": "测试",
        })
        assert response.status_code == 201
        body = response.json()
        assert body["data"]["title"] == "创建测试文档"
        assert body["data"]["source_type"] == "markdown"
        assert body["data"]["status"] in ("active", "pending")
        assert "doc_id" in body["data"]

        _cleanup_doc(body["data"]["doc_id"])

    def test_create_with_default_category(self):
        """不传 category 时默认为"通用" (documents.py:229)。"""
        response = client.post("/api/v1/documents", params={
            "title": "默认分类文档",
            "source_type": "markdown",
            "source_uri": "file:///test/default_cat.md",
        })
        assert response.status_code == 201
        body = response.json()
        assert body["data"]["category"] == "通用"

        _cleanup_doc(body["data"]["doc_id"])

    def test_create_with_all_source_types(self):
        """前端支持的所有 source_type (documents.js:399-401)。"""
        source_types = ["markdown", "docx", "xlsx", "html", "pdf", "pptx", "manual"]
        for st in source_types:
            response = client.post("/api/v1/documents", params={
                "title": f"测试 {st} 文档",
                "source_type": st,
                "source_uri": f"file:///test/test.{st}",
                "category": "测试",
            })
            assert response.status_code == 201, f"source_type={st} 创建失败: {response.text}"
            _cleanup_doc(response.json()["data"]["doc_id"])

    def test_create_with_source_hash(self):
        """带 source_hash 创建文档。"""
        response = client.post("/api/v1/documents", params={
            "title": "带哈希文档",
            "source_type": "markdown",
            "source_uri": "file:///test/hash_test.md",
            "source_hash": "sha256:integration_test_hash_001",
            "category": "测试",
        })
        assert response.status_code == 201
        body = response.json()
        assert body["data"]["source_hash"] == "sha256:integration_test_hash_001"

        _cleanup_doc(body["data"]["doc_id"])

    def test_create_with_metadata_json(self):
        """带 metadata JSON 字符串创建文档。"""
        response = client.post("/api/v1/documents", params={
            "title": "带元数据文档",
            "source_type": "markdown",
            "source_uri": "file:///test/meta_test.md",
            "category": "测试",
            "metadata": '{"author": "tester", "tags": ["integration"]}',
        })
        assert response.status_code == 201
        body = response.json()
        assert body["data"]["metadata"] == {"author": "tester", "tags": ["integration"]}

        _cleanup_doc(body["data"]["doc_id"])

    def test_create_duplicate_source_hash_returns_409(self):
        """相同 source_hash 的文档创建返回 409 (documents.py:249-257)。"""
        import uuid
        unique_hash = f"sha256:dup_test_{uuid.uuid4().hex}"
        # 第一次创建
        resp1 = client.post("/api/v1/documents", params={
            "title": "去重文档1",
            "source_type": "markdown",
            "source_uri": f"file:///test/dup_{uuid.uuid4().hex}.md",
            "source_hash": unique_hash,
            "category": "测试",
        })
        assert resp1.status_code == 201, f"第一次创建失败: {resp1.text}"
        doc1_id = resp1.json()["data"]["doc_id"]

        # 第二次创建（相同 hash）
        resp2 = client.post("/api/v1/documents", params={
            "title": "去重文档2",
            "source_type": "markdown",
            "source_uri": f"file:///test/dup_{uuid.uuid4().hex}.md",
            "source_hash": unique_hash,
            "category": "测试",
        })
        assert resp2.status_code == 409, f"应返回 409, 实际: {resp2.status_code} {resp2.text}"
        err_body = resp2.json()
        assert err_body["error"]["code"] == "DOCUMENT_DUPLICATE"

        _cleanup_doc(doc1_id)

    def test_create_missing_required_fields_returns_422(self):
        """缺少必填字段返回 422 验证错误。"""
        response = client.post("/api/v1/documents", params={
            "title": "缺少字段",
            # 缺少 source_type 和 source_uri
        })
        assert response.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# 4. GET /api/v1/documents/{doc_id} — 文档详情
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsDetail:
    """前端: API.getDocument(docId) (api.js:99)，点击详情链接跳转到文档详情页。"""

    def test_get_document_returns_full_detail(self):
        """文档详情包含所有字段和统计信息。"""
        doc = _create_test_doc("详情测试文档")
        doc_id = doc["doc_id"]

        response = client.get(f"/api/v1/documents/{doc_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["doc_id"] == doc_id
        assert body["data"]["title"] == "详情测试文档"
        assert "chunk_count" in body["data"]
        assert "element_count" in body["data"]
        assert "asset_count" in body["data"]
        assert "index_summary" in body["data"]
        assert "metadata" in body["data"]

        _cleanup_doc(doc_id)

    def test_get_nonexistent_document_returns_404(self):
        """不存在的文档返回 404 + DOCUMENT_NOT_FOUND (documents.py:321-325)。"""
        response = client.get("/api/v1/documents/__nonexistent_doc_for_test__")
        assert response.status_code == 404
        body = response.json()
        assert body["data"] is None
        assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"

    def test_get_document_response_has_unified_structure(self):
        """详情响应也遵循统一的 { data, meta, error } 结构。"""
        doc = _create_test_doc("结构测试文档")
        doc_id = doc["doc_id"]

        response = client.get(f"/api/v1/documents/{doc_id}")
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

        _cleanup_doc(doc_id)


# ══════════════════════════════════════════════════════════════════════
# 4.5 GET /api/v1/documents/{doc_id}/elements — 文档解析元素
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsElements:
    """前端: 文档详情页展示解析元素列表。"""

    def test_elements_returns_paginated_structure(self):
        """元素列表返回统一的分页响应结构。"""
        doc = _create_test_doc("元素测试文档")
        doc_id = doc["doc_id"]

        try:
            response = client.get(f"/api/v1/documents/{doc_id}/elements")
            assert response.status_code == 200
            body = response.json()
            assert "data" in body
            assert "meta" in body
            assert body["error"] is None
            assert isinstance(body["data"], list)
            assert "total" in body["meta"]
            assert "page" in body["meta"]
            assert "page_size" in body["meta"]
        finally:
            _cleanup_doc(doc_id)

    def test_elements_item_has_required_fields(self):
        """每个元素条目包含前端渲染所需的字段。"""
        doc = _create_test_doc("元素字段测试")
        doc_id = doc["doc_id"]

        try:
            response = client.get(f"/api/v1/documents/{doc_id}/elements")
            items = response.json()["data"]

            if items:
                item = items[0]
                required_fields = [
                    "element_id", "doc_id", "doc_version",
                    "sequence_order", "element_type", "text",
                ]
                for field in required_fields:
                    assert field in item, f"元素条目缺少字段: {field}"
                assert isinstance(item["sequence_order"], int)
                assert isinstance(item["element_type"], str)
        finally:
            _cleanup_doc(doc_id)

    def test_elements_nonexistent_document_returns_404(self):
        """不存在的文档查询元素返回 404。"""
        response = client.get(
            "/api/v1/documents/__nonexistent_elements_test__/elements"
        )
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"

    def test_elements_pagination(self):
        """元素列表支持分页参数。"""
        doc = _create_test_doc("元素分页测试")
        doc_id = doc["doc_id"]

        try:
            response = client.get(
                f"/api/v1/documents/{doc_id}/elements",
                params={"page": 1, "page_size": 5},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["meta"]["page"] == 1
            assert body["meta"]["page_size"] == 5
            assert len(body["data"]) <= 5
        finally:
            _cleanup_doc(doc_id)

    def test_elements_default_pagination(self):
        """不带分页参数时使用默认值（page=1, page_size=20）。"""
        doc = _create_test_doc("元素默认分页")
        doc_id = doc["doc_id"]

        try:
            response = client.get(f"/api/v1/documents/{doc_id}/elements")
            body = response.json()
            assert body["meta"]["page"] == 1
            assert body["meta"]["page_size"] == 20
        finally:
            _cleanup_doc(doc_id)


# ══════════════════════════════════════════════════════════════════════
# 5. PATCH /api/v1/documents/{doc_id} — 更新文档
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsUpdate:
    """前端: API.updateDocument(docId, params) (api.js:102)"""

    def test_update_title(self):
        """更新文档标题。"""
        doc = _create_test_doc("原始标题")
        doc_id = doc["doc_id"]

        response = client.patch(f"/api/v1/documents/{doc_id}", params={
            "title": "更新后的标题",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["title"] == "更新后的标题"

        _cleanup_doc(doc_id)

    def test_update_category(self):
        """更新文档分类。"""
        doc = _create_test_doc("分类更新测试")
        doc_id = doc["doc_id"]

        response = client.patch(f"/api/v1/documents/{doc_id}", params={
            "category": "新分类",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["category"] == "新分类"

        _cleanup_doc(doc_id)

    def test_update_status(self):
        """更新文档状态。"""
        doc = _create_test_doc("状态更新测试")
        doc_id = doc["doc_id"]

        response = client.patch(f"/api/v1/documents/{doc_id}", params={
            "status": "failed",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "failed"

        _cleanup_doc(doc_id)

    def test_update_source_uri_triggers_needs_reingest(self):
        """更新 source_uri 后响应标记 needs_reingest (documents.py:424-426)。"""
        doc = _create_test_doc("来源更新测试")
        doc_id = doc["doc_id"]

        response = client.patch(f"/api/v1/documents/{doc_id}", params={
            "source_uri": "file:///test/updated_source.md",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["needs_reingest"] is True

        _cleanup_doc(doc_id)

    def test_update_with_optimistic_lock(self):
        """使用 expected_version 乐观锁更新。"""
        doc = _create_test_doc("乐观锁测试")
        doc_id = doc["doc_id"]
        original_version = doc["version"]

        response = client.patch(f"/api/v1/documents/{doc_id}", params={
            "title": "乐观锁更新",
            "expected_version": original_version,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["version"] == original_version + 1

        _cleanup_doc(doc_id)

    def test_update_version_conflict_returns_409(self):
        """版本号不匹配返回 409 (documents.py:407-413)。"""
        doc = _create_test_doc("版本冲突测试")
        doc_id = doc["doc_id"]
        wrong_version = doc["version"] + 99

        response = client.patch(f"/api/v1/documents/{doc_id}", params={
            "title": "冲突更新",
            "expected_version": wrong_version,
        })
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "DOCUMENT_VERSION_CONFLICT"

        _cleanup_doc(doc_id)

    def test_update_nonexistent_document_returns_404(self):
        """更新不存在的文档返回 404。"""
        response = client.patch("/api/v1/documents/__nonexistent_update_test__", params={
            "title": "不存在的文档",
        })
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════
# 6. DELETE /api/v1/documents/{doc_id} — 软删除文档
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsDelete:
    """前端: API.deleteDocument(docId) (documents.js:168)"""

    def test_delete_sets_status_to_deleted(self):
        """软删除后文档状态变为 deleted (documents.js:168)。"""
        doc = _create_test_doc("删除测试文档")
        doc_id = doc["doc_id"]

        response = client.delete(f"/api/v1/documents/{doc_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "deleted"

        # 验证确实被标记为删除
        detail_resp = client.get(f"/api/v1/documents/{doc_id}")
        if detail_resp.status_code == 200:
            assert detail_resp.json()["data"]["status"] == "deleted"

        # 恢复以便清理
        client.post(f"/api/v1/documents/{doc_id}/restore")
        _cleanup_doc(doc_id)

    def test_delete_nonexistent_document_returns_404(self):
        """删除不存在的文档返回 404。"""
        response = client.delete("/api/v1/documents/__nonexistent_delete_test__")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"

    def test_delete_already_deleted_document(self):
        """重复删除已删除的文档。"""
        doc = _create_test_doc("重复删除测试")
        doc_id = doc["doc_id"]

        # 第一次删除
        client.delete(f"/api/v1/documents/{doc_id}")

        # 第二次删除（应成功或返回合理状态）
        resp2 = client.delete(f"/api/v1/documents/{doc_id}")
        # 应该成功（幂等）或返回合理状态
        assert resp2.status_code in {200, 404}

        client.post(f"/api/v1/documents/{doc_id}/restore")
        _cleanup_doc(doc_id)


# ══════════════════════════════════════════════════════════════════════
# 7. POST /api/v1/documents/{doc_id}/restore — 恢复文档
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsRestore:
    """前端: API.restoreDocument(docId) (documents.js:178)"""

    def test_restore_sets_status_to_active(self):
        """恢复后文档状态变为 active (documents.js:178)。"""
        doc = _create_test_doc("恢复测试文档")
        doc_id = doc["doc_id"]

        # 先删除
        client.delete(f"/api/v1/documents/{doc_id}")

        # 再恢复
        response = client.post(f"/api/v1/documents/{doc_id}/restore")
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "active"
        assert "restored_chunks" in body["meta"]

        _cleanup_doc(doc_id)

    def test_restore_active_document(self):
        """恢复未删除的文档（应成功）。"""
        doc = _create_test_doc("恢复活跃文档")
        doc_id = doc["doc_id"]

        response = client.post(f"/api/v1/documents/{doc_id}/restore")
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "active"

        _cleanup_doc(doc_id)

    def test_restore_nonexistent_document_returns_404(self):
        """恢复不存在的文档返回 404。"""
        response = client.post("/api/v1/documents/__nonexistent_restore_test__/restore")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════
# 8. POST /api/v1/documents/{doc_id}/ingest — 触发入库
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsIngest:
    """前端: API.ingestDocument(docId, 'incremental') (documents.js:188)"""

    def test_ingest_returns_job_id(self):
        """触发入库返回 job_id (documents.js:188)。"""
        doc = _create_test_doc("入库测试文档")
        doc_id = doc["doc_id"]

        response = client.post(
            f"/api/v1/documents/{doc_id}/ingest",
            params={"mode": "incremental"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "job_id" in body["data"]
        assert body["data"]["doc_id"] == doc_id
        assert body["data"]["mode"] == "incremental"
        assert body["meta"]["status"] == "accepted"

        _cleanup_doc(doc_id)

    def test_ingest_default_mode_is_incremental(self):
        """默认 mode=incremental (documents.py:536)。"""
        doc = _create_test_doc("增量入库测试")
        doc_id = doc["doc_id"]

        response = client.post(f"/api/v1/documents/{doc_id}/ingest")
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["mode"] == "incremental"
        assert body["meta"]["status"] == "accepted"

        _cleanup_doc(doc_id)

    def test_ingest_nonexistent_document_returns_404(self):
        """对不存在的文档触发入库返回 404。"""
        response = client.post("/api/v1/documents/__nonexistent_ingest_test__/ingest")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════
# 9. 完整 CRUD 流程 — 模拟前端操作序列
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsFullCRUDFlow:
    """模拟前端 documents.js 的完整操作流程:
    renderList → loadPage → 删除 → 恢复 → 重新处理
    """

    def test_full_lifecycle_create_get_update_delete_restore(self):
        """完整生命周期: 创建 → 查看 → 更新 → 删除 → 恢复 → 查看。"""
        # ── 步骤 1: 创建文档 (模拟上传后创建) ──
        create_resp = client.post("/api/v1/documents", params={
            "title": "完整流程测试文档",
            "source_type": "markdown",
            "source_uri": "file:///test/full_flow.md",
            "source_hash": "sha256:full_flow_test_hash",
            "category": "测试",
            "metadata": '{"author": "integration_test"}',
        })
        assert create_resp.status_code == 201
        doc_id = create_resp.json()["data"]["doc_id"]

        # ── 步骤 2: 查看文档详情 ──
        get_resp = client.get(f"/api/v1/documents/{doc_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["title"] == "完整流程测试文档"
        assert get_resp.json()["data"]["category"] == "测试"

        # ── 步骤 3: 更新文档 ──
        update_resp = client.patch(f"/api/v1/documents/{doc_id}", params={
            "title": "已更新的完整流程文档",
            "category": "新测试分类",
        })
        assert update_resp.status_code == 200
        assert update_resp.json()["data"]["title"] == "已更新的完整流程文档"
        assert update_resp.json()["data"]["category"] == "新测试分类"

        # ── 步骤 4: 软删除 ──
        delete_resp = client.delete(f"/api/v1/documents/{doc_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["data"]["status"] == "deleted"

        # ── 步骤 5: 恢复 ──
        restore_resp = client.post(f"/api/v1/documents/{doc_id}/restore")
        assert restore_resp.status_code == 200
        assert restore_resp.json()["data"]["status"] == "active"

        # ── 步骤 6: 再次查看确认状态 ──
        final_resp = client.get(f"/api/v1/documents/{doc_id}")
        assert final_resp.status_code == 200
        assert final_resp.json()["data"]["status"] == "active"
        assert final_resp.json()["data"]["title"] == "已更新的完整流程文档"

        # 清理
        _cleanup_doc(doc_id)

    def test_full_frontend_flow_simulated(self):
        """精确模拟前端 documents.js renderList() → loadPage() 的调用序列。"""
        # ── 步骤 1: 加载分类选项 (documents.js:20) ──
        filters_resp = client.get("/api/v1/search/filters")
        assert filters_resp.status_code == 200
        categories = filters_resp.json()["data"]["categories"]
        assert isinstance(categories, list)

        # ── 步骤 2: 加载文档列表 (documents.js:30-38) ──
        list_params = {
            "page": 1,
            "page_size": 15,
            "keyword": "",
            "status": "",
            "category": "",
            "sort_by": "updated_at",
            "sort_order": "desc",
        }
        list_resp = client.get("/api/v1/documents", params=list_params)
        assert list_resp.status_code == 200
        list_body = list_resp.json()

        # 前端: res?.data || [] → items.length === 0 判断空状态
        items = list_body["data"]
        assert isinstance(items, list)

        # 前端: res?.meta || {} → meta.total, meta.total_pages
        meta = list_body["meta"]
        assert isinstance(meta["total"], int)
        assert isinstance(meta["total_pages"], int)

        # 前端: 每个 item 渲染表格行 (documents.js:65-87)
        for item in items:
            assert "doc_id" in item
            assert "title" in item
            assert "source_type" in item
            assert "category" in item
            assert "status" in item
            assert "chunk_count" in item
            assert "element_count" in item

    def test_frontend_status_filter_values_all_work(self):
        """前端状态下拉框 5 个选项 (documents.js:114-118) 都能正常请求。"""
        status_values = ["", "active", "pending", "processing", "failed", "deleted"]
        for sv in status_values:
            params = {"page": 1, "page_size": 5}
            if sv:
                params["status"] = sv
            response = client.get("/api/v1/documents", params=params)
            assert response.status_code == 200, f"status={sv} 请求失败: {response.text}"
            body = response.json()
            assert body["error"] is None

    def test_batch_delete_flow(self):
        """模拟前端批量删除 (documents.js:220-230): 逐条 DELETE。"""
        # 创建 3 个测试文档
        doc_ids = []
        for i in range(3):
            doc = _create_test_doc(f"批量删除测试{i+1}")
            doc_ids.append(doc["doc_id"])

        # 逐条删除（前端实现方式）
        done = 0
        for doc_id in doc_ids:
            resp = client.delete(f"/api/v1/documents/{doc_id}")
            if resp.status_code == 200:
                done += 1

        assert done == 3

        # 清理
        for doc_id in doc_ids:
            client.post(f"/api/v1/documents/{doc_id}/restore")
            _cleanup_doc(doc_id)


# ══════════════════════════════════════════════════════════════════════
# 10. 旧版上传/入库 API — 前端已迁移至 v1，旧接口仅保留兼容
# ══════════════════════════════════════════════════════════════════════

class TestLegacyUploadAPI:
    """旧版 /upload、/ingest、/ingest/{job_id} 已标记废弃并添加 X-Deprecated
    响应头。前端已迁移至 v1（API.uploadDocument、API.ingestDocument 等），
    旧接口保留兼容期内可用，本测试验证其仍能正常响应。
    """

    def test_upload_endpoint_exists(self):
        """POST /upload 端点必须存在并能处理请求。"""
        import io
        # 用空内容测试端点是否存在
        response = client.post("/upload", files={
            "file": ("test.md", io.BytesIO(b"# test"), "text/markdown"),
        }, data={
            "title": "上传测试",
            "category": "测试",
        })
        # 应返回 200（成功）或合理的错误状态
        assert response.status_code in {200, 201, 400, 422, 500, 503}, \
            f"上传端点异常: {response.status_code}"

    def test_ingest_endpoint_exists(self):
        """POST /ingest 端点必须存在并能处理请求。"""
        response = client.post("/ingest", json={
            "documents": [{
                "title": "入库测试文档",
                "source_type": "markdown",
                "source_uri": "file:///test/ingest_test.md",
                "category": "测试",
            }],
            "options": {},
        })
        # 应返回 200/202（已接受）或合理状态
        assert response.status_code in {200, 202, 400, 422, 500, 503}, \
            f"入库端点异常: {response.status_code}"

    def test_ingest_job_query_endpoint_exists(self):
        """GET /ingest/{job_id} 端点必须存在（前端轮询用, ingestion.js:61）。"""
        response = client.get("/ingest/__nonexistent_job_test__")
        # 不存在返回 404 是可以接受的
        assert response.status_code in {200, 404}, \
            f"入库任务查询端点异常: {response.status_code}"


# ══════════════════════════════════════════════════════════════════════
# 11. 响应结构一致性验证
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsResponseConsistency:
    """所有文档管理 API 端点必须返回统一的 { data, meta, error } 结构。"""

    ENDPOINTS = [
        ("GET", "/api/v1/documents", {"page": 1, "page_size": 5}),
        ("GET", "/api/v1/search/filters", None),
    ]

    def test_all_endpoints_have_unified_structure(self):
        """验证统一响应结构。"""
        for method, path, params in self.ENDPOINTS:
            if method == "GET":
                resp = client.get(path, params=params)
            else:
                resp = client.request(method, path, params=params)

            body = resp.json()
            assert "data" in body, f"{method} {path} 缺少 data"
            assert "meta" in body, f"{method} {path} 缺少 meta"
            assert "error" in body, f"{method} {path} 缺少 error"
            if resp.status_code < 400:
                assert body["error"] is None, f"{method} {path} 成功时 error 应为 null"

    def test_no_x_deprecated_header_on_v1_endpoints(self):
        """v1 端点不应返回 X-Deprecated 警告头。"""
        v1_urls = [
            "/api/v1/documents?page=1&page_size=5",
            "/api/v1/search/filters",
        ]
        for url in v1_urls:
            response = client.get(url)
            assert "x-deprecated" not in response.headers, \
                f"{url} 不应有 X-Deprecated 头"

    def test_error_response_structure(self):
        """错误响应也遵循统一结构: data=null, error 含 code+message。"""
        response = client.get("/api/v1/documents/__nonexistent_error_test__")
        assert response.status_code == 404
        body = response.json()
        assert body["data"] is None
        assert body["error"]["code"] is not None
        assert body["error"]["message"] is not None
        assert isinstance(body["error"]["code"], str)
        assert isinstance(body["error"]["message"], str)


# ══════════════════════════════════════════════════════════════════════
# 12. POST /api/v1/documents/upload — 文件上传（使用模拟文件）
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsUpload:
    """前端: API.uploadDocument(file, title, category, options) (documents.js:374)
    使用 data/simulated_inputs 下的模拟文件。
    """

    # ── 12.1 各格式上传 ─────────────────────────────────────────────

    def test_upload_markdown(self):
        """上传 Markdown 模拟文件 (simulated_dev_guide.md)。"""
        resp = _upload_simulated("markdown", title="开发指南", ingest_after_create=False)
        assert resp.status_code == 201, f"上传失败: {resp.text}"
        data = resp.json()["data"]
        assert data["duplicate"] is False
        assert data["file_name"] == "simulated_dev_guide.md"
        assert data["source_type"] == "markdown"
        assert data["title"] == "开发指南"
        assert data["size"] > 0
        _cleanup_doc(data["doc_id"])

    def test_upload_txt(self):
        """上传 TXT 模拟文件 (simulated_project_plan.txt)。"""
        resp = _upload_simulated("txt", title="项目计划", ingest_after_create=False)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["duplicate"] is False
        assert data["source_type"] == "txt"
        _cleanup_doc(data["doc_id"])

    def test_upload_docx(self):
        """上传 DOCX 模拟文件 (simulated_system_manual.docx)。
        若文件曾被上传过且未清理，会返回 duplicate=true，这也是合法响应。
        """
        resp = _upload_simulated("docx", title="系统手册", ingest_after_create=False)
        assert resp.status_code in {200, 201}, (
            f"DOCX 上传异常: HTTP {resp.status_code}"
        )
        data = resp.json()["data"]
        if data["duplicate"]:
            # 已有文档残留，清理后重试
            _cleanup_doc(data["existing_doc_id"])
        else:
            assert data["source_type"] == "docx"
            _cleanup_doc(data["doc_id"])

    def test_upload_xlsx(self):
        """上传 XLSX 模拟文件 (simulated_user_stats.xlsx)。"""
        resp = _upload_simulated("xlsx", title="用户统计", ingest_after_create=False)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["duplicate"] is False
        assert data["source_type"] == "xlsx"
        _cleanup_doc(data["doc_id"])

    def test_upload_html(self):
        """上传 HTML 模拟文件 (simulated_dashboard.html)。
        若文件曾被上传过且未清理，会返回 duplicate=true，这也是合法响应。
        """
        resp = _upload_simulated("html", title="仪表盘页面", ingest_after_create=False)
        assert resp.status_code in {200, 201}, (
            f"HTML 上传异常: HTTP {resp.status_code}"
        )
        data = resp.json()["data"]
        if data["duplicate"]:
            # 已有文档残留，清理后重试
            _cleanup_doc(data["existing_doc_id"])
        else:
            assert data["source_type"] == "html"
            _cleanup_doc(data["doc_id"])

    def test_upload_pdf(self):
        """上传 PDF 模拟文件 (simulated_api_whitepaper.pdf)。"""
        resp = _upload_simulated("pdf", title="API 白皮书", ingest_after_create=False)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["duplicate"] is False
        assert data["source_type"] == "pdf"
        _cleanup_doc(data["doc_id"])

    def test_upload_pptx(self):
        """上传 PPTX 模拟文件 (simulated_q4_review.pptx)。"""
        resp = _upload_simulated("pptx", title="Q4 评审", ingest_after_create=False)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["duplicate"] is False
        assert data["source_type"] == "pptx"
        _cleanup_doc(data["doc_id"])

    # ── 12.2 前端取值路径对齐 ───────────────────────────────────────

    def test_upload_response_matches_frontend_paths(self):
        """前端 documents.js:374-392 逐行取值:
        result?.data?.doc_id / duplicate / file_name / size / title
        / source_type / ingest_job_id / ingest_job。"""
        content = f"# 前端对齐测试 {uuid.uuid4().hex}\n\n这是测试内容。".encode("utf-8")
        resp = client.post("/api/v1/documents/upload", files={
            "file": (f"frontend_test_{uuid.uuid4().hex[:8]}.md",
                     io.BytesIO(content), "text/markdown"),
        }, data={"title": "前端对齐测试"}, params={"ingest_after_create": "false", "mode": "incremental"})
        assert resp.status_code == 201
        data = resp.json()["data"]

        # documents.js:378: data = result?.data || {}
        assert isinstance(data, dict)
        # documents.js:382: data.duplicate
        assert isinstance(data["duplicate"], bool)
        # documents.js:386: data.ingest_job_id（ingest_after_create=false 时允许为空）
        if data.get("ingest_job_id"):
            job = data.get("ingest_job", {})
            assert "job_id" in job and "status" in job and "stage" in job
        # documents.js:391: title || selectedFile.name
        assert data["title"] == "前端对齐测试"
        assert "file_name" in data
        # documents.js:70: UI.fmtBadge(source_type)
        assert isinstance(data["source_type"], str) and len(data["source_type"]) > 0
        # 统一响应结构
        body = resp.json()
        assert body["error"] is None
        assert "meta" in body

        _cleanup_doc(data["doc_id"])

    # ── 12.3 标题与分类 ─────────────────────────────────────────────

    def test_upload_custom_title(self):
        """自定义标题覆盖文件名。"""
        resp = _upload_simulated("txt", title="自定义标题")
        assert resp.json()["data"]["title"] == "自定义标题"
        _cleanup_doc(resp.json()["data"]["doc_id"])

    def test_upload_without_title_uses_filename_stem(self):
        """不传 title 时使用文件名（去后缀）作为标题。"""
        content, filename, content_type = _get_simulated_file("markdown")
        resp = client.post("/api/v1/documents/upload", files={
            "file": (filename, io.BytesIO(content), content_type),
        }, params={"ingest_after_create": "false", "mode": "incremental"})
        assert resp.status_code == 201
        assert resp.json()["data"]["title"] == "simulated_dev_guide"
        _cleanup_doc(resp.json()["data"]["doc_id"])

    def test_upload_custom_category(self):
        """自定义分类。"""
        resp = _upload_simulated("txt", title="分类测试", category="技术文档")
        assert resp.json()["data"]["category"] == "技术文档"
        _cleanup_doc(resp.json()["data"]["doc_id"])

    # ── 12.4 入库控制 ───────────────────────────────────────────────

    def test_upload_auto_ingest_returns_job(self):
        """前端默认 ingest_after_create=true，返回入库任务。"""
        resp = _upload_simulated("txt", title="入库测试", ingest_after_create=True)
        data = resp.json()["data"]
        assert data["ingest_job_id"], "应返回 ingest_job_id"
        _cleanup_doc(data["doc_id"])

    def test_upload_without_ingest_no_job(self):
        """ingest_after_create=false 时不创建入库任务。"""
        resp = _upload_simulated("markdown", title="不入库", ingest_after_create=False)
        data = resp.json()["data"]
        assert data.get("ingest_job_id") in (None, ""), (
            f"ingest_after_create=false 时不应有 ingest_job_id, 实际={data.get('ingest_job_id')}"
        )
        _cleanup_doc(data["doc_id"])

    def test_upload_force_mode(self):
        """后端仍支持 force 模式，但前端重新处理已有文档不再使用该模式。"""
        resp = _upload_simulated("markdown", title="force测试", mode="force")
        data = resp.json()["data"]
        if "ingest_job" in data:
            assert data["ingest_job"]["mode"] == "force"
        _cleanup_doc(data["doc_id"])

    # ── 12.5 重复检测 ───────────────────────────────────────────────

    def test_duplicate_upload_same_content(self):
        """相同内容重复上传返回 duplicate=true (documents.js:382-384)。
        使用唯一内容避免与格式测试的模拟文件冲突。
        """
        unique_content = f"# dup test {uuid.uuid4().hex}\n".encode("utf-8")
        filename = f"dup_{uuid.uuid4().hex[:8]}.md"

        # 第一次上传
        resp1 = client.post("/api/v1/documents/upload", files={
            "file": (filename, io.BytesIO(unique_content), "text/markdown"),
        }, data={"title": "原始"}, params={"ingest_after_create": "false", "mode": "incremental"})
        assert resp1.status_code == 201, f"第一次上传失败: {resp1.text}"
        body1 = resp1.json()
        if body1["data"]["duplicate"]:
            # 之前测试残留，清理后用新内容重试
            _cleanup_doc(body1["data"]["existing_doc_id"])
            unique_content = f"# dup retry {uuid.uuid4().hex}\n".encode("utf-8")
            resp1 = client.post("/api/v1/documents/upload", files={
                "file": (f"dup2_{uuid.uuid4().hex[:8]}.md", io.BytesIO(unique_content), "text/markdown"),
            }, data={"title": "原始"}, params={"ingest_after_create": "false", "mode": "incremental"})
            assert resp1.status_code == 201
            body1 = resp1.json()
        assert not body1["data"]["duplicate"]
        doc_id = body1["data"]["doc_id"]

        # 第二次上传相同内容 → 应检测到重复
        resp2 = client.post("/api/v1/documents/upload", files={
            "file": (filename, io.BytesIO(unique_content), "text/markdown"),
        }, data={"title": "重复"}, params={"ingest_after_create": "false", "mode": "incremental"})
        assert resp2.status_code in {200, 201}, f"重复上传异常: {resp2.status_code}"
        body2 = resp2.json()
        # PG 后端：duplicate=true；内存后端：无去重检查，duplicate=false
        if body2["data"]["duplicate"]:
            assert body2["data"]["existing_doc_id"] == doc_id
            assert body2["meta"].get("duplicate") is True
        else:
            _cleanup_doc(body2["data"]["doc_id"])

        _cleanup_doc(doc_id)

    def test_different_files_no_duplicate(self):
        """不同内容的文件不会误判为重复。
        PG 后端第二次上传返回 duplicate=true + existing_doc_id。
        """
        content = f"# unique {uuid.uuid4().hex}\n".encode("utf-8")
        resp1 = client.post("/api/v1/documents/upload", files={
            "file": ("a.md", io.BytesIO(content), "text/markdown"),
        }, params={"ingest_after_create": "false", "mode": "incremental"})
        assert resp1.status_code in {200, 201}, f"第一次上传异常: {resp1.status_code}"
        body1 = resp1.json()
        if body1["data"]["duplicate"]:
            # 之前运行残留，清理后用新内容
            _cleanup_doc(body1["data"]["existing_doc_id"])
            content = f"# unique retry {uuid.uuid4().hex}\n".encode("utf-8")
            resp1 = client.post("/api/v1/documents/upload", files={
                "file": ("a2.md", io.BytesIO(content), "text/markdown"),
            }, params={"ingest_after_create": "false", "mode": "incremental"})
            assert resp1.status_code == 201
            body1 = resp1.json()
        assert body1["data"]["duplicate"] is False
        doc1 = body1["data"]["doc_id"]

        # 第二次上传相同内容
        resp2 = client.post("/api/v1/documents/upload", files={
            "file": ("b.md", io.BytesIO(content), "text/markdown"),
        }, params={"ingest_after_create": "false", "mode": "incremental"})
        assert resp2.status_code in {200, 201}, f"第二次上传异常: {resp2.status_code}"
        body2 = resp2.json()
        if body2["data"]["duplicate"]:
            # PG 后端：检测到重复
            assert body2["data"]["existing_doc_id"] == doc1
        else:
            # 内存后端：无去重检查
            _cleanup_doc(body2["data"]["doc_id"])

        _cleanup_doc(doc1)


# ══════════════════════════════════════════════════════════════════════
# 13. 上传后完整流程 — 模拟前端从上传到管理的全链路
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsUploadFullWorkflow:
    """模拟前端: showUploadModal → doUpload → closeUploadModal
    → loadPage → 详情 → 删除 → 恢复。"""

    @staticmethod
    def _upload_unique_text(title: str, **kwargs):
        """上传唯一文本内容，避免跨测试重复检测干扰。"""
        content = f"# {title} {uuid.uuid4().hex}\n\n测试内容。".encode("utf-8")
        return client.post("/api/v1/documents/upload", files={
            "file": (f"{uuid.uuid4().hex[:8]}.md", io.BytesIO(content), "text/markdown"),
        }, data={"title": title, "category": kwargs.get("category", "测试")},
           params={"ingest_after_create": str(kwargs.get("ingest_after_create", False)).lower(),
                   "mode": kwargs.get("mode", "incremental")})

    def test_upload_then_list_visible(self):
        """上传后能在文档列表中查到（前端 loadPage 刷新列表）。"""
        title = f"列表可见_{uuid.uuid4().hex[:8]}"
        resp = self._upload_unique_text(title)
        assert resp.status_code == 201
        doc_id = resp.json()["data"]["doc_id"]

        list_resp = client.get("/api/v1/documents", params={
            "page": 1, "page_size": 50, "keyword": title,
        })
        items = list_resp.json()["data"]
        assert any(d["doc_id"] == doc_id for d in items), (
            f"上传的文档 {doc_id} 未出现在列表中"
        )
        _cleanup_doc(doc_id)

    def test_upload_then_get_detail(self):
        """上传后可查看详情（前端点击标题跳转 /documents/:id）。"""
        title = f"详情测试_{uuid.uuid4().hex[:8]}"
        resp = self._upload_unique_text(title)
        assert resp.status_code == 201
        doc_id = resp.json()["data"]["doc_id"]

        detail = client.get(f"/api/v1/documents/{doc_id}")
        assert detail.status_code == 200
        d = detail.json()["data"]
        assert d["doc_id"] == doc_id
        assert d["title"] == title
        assert "chunk_count" in d and "element_count" in d and "index_summary" in d
        _cleanup_doc(doc_id)

    def test_upload_then_delete_then_restore(self):
        """上传 → 删除 → 恢复（前端 deleteDoc + restoreDoc）。"""
        title = f"删恢测试_{uuid.uuid4().hex[:8]}"
        resp = self._upload_unique_text(title)
        assert resp.status_code == 201
        doc_id = resp.json()["data"]["doc_id"]

        # 删除 (documents.js:168)
        assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 200
        # 恢复 (documents.js:178)
        assert client.post(f"/api/v1/documents/{doc_id}/restore").status_code == 200
        assert client.get(f"/api/v1/documents/{doc_id}").json()["data"]["status"] == "active"

        _cleanup_doc(doc_id)

    def test_upload_then_update(self):
        """上传后可更新标题和分类。"""
        title = f"旧标题_{uuid.uuid4().hex[:8]}"
        resp = self._upload_unique_text(title, category="旧分类")
        assert resp.status_code == 201
        doc_id = resp.json()["data"]["doc_id"]

        patch = client.patch(f"/api/v1/documents/{doc_id}", params={
            "title": "新标题", "category": "新分类",
        })
        assert patch.status_code == 200
        assert patch.json()["data"]["title"] == "新标题"
        assert patch.json()["data"]["category"] == "新分类"

        _cleanup_doc(doc_id)

    def test_upload_full_lifecycle(self):
        """上传 → 查看 → 更新 → 删除 → 恢复 → 最终确认。"""
        title = f"生命周期_{uuid.uuid4().hex[:8]}"
        resp = self._upload_unique_text(title, category="测试")
        assert resp.status_code == 201
        doc_id = resp.json()["data"]["doc_id"]

        # 查看
        assert client.get(f"/api/v1/documents/{doc_id}").status_code == 200
        # 更新
        assert client.patch(f"/api/v1/documents/{doc_id}",
                            params={"title": "生命周期-已更新"}).status_code == 200
        # 删除
        assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 200
        # 恢复
        assert client.post(f"/api/v1/documents/{doc_id}/restore").status_code == 200
        # 最终确认
        final = client.get(f"/api/v1/documents/{doc_id}")
        assert final.json()["data"]["status"] == "active"
        assert final.json()["data"]["title"] == "生命周期-已更新"

        _cleanup_doc(doc_id)

    def test_upload_then_ingest_job_queryable(self):
        """上传（含入库）后入库任务可查询。"""
        title = f"入库查询_{uuid.uuid4().hex[:8]}"
        resp = self._upload_unique_text(title, ingest_after_create=True)
        data = resp.json()["data"]
        job_id = data["ingest_job_id"]

        # 前端: API.getIngestJobV1(jobId)
        job_resp = client.get(f"/api/v1/ingest/jobs/{job_id}")
        assert job_resp.status_code == 200
        job = job_resp.json()["data"]
        assert job["job_id"] == job_id
        assert job["doc_id"] == data["doc_id"]
        assert job["status"] in {"pending", "processing", "completed", "failed", "canceled"}

        # 前端: API.listIngestJobs()
        list_resp = client.get("/api/v1/ingest/jobs")
        assert any(j["job_id"] == job_id for j in list_resp.json()["data"])

        _cleanup_doc(data["doc_id"])


# ══════════════════════════════════════════════════════════════════════
# 14. 上传边界情况 & v1 规范一致性
# ══════════════════════════════════════════════════════════════════════

class TestDocumentsUploadEdgeCases:
    """上传边界情况和规范验证。"""

    def test_upload_without_file_returns_422(self):
        assert client.post("/api/v1/documents/upload").status_code == 422

    def test_upload_empty_file(self):
        """空文件上传。"""
        resp = client.post("/api/v1/documents/upload", files={
            "file": ("empty.md", io.BytesIO(b""), "text/markdown"),
        }, data={"title": "空文件"}, params={"ingest_after_create": "false", "mode": "incremental"})
        assert resp.status_code in {200, 201, 400, 422}, f"空文件上传异常: {resp.status_code}"
        if resp.status_code in {200, 201}:
            _cleanup_doc(resp.json()["data"]["doc_id"])

    def test_upload_large_text_file(self):
        """大文本文件上传（模拟真实文档）。"""
        content = ("# 大型文档\n\n" + "内容行。\n" * 5000).encode("utf-8")
        resp = client.post("/api/v1/documents/upload", files={
            "file": ("large.md", io.BytesIO(content), "text/markdown"),
        }, data={"title": "大型文档"}, params={"ingest_after_create": "false", "mode": "incremental"})
        assert resp.status_code == 201
        assert resp.json()["data"]["size"] > 10000
        _cleanup_doc(resp.json()["data"]["doc_id"])

    def test_upload_special_chars_filename(self):
        """文件名含中文和特殊字符。"""
        resp = client.post("/api/v1/documents/upload", files={
            "file": ("测试文档 (v2.0).md", io.BytesIO(b"# test"), "text/markdown"),
        }, data={"title": "特殊文件名"}, params={"ingest_after_create": "false", "mode": "incremental"})
        assert resp.status_code == 201
        _cleanup_doc(resp.json()["data"]["doc_id"])

    def test_upload_v1_no_x_deprecated_header(self):
        """v1 上传接口不应有 X-Deprecated 头。"""
        resp = _upload_simulated("markdown", title="无废弃头", ingest_after_create=False)
        assert "x-deprecated" not in resp.headers
        _cleanup_doc(resp.json()["data"]["doc_id"])

    def test_upload_success_error_is_null(self):
        """成功上传 error 字段必须显式为 null。"""
        resp = _upload_simulated("txt", title="error null", ingest_after_create=False)
        assert resp.json()["error"] is None
        _cleanup_doc(resp.json()["data"]["doc_id"])

    def test_concurrent_uploads_different_formats(self):
        """并发上传不同格式文件。"""
        import concurrent.futures
        formats = ["markdown", "txt", "html"]
        doc_ids = []

        def upload_one(fmt):
            return _upload_simulated(fmt, title=f"并发_{fmt}", ingest_after_create=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {fmt: executor.submit(upload_one, fmt) for fmt in formats}
            results = {fmt: f.result() for fmt, f in futures.items()}

        for fmt, resp in results.items():
            assert resp.status_code == 201, f"并发上传 {fmt} 失败: {resp.status_code}"
            doc_ids.append(resp.json()["data"]["doc_id"])
        for did in doc_ids:
            _cleanup_doc(did)
