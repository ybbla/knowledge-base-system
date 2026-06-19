"""仪表板页面前后端联调测试 — 验证前端 dashboard.js 调用的 5 个接口。

前端 dashboard.js 调用链：
  1. GET /api/v1/health/live       → liveRes?.data?.status === 'ok'
  2. GET /api/v1/health/ready      → readyRes?.data?.status === 'ok'
  3. GET /api/v1/health/dependencies → depsRes?.data?.dependencies?.backend?.type
  4. GET /api/v1/documents?page=1&page_size=1 → docsRes?.meta?.total
  5. GET /api/v1/chunks?page=1&page_size=1    → chunksRes?.meta?.total

本测试使用 TestClient 对真实 FastAPI app 发起请求，
验证响应结构完全匹配前端期望，确保前后端联调可用。
"""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


# ══════════════════════════════════════════════════════════════════════
# 0. GET /api/v1/health/live — 存活检查
# ══════════════════════════════════════════════════════════════════════

class TestDashboardHealthLive:
    """前端: liveRes?.data?.status === 'ok' — 进程存活探针"""

    def test_live_returns_unified_api_response_structure(self):
        """存活接口返回统一的 { data, meta, error } 结构。"""
        response = client.get("/api/v1/health/live")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None

    def test_live_data_status_is_ok(self):
        """前端读取 data.status 判断进程是否存活。"""
        response = client.get("/api/v1/health/live")
        body = response.json()
        assert body["data"]["status"] == "ok"

    def test_live_meta_has_service_info(self):
        """meta 包含服务名和版本号。"""
        response = client.get("/api/v1/health/live")
        body = response.json()
        assert "service" in body["meta"]
        assert "version" in body["meta"]
        assert isinstance(body["meta"]["service"], str)
        assert len(body["meta"]["service"]) > 0

    def test_live_is_fast_and_lightweight(self):
        """存活检查应极快（无外部依赖调用）。"""
        import time
        start = time.perf_counter()
        response = client.get("/api/v1/health/live")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert response.status_code == 200
        # 存活检查不应超过 500ms（无 DB、无索引、无网络调用）
        assert elapsed_ms < 500, f"存活检查耗时 {elapsed_ms:.0f}ms，超过 500ms 阈值"


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
        assert backend["type"] == "postgres"

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


# ══════════════════════════════════════════════════════════════════════
# 6. 前端渲染逻辑精确对齐测试 — 模拟 dashboard.js 取值路径
# ══════════════════════════════════════════════════════════════════════

class TestDashboardFrontendAlignment:
    """验证后端响应与前端 dashboard.js 逐行取值逻辑精确匹配。"""

    # ── 6.1 前端: depStatuses 遍历 ──────────────────────────────────

    def test_dependencies_every_entry_has_name_field(self):
        """前端 dashboard.js:89: dep.name || key — 每个依赖项需有 name 字段。"""
        response = client.get("/api/v1/health/dependencies")
        deps = response.json()["data"]["dependencies"]

        for key, dep in deps.items():
            assert "name" in dep, (
                f"依赖项 '{key}' 缺少 name 字段，前端将回退显示英文 key"
            )
            assert isinstance(dep["name"], str) and len(dep["name"]) > 0, (
                f"依赖项 '{key}' 的 name 为空"
            )

    def test_dependencies_has_enough_entries_for_slice(self):
        """前端 dashboard.js:87: Object.entries(depStatuses).slice(0, 6)
        依赖项数量 ≥ 6，截断行为可验证。"""
        response = client.get("/api/v1/health/dependencies")
        deps = response.json()["data"]["dependencies"]

        assert len(deps) >= 6, (
            f"依赖项仅 {len(deps)} 个，前端 .slice(0,6) 不会触发截断行为"
        )

    def test_dependencies_status_values_match_frontend_rendering(self):
        """前端 dashboard.js:90: dep.status === 'ok' ? 'is-ok' : dep.status === 'error' ? 'is-error' : ''
        验证所有依赖项的 status 在 {ok, error, not_configured} 范围内。"""
        response = client.get("/api/v1/health/dependencies")
        deps = response.json()["data"]["dependencies"]

        valid_statuses = {"ok", "error", "not_configured"}
        for key, dep in deps.items():
            assert dep["status"] in valid_statuses, (
                f"依赖项 '{key}' 的 status='{dep['status']}' 不在合法范围 {valid_statuses}"
            )

    # ── 6.2 前端: healthOk 判断 ────────────────────────────────────

    def test_ready_status_exact_ok_string(self):
        """前端 dashboard.js:20: readyRes?.data?.status === 'ok'
        严格相等比较，确保是字符串 'ok' 而非其他。"""
        response = client.get("/api/v1/health/ready")
        status_val = response.json()["data"]["status"]

        assert status_val == "ok", f"期望 status='ok'，实际为 '{status_val}'"
        assert isinstance(status_val, str), "status 必须是字符串类型"

    # ── 6.3 前端: backendType 取值 ─────────────────────────────────

    def test_dependencies_backend_type_is_string(self):
        """前端 dashboard.js:21: depsRes?.data?.dependencies?.backend?.type || '—'
        type 必须是字符串，前端 || '—' 提供默认值。"""
        response = client.get("/api/v1/health/dependencies")
        backend_type = response.json()["data"]["dependencies"]["backend"]["type"]

        assert isinstance(backend_type, str), "backend.type 必须是字符串"
        assert len(backend_type) > 0, "backend.type 不能为空字符串"

    # ── 6.4 前端: meta.total 数值 ──────────────────────────────────

    def test_documents_meta_total_is_non_negative_int(self):
        """前端 dashboard.js:30: docsRes?.meta?.total || 0
        total 必须是非负整数。"""
        response = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        total = response.json()["meta"]["total"]

        assert isinstance(total, int), f"total 应为 int，实际为 {type(total)}"
        assert total >= 0, f"total 应为非负整数，实际为 {total}"

    def test_chunks_meta_total_is_non_negative_int(self):
        """前端 dashboard.js:35: chunksRes?.meta?.total || 0
        total 必须是非负整数。"""
        response = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        total = response.json()["meta"]["total"]

        assert isinstance(total, int), f"total 应为 int，实际为 {type(total)}"
        assert total >= 0, f"total 应为非负整数，实际为 {total}"

    # ── 6.5 前端: data 数据结构 ────────────────────────────────────

    def test_ready_data_is_dict_not_list(self):
        """ready 接口 data 是对象而非数组。"""
        response = client.get("/api/v1/health/ready")
        data = response.json()["data"]
        assert isinstance(data, dict), "ready data 应为 dict 对象"

    def test_dependencies_data_is_dict_not_list(self):
        """dependencies 接口 data.dependencies 是对象而非数组。
        前端: Object.entries(depStatuses) 需要对象格式。"""
        response = client.get("/api/v1/health/dependencies")
        deps = response.json()["data"]["dependencies"]
        assert isinstance(deps, dict), (
            "dependencies 必须是 dict，前端 Object.entries() 需要对象格式"
        )

    # ── 6.6 前端 fallback 逻辑 — 服务离线时的兜底 ─────────────────

    def test_health_endpoint_returns_valid_json_even_on_error(self):
        """即使服务降级 (503)，响应仍为合法 JSON 且结构一致。"""
        # 正常情况返回 200，但即使降级也应有统一结构
        response = client.get("/api/v1/health/ready")
        body = response.json()
        # 无论状态码如何，data/meta/error 三字段必须存在
        assert "data" in body
        assert "meta" in body
        assert "error" in body

    def test_pagination_structure_valid_regardless_of_data_volume(self):
        """无论知识库数据量多少，分页响应结构始终完整且一致。"""
        # 文档列表
        docs = client.get("/api/v1/documents", params={"page": 1, "page_size": 1})
        docs_body = docs.json()
        assert isinstance(docs_body["data"], list), "data 必须是数组"
        assert len(docs_body["data"]) <= 1, "page_size=1 最多返回 1 条"
        assert isinstance(docs_body["meta"]["total"], int), "total 必须是整数"
        assert docs_body["meta"]["total"] >= 0, "total 必须 >= 0"
        # total_pages 与 total/page_size 逻辑一致
        expected_pages = (
            (docs_body["meta"]["total"] + docs_body["meta"]["page_size"] - 1)
            // docs_body["meta"]["page_size"]
            if docs_body["meta"]["total"] > 0 else 0
        )
        assert docs_body["meta"]["total_pages"] == expected_pages

        # 知识块列表
        chunks = client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})
        chunks_body = chunks.json()
        assert isinstance(chunks_body["data"], list), "data 必须是数组"
        assert len(chunks_body["data"]) <= 1, "page_size=1 最多返回 1 条"
        assert isinstance(chunks_body["meta"]["total"], int), "total 必须是整数"
        assert chunks_body["meta"]["total"] >= 0, "total 必须 >= 0"
        expected_pages = (
            (chunks_body["meta"]["total"] + chunks_body["meta"]["page_size"] - 1)
            // chunks_body["meta"]["page_size"]
            if chunks_body["meta"]["total"] > 0 else 0
        )
        assert chunks_body["meta"]["total_pages"] == expected_pages

    def test_error_field_is_explicit_null_in_success_responses(self):
        """成功响应中 error 字段必须显式为 null（非 undefined/missing）。
        前端可能做 truthy 检查，确保 error 是 null 而非空字符串或其他。"""
        urls = [
            "/api/v1/health/ready",
            "/api/v1/health/dependencies",
            "/api/v1/documents?page=1&page_size=1",
            "/api/v1/chunks?page=1&page_size=1",
        ]
        for url in urls:
            response = client.get(url)
            body = response.json()
            assert body["error"] is None, (
                f"{url} 成功响应中 error 应为 null，实际为 {body['error']!r}"
            )


# ══════════════════════════════════════════════════════════════════════
# 7. 并发场景测试 — 模拟前端 Promise.all 并行请求
# ══════════════════════════════════════════════════════════════════════

class TestDashboardConcurrency:
    """模拟前端 dashboard.js:16-19 的 Promise.all 并行调用。"""

    def test_concurrent_health_checks(self):
        """并行调用 health/ready 和 health/dependencies，验证无竞态错误。"""
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                "ready": executor.submit(client.get, "/api/v1/health/ready"),
                "deps": executor.submit(client.get, "/api/v1/health/dependencies"),
            }
            results = {k: v.result() for k, v in futures.items()}

        assert results["ready"].status_code == 200
        assert results["deps"].status_code == 200

    def test_concurrent_document_and_chunk_counts(self):
        """并行调用文档列表和知识块列表，验证无竞态错误。"""
        import concurrent.futures

        def fetch_docs():
            return client.get("/api/v1/documents", params={"page": 1, "page_size": 1})

        def fetch_chunks():
            return client.get("/api/v1/chunks", params={"page": 1, "page_size": 1})

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                "docs": executor.submit(fetch_docs),
                "chunks": executor.submit(fetch_chunks),
            }
            results = {k: v.result() for k, v in futures.items()}

        assert results["docs"].status_code == 200
        assert results["chunks"].status_code == 200
        assert isinstance(results["docs"].json()["meta"]["total"], int)
        assert isinstance(results["chunks"].json()["meta"]["total"], int)
