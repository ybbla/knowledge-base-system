"""仪表板页面前后端联调测试 — 验证前端 dashboard.js 调用的 4 个接口。

前端 dashboard.js 调用链：
  1. GET /api/v1/health/ready      → readyRes?.data?.status === 'ok'
  2. GET /api/v1/health/dependencies → depsRes?.data?.dependencies?.backend?.type
  3. GET /api/v1/documents?page=1&page_size=1 → docsRes?.meta?.total
  4. GET /api/v1/chunks?page=1&page_size=1    → chunksRes?.meta?.total

本测试使用 TestClient 对真实 FastAPI app 发起请求，
验证响应结构完全匹配前端期望，确保前后端联调可用。
"""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


# ══════════════════════════════════════════════════════════════════════
# 1. GET /api/v1/health/ready — 就绪检查
# ══════════════════════════════════════════════════════════════════════

class TestDashboardHealthReady:
    """前端: readyRes?.data?.status === 'ok'"""

    def test_ready_returns_unified_api_response_structure(self):
        """就绪接口返回统一的 { data, meta, error } 结构。"""
        response = client.get("/api/v1/health/ready")

        assert response.status_code in {200, 503}
        body = response.json()
        assert isinstance(body, dict)
        assert "data" in body
        assert "meta" in body
        assert "error" in body
        if response.status_code == 200:
            assert body["error"] is None

    def test_ready_data_contains_status_field(self):
        """前端读取 data.status 判断是否在线。"""
        response = client.get("/api/v1/health/ready")
        body = response.json()
        assert "status" in body["data"]
        assert body["data"]["status"] in {"ok", "degraded"}

    def test_ready_data_contains_checks_dict(self):
        """data.checks 包含各依赖状态。"""
        response = client.get("/api/v1/health/ready")
        body = response.json()
        assert "checks" in body["data"]
        assert isinstance(body["data"]["checks"], dict)

    def test_ready_meta_contains_backend(self):
        """meta.backend 标识后端类型。"""
        response = client.get("/api/v1/health/ready")
        body = response.json()
        assert "backend" in body["meta"]

    def test_ready_memory_backend_all_ok(self):
        """默认 memory 后端：所有组件状态为 ok 或 not_configured，overall=ok。"""
        response = client.get("/api/v1/health/ready")
        body = response.json()

        assert response.status_code == 200
        assert body["data"]["status"] == "ok"

        for key, check in body["data"]["checks"].items():
            assert check["status"] in {"ok", "not_configured"}, (
                f"{key} 状态异常: {check.get('status')}"
            )


# ══════════════════════════════════════════════════════════════════════
# 2. GET /api/v1/health/dependencies — 依赖状态详情
# ══════════════════════════════════════════════════════════════════════

class TestDashboardHealthDependencies:
    """前端: depsRes?.data?.dependencies?.backend?.type"""

    def test_dependencies_returns_unified_structure(self):
        """依赖接口返回统一的 { data, meta, error } 结构。"""
        response = client.get("/api/v1/health/dependencies")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_dependencies_contains_required_keys(self):
        """data.dependencies 包含前端展示所需的各依赖项。"""
        response = client.get("/api/v1/health/dependencies")
        deps = response.json()["data"]["dependencies"]

        required = ["backend", "chunk_store", "vector_index", "bm25_index"]
        for key in required:
            assert key in deps, f"缺少依赖项: {key}"

    def test_dependencies_backend_has_type_field(self):
        """前端用 dependencies.backend.type 显示后端引擎名称。"""
        response = client.get("/api/v1/health/dependencies")
        backend = response.json()["data"]["dependencies"]["backend"]

        assert "status" in backend
        assert "type" in backend
        assert backend["status"] == "ok"
        # 兼容 memory 和 postgres 两种后端
        assert backend["type"] in {"memory", "postgres"}

    def test_dependencies_every_dep_has_status(self):
        """每个依赖项都有 status 字段，前端据此渲染状态标识。"""
        response = client.get("/api/v1/health/dependencies")
        deps = response.json()["data"]["dependencies"]

        for key, dep in deps.items():
            assert "status" in dep, f"{key} 缺少 status"
            assert dep["status"] in {"ok", "error", "not_configured"}, (
                f"{key} status 异常: {dep['status']}"
            )

    def test_dependencies_no_sensitive_info(self):
        """依赖响应不含密钥、密码等敏感信息。"""
        response = client.get("/api/v1/health/dependencies")
        body_str = str(response.json()).lower()
        for secret in ["password", "secret", "api_key", "token"]:
            assert secret not in body_str, f"泄露敏感信息: {secret}"

    def test_dependencies_meta_has_service_info(self):
        """meta 包含服务版本标识。"""
        response = client.get("/api/v1/health/dependencies")
        body = response.json()
        assert "service" in body["meta"]


# ══════════════════════════════════════════════════════════════════════
# 3. GET /api/v1/documents — 文档列表（仪表盘仅取 meta.total）
# ══════════════════════════════════════════════════════════════════════

class TestDashboardDocumentList:
    """前端: docsRes?.meta?.total"""

    def test_list_documents_returns_paginated_structure(self):
        """文档列表返回 { data: [...], meta: { total, page, page_size }, error: null }。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_list_documents_meta_has_total(self):
        """前端通过 meta.total 获取文档总数。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        body = response.json()

        assert "total" in body["meta"]
        assert isinstance(body["meta"]["total"], int)
        assert body["meta"]["total"] >= 0

    def test_list_documents_meta_pagination_fields(self):
        """meta 包含完整分页信息。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        body = response.json()

        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 1
        assert "total_pages" in body["meta"]

    def test_list_documents_data_is_array(self):
        """data 是文档条目数组。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        body = response.json()

        assert isinstance(body["data"], list)
        assert len(body["data"]) <= 1  # page_size=1

    def test_list_documents_default_params(self):
        """不带参数时使用默认分页（page=1, page_size=20）。"""
        response = client.get("/api/v1/documents")
        body = response.json()

        assert response.status_code == 200
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 20


# ══════════════════════════════════════════════════════════════════════
# 4. GET /api/v1/chunks — 知识块列表（仪表盘仅取 meta.total）
# ══════════════════════════════════════════════════════════════════════

class TestDashboardChunkList:
    """前端: chunksRes?.meta?.total"""

    def test_list_chunks_returns_paginated_structure(self):
        """知识块列表返回 { data: [...], meta: { total, page, page_size }, error: null }。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_list_chunks_meta_has_total(self):
        """前端通过 meta.total 获取知识块总数。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        body = response.json()

        assert "total" in body["meta"]
        assert isinstance(body["meta"]["total"], int)
        assert body["meta"]["total"] >= 0

    def test_list_chunks_meta_pagination_fields(self):
        """meta 包含完整分页信息。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        body = response.json()

        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 1
        assert "total_pages" in body["meta"]

    def test_list_chunks_data_is_array(self):
        """data 是知识块条目数组。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        body = response.json()

        assert isinstance(body["data"], list)
        assert len(body["data"]) <= 1

    def test_list_chunks_default_params(self):
        """不带参数时使用默认分页（page=1, page_size=20）。"""
        response = client.get("/api/v1/chunks")
        body = response.json()

        assert response.status_code == 200
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 20


# ══════════════════════════════════════════════════════════════════════
# 5. 综合联调测试 — 模拟前端 dashboard.render() 完整调用流程
# ══════════════════════════════════════════════════════════════════════

class TestDashboardFullFlow:
    """模拟前端 dashboard.js render() 的 4 个 API 调用序列。"""

    def test_full_dashboard_flow_all_succeed(self):
        """4 个 API 全部成功，响应结构匹配前端期望。"""

        # ── 步骤 1: Promise.all([healthReady(), healthDependencies()]) ──
        ready = client.get("/api/v1/health/ready")
        deps = client.get("/api/v1/health/dependencies")

        # 前端: healthOk = readyRes?.data?.status === 'ok'
        assert ready.json()["data"]["status"] == "ok"

        # 前端: backendType = depsRes?.data?.dependencies?.backend?.type || '—'
        backend_type = deps.json()["data"]["dependencies"]["backend"]["type"]
        assert isinstance(backend_type, str) and len(backend_type) > 0

        # 前端: depStatuses = depsRes?.data?.dependencies || {}
        dep_statuses = deps.json()["data"]["dependencies"]
        assert isinstance(dep_statuses, dict) and len(dep_statuses) > 0

        # ── 步骤 2: API.listDocuments({ page: 1, page_size: 1 }) ──
        docs = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        # 前端: docCount = docsRes?.meta?.total || 0
        assert isinstance(docs.json()["meta"]["total"], int)

        # ── 步骤 3: API.listChunks({ page: 1, page_size: 1 }) ──
        chunks = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        # 前端: chunkCount = chunksRes?.meta?.total || 0
        assert isinstance(chunks.json()["meta"]["total"], int)

    def test_dashboard_handles_any_data_volume(self):
        """仪表板无论数据量多少（包括空库），响应结构始终正确。"""
        docs = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        chunks = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})

        # 核心：meta.total 必须存在且为有效整数
        assert isinstance(docs.json()["meta"]["total"], int)
        assert isinstance(chunks.json()["meta"]["total"], int)
        # data 是数组，且不超过 page_size
        assert isinstance(docs.json()["data"], list)
        assert len(docs.json()["data"]) <= 1
        assert isinstance(chunks.json()["data"], list)
        assert len(chunks.json()["data"]) <= 1

    def test_v1_endpoints_no_x_deprecated_header(self):
        """仪表板使用的 v1 接口不应返回 X-Deprecated 警告头。"""
        urls = [
            "/api/v1/health/ready",
            "/api/v1/health/dependencies",
            "/api/v1/documents?page=1&page_size=1",
            "/api/v1/chunks?page=1&page_size=1",
        ]
        for url in urls:
            response = client.get(url)
            assert "x-deprecated" not in response.headers, (
                f"{url} 不应有 X-Deprecated 头"
            )
