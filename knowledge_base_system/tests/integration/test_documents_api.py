"""文档管理页面集成测试 — 验证前端 documents.js 调用的所有 API 端点。

前端 documents.js 调用链（已全面迁移至 v1）：
  1. GET  /api/v1/search/filters                        → 加载分类选项 (renderList L20)
  2. GET  /api/v1/documents?page=&page_size=15&...       → 分页文档列表 (loadPage L39)
  3. GET  /api/v1/documents/{doc_id}                    → 文档详情 (点击详情链接)
  4. DELETE /api/v1/documents/{doc_id}                   → 软删除 (deleteDoc L168)
  5. POST /api/v1/documents/{doc_id}/restore            → 恢复 (restoreDoc L178)
  6. POST /api/v1/documents/{doc_id}/ingest?mode=force  → 重新入库 (ingestDocument L188)
  7. POST /api/v1/documents                             → 创建文档 (后端支持)
  8. PATCH /api/v1/documents/{doc_id}                   → 更新文档 (后端支持)
  9. POST /api/v1/documents/upload                      → 文件上传 (uploadDocument L374)
  10. POST /api/v1/documents/{doc_id}/ingest             → 触发入库 (ingestion.js submitNewJob L299)

旧版 /upload、/ingest、/ingest/{job_id} 已标记废弃，保留兼容期内可用。

本测试使用 TestClient 对真实 FastAPI app 发起请求，
验证响应结构完全匹配前端期望，确保前后端联调可用。
"""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


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
    """前端: API.ingestDocument(docId, 'force') (documents.js:188)"""

    def test_ingest_returns_job_id(self):
        """触发入库返回 job_id (documents.js:188)。"""
        doc = _create_test_doc("入库测试文档")
        doc_id = doc["doc_id"]

        response = client.post(
            f"/api/v1/documents/{doc_id}/ingest",
            params={"mode": "force"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "job_id" in body["data"]
        assert body["data"]["doc_id"] == doc_id
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
    renderList → loadPage → 删除 → 恢复 → 重新入库
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
