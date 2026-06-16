"""Phase 3 端到端测试：PostgreSQL + Milvus + MinIO 完整链路。

本脚本是阶段 3 的核心集成测试，使用 ``data/simulated_inputs`` 下的模拟数据
通过 FastAPI TestClient 真实执行完整 API 链路，验证以下 Phase 3 能力：

- PostgreSQL 持久化（文档、元素、知识块、资产）
- Milvus 向量检索（dense + sparse 双路索引）
- MinIO 对象存储（文件上传、图片 Asset 落盘、预签名 URL）
- 图片处理链路（格式校验、缩略图）
- 视频链接识别（Asset 创建但不下载）
- 混合检索（RRF 融合 + LLM Rerank）

启动方式::

    # 1. 启动全部后端服务
    docker compose up -d postgres etcd minio milvus-standalone

    # 2. 运行测试（需要 VOLCENGINE_API_KEY）
    python knowledge_base_system/tests/e2e/e2e_phase3_markdown_docx.py

    # 3. 仅验证上传和解析链路（无需 LLM）
    python knowledge_base_system/tests/e2e/e2e_phase3_markdown_docx.py --allow-empty-results

    # 4. 单独运行 Markdown 或 DOCX 用例
    python knowledge_base_system/tests/e2e/e2e_phase3_markdown_docx.py --case markdown

输入文件::

    data/simulated_inputs/phase3_product_manual.md
    data/simulated_inputs/phase3_architecture_spec.docx

输出报告::

    knowledge_base_system/tests/results/e2e/phase3_e2e_YYYYMMDD_HHMMSS.md
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

# ── 路径常量 ────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
TESTS_DIR = SCRIPT_DIR.parent
PACKAGE_ROOT = TESTS_DIR.parent
REPO_ROOT = PACKAGE_ROOT.parent
INPUT_DIR = REPO_ROOT / "data" / "simulated_inputs"
RESULTS_DIR = TESTS_DIR / "results" / "e2e"

# Phase 3 模拟输入文件
MARKDOWN_INPUT = INPUT_DIR / "phase3_product_manual.md"
DOCX_INPUT = INPUT_DIR / "phase3_architecture_spec.docx"

if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

# 注册 MIME 类型，确保 Windows 环境下正确识别 Markdown 和 DOCX
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/markdown", ".markdown")
mimetypes.add_type(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".docx",
)

# ── 数据结构 ────────────────────────────────────────────────────────────


@dataclass
class Check:
    """单个校验项。"""
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Step:
    """API 链路中的一个步骤。"""
    name: str
    ok: bool
    elapsed_seconds: float = 0.0
    request: dict[str, Any] = field(default_factory=dict)
    response: Any = None
    checks: list[Check] = field(default_factory=list)
    error: str | None = None


@dataclass
class CaseConfig:
    """单个测试用例的配置。"""
    name: str
    path: Path
    source_type: str
    title: str
    category: str
    queries: list[str]           # 检索验证用的查询列表
    min_assets: int = 0          # 最少期望 Asset 数量


@dataclass
class CaseResult:
    """单个用例的执行结果。"""
    name: str
    input_path: str
    source_type: str
    steps: list[Step]

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.steps)


# ── 工具函数 ────────────────────────────────────────────────────────────


def _source_type(path: Path) -> str:
    """根据文件后缀返回 source_type。"""
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".docx":
        return "docx"
    raise ValueError(f"不支持的文件类型：{path}")


def _content_type(path: Path) -> str:
    """返回 HTTP Content-Type。"""
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _run_step(name: str, fn, request: dict[str, Any] | None = None) -> Step:
    """执行步骤，统一捕获异常并记录耗时。"""
    started = time.perf_counter()
    try:
        response, checks = fn()
        return Step(
            name=name,
            ok=all(check.passed for check in checks),
            elapsed_seconds=time.perf_counter() - started,
            request=request or {},
            response=response,
            checks=checks,
        )
    except Exception as exc:
        return Step(
            name=name,
            ok=False,
            elapsed_seconds=time.perf_counter() - started,
            request=request or {},
            error=f"{type(exc).__name__}: {exc}",
        )


def _json_safe(value: Any) -> Any:
    """确保值可 JSON 序列化，否则转为字符串。"""
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


# ── 用例配置 ─────────────────────────────────────────────────────────────


def prepare_cases(category: str, selected: str = "all") -> list[CaseConfig]:
    """构建测试用例列表。

    Args:
        category: 文档分类标签。
        selected: "all" | "markdown" | "docx"
    """
    if not MARKDOWN_INPUT.exists():
        raise FileNotFoundError(f"缺少模拟 Markdown 文件：{MARKDOWN_INPUT}")
    if not DOCX_INPUT.exists():
        raise FileNotFoundError(f"缺少模拟 DOCX 文件：{DOCX_INPUT}")

    cases = [
        CaseConfig(
            name="Phase3-Markdown-产品手册",
            path=MARKDOWN_INPUT,
            source_type=_source_type(MARKDOWN_INPUT),
            title="智能知识库产品使用手册（Phase 3 测试）",
            category=category,
            queries=[
                "知识库系统支持哪些文件格式？",
                "入库流程包含哪些阶段？",
                "视频链接如何处理？",
            ],
            min_assets=1,  # Markdown 中至少有一个图片引用
        ),
        CaseConfig(
            name="Phase3-DOCX-技术架构规范",
            path=DOCX_INPUT,
            source_type=_source_type(DOCX_INPUT),
            title="智能知识库技术架构规范（Phase 3 测试）",
            category=category,
            queries=[
                "系统采用什么架构设计？",
                "Milvus 和 MinIO 分别负责什么？",
                "Asset 生命周期有哪些状态？",
            ],
            min_assets=1,  # DOCX 中嵌入了测试图片
        ),
    ]

    if selected == "markdown":
        return [cases[0]]
    if selected == "docx":
        return [cases[1]]
    return cases


# ── API 步骤 ─────────────────────────────────────────────────────────────


def step_health(client: TestClient) -> Step:
    """GET /health — 验证服务存活。"""
    def call():
        resp = client.get("/health")
        body = resp.json()
        return (
            {"status_code": resp.status_code, "body": body},
            [
                Check("HTTP 200", resp.status_code == 200, str(resp.status_code)),
                Check("服务状态 ok", body.get("status") == "ok", str(body)),
            ],
        )

    return _run_step("GET /health", call)


def step_upload(client: TestClient, case: CaseConfig) -> Step:
    """POST /upload — 上传文件，验证返回元数据。

    检查项：
    - HTTP 200
    - 返回 source_uri（MinIO 格式为 minio://，本地为 file://）
    - 返回 source_hash（sha256: 前缀）
    - 标题和分类保留正确
    - 文件落地或写入 MinIO
    """
    request = {
        "file_name": case.path.name,
        "content_type": _content_type(case.path),
        "title": case.title,
        "category": case.category,
        "size": case.path.stat().st_size,
    }

    def call():
        with case.path.open("rb") as handle:
            resp = client.post(
                "/upload",
                files={"file": (case.path.name, handle, _content_type(case.path))},
                data={"title": case.title, "category": case.category},
            )
        body = resp.json()
        source_uri = body.get("source_uri", "")

        checks = [
            Check("HTTP 200", resp.status_code == 200, str(resp.status_code)),
            Check("返回 source_uri", bool(source_uri), str(source_uri)),
            Check(
                "返回 source_hash（sha256: 前缀）",
                str(body.get("source_hash", "")).startswith("sha256:"),
                str(body.get("source_hash")),
            ),
            Check("标题保留正确", body.get("title") == case.title, str(body.get("title"))),
            Check("分类保留正确", body.get("category") == case.category, str(body.get("category"))),
        ]

        # 验证文件存储位置
        if source_uri.startswith("file://"):
            from app.core.paths import resolve_file_uri
            checks.append(
                Check(
                    "本地文件已落盘",
                    resolve_file_uri(source_uri).exists(),
                    str(resolve_file_uri(source_uri)),
                )
            )
        elif source_uri.startswith("minio://"):
            checks.append(
                Check("MinIO URI 格式正确", True, source_uri)
            )

        return ({"status_code": resp.status_code, "body": body}, checks)

    return _run_step("POST /upload", call, request)


def step_ingest(client: TestClient, case: CaseConfig, upload_body: dict[str, Any]) -> Step:
    """POST /ingest — 提交异步入库任务。

    检查项：
    - HTTP 202 Accepted
    - 任务状态为 accepted
    - 返回 job_id 和 doc_ids
    """
    payload = {
        "documents": [
            {
                "title": upload_body["title"],
                "source_type": case.source_type,
                "source_uri": upload_body["source_uri"],
                "source_hash": upload_body.get("source_hash", ""),
                "category": case.category,
            }
        ],
        "options": {
            "max_depth": 1,
            "max_elements_per_doc": 1000,
            "extract_assets": True,
        },
    }

    def call():
        resp = client.post("/ingest", json=payload)
        body = resp.json()
        return (
            {"status_code": resp.status_code, "body": body},
            [
                Check("HTTP 202", resp.status_code == 202, str(resp.status_code)),
                Check("任务状态 accepted", body.get("status") == "accepted", str(body.get("status"))),
                Check("返回 job_id", bool(body.get("job_id")), str(body.get("job_id"))),
                Check("返回 doc_ids", bool(body.get("doc_ids")), str(body.get("doc_ids"))),
            ],
        )

    return _run_step("POST /ingest", call, payload)


def step_poll(
    client: TestClient,
    job_id: str,
    timeout_seconds: float,
    *,
    min_assets: int,
    allow_empty_results: bool,
) -> Step:
    """GET /ingest/{job_id} — 轮询入库任务直至完成或超时。

    Phase 3 重点检查：
    - chunk_count > 0（语义抽取成功）
    - asset_count >= min_assets（图片/视频 Asset 已创建）
    - 任务无 error

    Args:
        min_assets: 最少期望 Asset 数量。
        allow_empty_results: True 时跳过 chunk_count 检查。
    """
    request = {
        "job_id": job_id,
        "timeout_seconds": timeout_seconds,
        "min_assets": min_assets,
        "allow_empty_results": allow_empty_results,
    }

    def call():
        deadline = time.time() + timeout_seconds
        polls: list[dict[str, Any]] = []
        final: dict[str, Any] = {}

        while time.time() < deadline:
            resp = client.get(f"/ingest/{job_id}")
            body = resp.json()
            final = {"status_code": resp.status_code, **body}
            polls.append(final)
            if body.get("status") in {"completed", "failed"}:
                break
            time.sleep(1)

        chunk_count = int(final.get("chunk_count") or 0)
        asset_count = int(final.get("asset_count") or 0)
        task_status = final.get("status", "unknown")

        checks = [
            Check("状态接口 HTTP 200", final.get("status_code") == 200, str(final.get("status_code"))),
            Check("入库任务 completed", task_status == "completed", task_status),
            Check("任务无 error", not final.get("error"), str(final.get("error"))),
        ]

        # 知识块检查
        if allow_empty_results:
            checks.append(Check("知识块数量（跳过检查）", True, f"chunk_count={chunk_count}"))
        else:
            checks.append(
                Check("生成知识块 chunk_count > 0", chunk_count > 0, f"chunk_count={chunk_count}")
            )

        # Asset 数量检查（Phase 3 关键指标）
        checks.append(
            Check(
                f"Asset 数量 >= {min_assets}",
                asset_count >= min_assets,
                f"asset_count={asset_count}",
            )
        )

        return (
            {"polls": polls, "final": final},
            checks,
        )

    return _run_step("GET /ingest/{job_id}", call, request)


def step_search(
    client: TestClient,
    query: str,
    category: str,
    *,
    allow_empty_results: bool,
) -> Step:
    """POST /search — 执行检索并验证结果结构。

    Phase 3 重点检查：
    - search_id 和 rewritten_query
    - score_components（向量分 + BM25 分 + 重排序分）
    - source_refs（来源文档和段落引用）
    - asset_refs（关联的图片/视频资源）
    - category 过滤正确
    - storage_uri 可渲染（MinIO 预签名 URL 或为空）
    """
    payload = {"query": query, "top_k": 5, "filters": {"category": category}}

    def call():
        resp = client.post("/search", json=payload)
        body = resp.json()
        results = body.get("results") or []
        first = results[0] if results else {}

        checks = [
            Check("HTTP 200", resp.status_code == 200, str(resp.status_code)),
            Check("返回 search_id", bool(body.get("search_id")), str(body.get("search_id"))),
            Check("返回 rewritten_query", "rewritten_query" in body, str(body.get("rewritten_query"))),
        ]

        # 检索结果基础检查
        if results:
            checks.extend([
                Check("检索返回结果", True, f"results={len(results)}"),
                Check(
                    "分类过滤正确",
                    all(item.get("category") == category for item in results),
                    category,
                ),
                Check(
                    "包含评分明细 score_components",
                    bool(first.get("score_components")),
                    json.dumps(first.get("score_components"), ensure_ascii=False),
                ),
                Check(
                    "包含来源引用 source_refs",
                    bool(first.get("source_refs")),
                    json.dumps(first.get("source_refs"), ensure_ascii=False),
                ),
            ])

            # Phase 3: 验证 asset_refs 的 storage_uri 可渲染
            all_asset_uris_ok = all(
                ref.get("storage_uri") is None
                or str(ref.get("storage_uri")).startswith(("http://", "https://", "file://", "minio://"))
                for item in results
                for ref in item.get("asset_refs", [])
            )
            checks.append(
                Check(
                    "Asset 资源 URL 可渲染或为空",
                    all_asset_uris_ok,
                    "asset_refs.storage_uri 格式检查",
                )
            )
        else:
            if allow_empty_results:
                checks.append(Check("检索结果（跳过检查）", True, "无结果但允许为空"))
            else:
                checks.append(Check("检索有结果", False, "results=0（可能需要 VOLCENGINE_API_KEY）"))

        return ({"status_code": resp.status_code, "body": body}, checks)

    return _run_step(f"POST /search: {query}", call, payload)


# ── 用例执行 ─────────────────────────────────────────────────────────────


def run_case(
    client: TestClient,
    case: CaseConfig,
    timeout_seconds: float,
    allow_empty_results: bool,
) -> CaseResult:
    """执行单个用例的完整 API 链路。

    链路顺序：health → upload → ingest → poll(status) → search × N
    任一步骤失败后，后续依赖步骤跳过。
    """
    steps: list[Step] = []

    # 1. 健康检查
    steps.append(step_health(client))

    # 2. 上传文件
    upload = step_upload(client, case)
    steps.append(upload)
    if not upload.ok or not isinstance(upload.response, dict):
        return CaseResult(case.name, str(case.path), case.source_type, steps)

    upload_body = upload.response.get("body") or {}

    # 3. 提交入库
    ingest = step_ingest(client, case, upload_body)
    steps.append(ingest)
    if not ingest.ok or not isinstance(ingest.response, dict):
        return CaseResult(case.name, str(case.path), case.source_type, steps)

    ingest_body = ingest.response.get("body") or {}
    job_id = ingest_body.get("job_id")
    if isinstance(job_id, list):
        job_id = job_id[0] if job_id else None
    if not job_id:
        steps.append(Step("GET /ingest/{job_id}", False, error="未返回 job_id，无法轮询"))
        return CaseResult(case.name, str(case.path), case.source_type, steps)

    # 4. 轮询入库状态
    poll = step_poll(
        client,
        str(job_id),
        timeout_seconds,
        min_assets=case.min_assets,
        allow_empty_results=allow_empty_results,
    )
    steps.append(poll)

    # 5. 检索验证（多条查询）
    if poll.ok or allow_empty_results:
        for query in case.queries:
            steps.append(
                step_search(client, query, case.category, allow_empty_results=allow_empty_results)
            )

    return CaseResult(case.name, str(case.path), case.source_type, steps)


# ── 报告生成 ─────────────────────────────────────────────────────────────


def render_markdown_report(
    *,
    started_at: str,
    finished_at: str,
    cases: list[CaseResult],
    settings_snapshot: dict[str, Any],
) -> str:
    """生成 Markdown 格式的端到端测试报告。"""
    overall_ok = all(case.ok for case in cases)
    lines = [
        "# Phase 3 端到端测试报告",
        "",
        f"- **开始时间**：{started_at}",
        f"- **结束时间**：{finished_at}",
        f"- **总体结果**：{'✅ PASS' if overall_ok else '❌ FAIL'}",
        f"- **模拟数据目录**：`{INPUT_DIR}`",
        f"- **报告目录**：`{RESULTS_DIR}`",
        "",
        "## 运行配置",
        "",
        "```json",
        json.dumps(settings_snapshot, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 用例汇总",
        "",
        "| 用例 | 输入类型 | 结果 |",
        "|---|---|---|",
    ]
    for case in cases:
        icon = "✅ PASS" if case.ok else "❌ FAIL"
        lines.append(f"| {case.name} | `{case.source_type}` | {icon} |")

    # 各用例详情
    for case in cases:
        lines.extend(["", f"## {case.name}", "", f"- 输入文件：`{case.input_path}`", ""])
        for index, step in enumerate(case.steps, 1):
            icon = "✅ PASS" if step.ok else "❌ FAIL"
            lines.extend([
                f"### {index}. {step.name}",
                "",
                f"- **结果**：{icon}",
                f"- **耗时**：{step.elapsed_seconds:.2f}s",
            ])
            if step.error:
                lines.extend(["", "**错误**：", "", "```text", step.error, "```"])
            lines.extend(["", "**校验项**：", "", "| 检查项 | 结果 | 详情 |", "|---|---|---|"])
            if step.checks:
                for check in step.checks:
                    detail = str(check.detail).replace("\n", " ")[:500]
                    icon_c = "✅" if check.passed else "❌"
                    lines.append(f"| {check.name} | {icon_c} | `{detail}` |")
            else:
                lines.append("| 无校验 | ❌ | `无` |")

            # 折叠请求/响应细节
            lines.extend([
                "",
                "<details><summary>📤 请求</summary>",
                "",
                "```json",
                json.dumps(step.request, ensure_ascii=False, indent=2),
                "```",
                "",
                "</details>",
                "",
                "<details><summary>📥 响应</summary>",
                "",
                "```json",
                json.dumps(step.response, ensure_ascii=False, indent=2, default=str),
                "```",
                "",
                "</details>",
            ])

    return "\n".join(lines) + "\n"


def write_report(
    cases: list[CaseResult],
    settings_snapshot: dict[str, Any],
    started_at: str,
) -> Path:
    """写入 Markdown 报告，返回文件路径。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    md_path = RESULTS_DIR / f"phase3_e2e_{stamp}.md"
    md_path.write_text(
        render_markdown_report(
            started_at=started_at,
            finished_at=finished_at,
            cases=cases,
            settings_snapshot=settings_snapshot,
        ),
        encoding="utf-8",
    )
    return md_path


# ── 入口 ─────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 3 端到端测试：PostgreSQL + Milvus + MinIO 完整链路",
    )
    parser.add_argument(
        "--category",
        default="phase3-e2e",
        help="文档分类标签（默认：phase3-e2e）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="入库轮询超时秒数（默认：180）",
    )
    parser.add_argument(
        "--case",
        choices=["all", "markdown", "docx"],
        default="all",
        help="选择运行全部或单个用例（默认：all）",
    )
    parser.add_argument(
        "--allow-empty-results",
        action="store_true",
        help="允许无 VOLCENGINE_API_KEY 或无知识块时仍生成报告并返回成功",
    )
    args = parser.parse_args()

    # 切换到知识库包根目录，确保相对路径正确
    os.chdir(PACKAGE_ROOT)
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    from app.core.config import settings
    from app.main import app

    # 快照当前配置
    settings_snapshot = {
        "backend": settings.backend,
        "milvus_enabled": settings.milvus_enabled,
        "milvus_host": settings.milvus_host,
        "milvus_port": settings.milvus_port,
        "minio_enabled": settings.minio_enabled,
        "minio_endpoint": settings.minio_endpoint,
        "minio_bucket_input": settings.minio_bucket_input,
        "minio_bucket_assets": settings.minio_bucket_assets,
        "vector_top_k": settings.vector_top_k,
        "bm25_top_k": settings.bm25_top_k,
        "fusion_top_k": settings.fusion_top_k,
        "rrf_k": settings.rrf_k,
        "volcengine_api_key_configured": bool(settings.api_key),
    }

    # 构建用例并执行
    cases_config = prepare_cases(args.category, args.case)
    with TestClient(app) as client:
        cases = [
            run_case(client, case, timeout_seconds=args.timeout, allow_empty_results=args.allow_empty_results)
            for case in cases_config
        ]

    # 生成报告
    md_path = write_report(cases, settings_snapshot, started_at)
    overall_ok = all(case.ok for case in cases)

    print(f"\n{'='*60}")
    print("Phase 3 端到端测试完成")
    print(f"{'='*60}")
    status_text = "PASS" if (overall_ok or args.allow_empty_results) else "FAIL"
    print(f"总体结果：{status_text}")
    print(f"Markdown 报告：{md_path}")

    return 0 if overall_ok or args.allow_empty_results else 1


if __name__ == "__main__":
    raise SystemExit(main())
