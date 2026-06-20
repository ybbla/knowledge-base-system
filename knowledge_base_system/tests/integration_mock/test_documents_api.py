"""文档管理页面联调测试（Mock LLM 版）。

与 integration/test_documents_api.py 完全相同，
LLM 调用（语义提取 + 块嵌入）由 conftest.py mock。

以下测试类/方法已覆盖以适配已删除的 PATCH 端点和 ingest 端点：
  - TestDocumentsUpdate（整个类删除，PATCH 端点已删除）
  - TestDocumentsIngest（整个类删除，POST /{doc_id}/ingest 端点已删除）
  - 多个测试方法已覆盖以移除对 ingest_job / pending 状态 / PATCH 更新的依赖
"""

from __future__ import annotations

import uuid

from tests.integration.test_documents_api import (
    client,
    _SIMULATED_FILES,
    _CONTENT_TYPES,
    _create_test_doc,
    _cleanup_doc,
    _get_simulated_file,
    _upload_simulated,
    TestDocumentsSearchFilters as _OrigSearchFilters,
    TestDocumentsList as _OrigList,
    TestDocumentsCreate as _OrigCreate,
    TestDocumentsDetail as _OrigDetail,
    TestDocumentsElements as _OrigElements,
    TestDocumentsDelete as _OrigDelete,
    TestDocumentsRestore as _OrigRestore,
    TestDocumentsFullCRUDFlow as _OrigFullCRUDFlow,
    TestLegacyUploadAPI as _OrigLegacyUpload,
    TestDocumentsResponseConsistency as _OrigResponseConsistency,
    TestDocumentsUpload as _OrigUpload,
    TestDocumentsUploadFullWorkflow as _OrigUploadFullWorkflow,
    TestDocumentsUploadEdgeCases as _OrigUploadEdgeCases,
)


class TestDocumentsSearchFilters(_OrigSearchFilters):
    pass


class TestDocumentsList(_OrigList):
    """覆盖：移除对 pending 状态的测试。"""

    def test_list_with_status_filter(self):
        """前端状态下拉框传 status 参数（不包含已删除的 pending 状态）。"""
        for status_val in ["active", "processing", "failed", "deleted"]:
            response = client.get("/api/v1/documents", params={
                "page": 1, "page_size": 5, "status": status_val,
            })
            assert response.status_code == 200, f"status={status_val} 请求失败"
            body = response.json()
            assert body["error"] is None


class TestDocumentsCreate(_OrigCreate):
    """覆盖：创建后状态不再包含 pending。"""

    def test_create_returns_201_with_doc_data(self):
        """创建文档返回 201 和文档数据（状态仅为 active，pending 已删除）。"""
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
        assert body["data"]["status"] == "active"
        assert "doc_id" in body["data"]

        _cleanup_doc(body["data"]["doc_id"])


class TestDocumentsDetail(_OrigDetail):
    pass


class TestDocumentsElements(_OrigElements):
    pass


class TestDocumentsDelete(_OrigDelete):
    pass


class TestDocumentsRestore(_OrigRestore):
    pass


class TestDocumentsFullCRUDFlow(_OrigFullCRUDFlow):
    """覆盖：移除 PATCH 更新步骤和 pending 状态筛选。"""

    def test_full_lifecycle_create_get_update_delete_restore(self):
        """完整生命周期: 创建 → 查看 → 删除 → 恢复 → 查看（无更新步骤，PATCH 已删除）。"""
        # ── 步骤 1: 创建文档 ──
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

        # ── 步骤 3: 软删除 ──
        delete_resp = client.delete(f"/api/v1/documents/{doc_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["data"]["status"] == "deleted"

        # ── 步骤 4: 恢复 ──
        restore_resp = client.post(f"/api/v1/documents/{doc_id}/restore")
        assert restore_resp.status_code == 200
        assert restore_resp.json()["data"]["status"] == "active"

        # ── 步骤 5: 再次查看确认状态 ──
        final_resp = client.get(f"/api/v1/documents/{doc_id}")
        assert final_resp.status_code == 200
        assert final_resp.json()["data"]["status"] == "active"
        assert final_resp.json()["data"]["title"] == "完整流程测试文档"

        # 清理
        _cleanup_doc(doc_id)

    def test_frontend_status_filter_values_all_work(self):
        """前端状态下拉框选项都能正常请求（不包含已删除的 pending 状态）。"""
        status_values = ["", "active", "processing", "failed", "deleted"]
        for sv in status_values:
            params = {"page": 1, "page_size": 5}
            if sv:
                params["status"] = sv
            response = client.get("/api/v1/documents", params=params)
            assert response.status_code == 200, f"status={sv} 请求失败: {response.text}"
            body = response.json()
            assert body["error"] is None


class TestLegacyUploadAPI(_OrigLegacyUpload):
    pass


class TestDocumentsResponseConsistency(_OrigResponseConsistency):
    pass


class TestDocumentsUpload(_OrigUpload):
    """覆盖：不期望返回 ingest_job_id。"""

    def test_upload_auto_ingest_returns_job(self):
        """上传后只需验证返回成功且有 doc_id（不再检查 ingest_job_id）。"""
        resp = _upload_simulated("txt", title="上传测试", ingest_after_create=False)
        assert resp.status_code in (200, 201), f"上传失败: {resp.text}"
        data = resp.json()["data"]
        assert "doc_id" in data, "应返回 doc_id"
        _cleanup_doc(data["doc_id"])


class TestDocumentsUploadFullWorkflow(_OrigUploadFullWorkflow):
    """覆盖：移除 PATCH 更新和 ingest_job 查询相关测试。"""

    def test_upload_then_update(self):
        """上传后验证文档存在（不再使用已删除的 PATCH 端点）。"""
        title = f"上传验证_{uuid.uuid4().hex[:8]}"
        resp = self._upload_unique_text(title, category="测试")
        assert resp.status_code == 201
        doc_id = resp.json()["data"]["doc_id"]

        # 验证文档存在且信息正确
        detail = client.get(f"/api/v1/documents/{doc_id}")
        assert detail.status_code == 200
        d = detail.json()["data"]
        assert d["doc_id"] == doc_id
        assert d["title"] == title
        assert d["category"] == "测试"

        _cleanup_doc(doc_id)

    def test_upload_then_ingest_job_queryable(self):
        """上传后验证文档存在（不再检查 ingest_job）。"""
        title = f"上传存在_{uuid.uuid4().hex[:8]}"
        resp = self._upload_unique_text(title, ingest_after_create=False)
        assert resp.status_code == 201
        data = resp.json()["data"]
        doc_id = data["doc_id"]

        # 验证文档存在
        detail = client.get(f"/api/v1/documents/{doc_id}")
        assert detail.status_code == 200
        assert detail.json()["data"]["doc_id"] == doc_id
        assert detail.json()["data"]["title"] == title

        _cleanup_doc(doc_id)


class TestDocumentsUploadEdgeCases(_OrigUploadEdgeCases):
    pass
