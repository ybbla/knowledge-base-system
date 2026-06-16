"""Phase 2 端到端测试：PostgreSQL 后端 Markdown + DOCX 真实链路。

启动方式::

    # 1. 启动 PostgreSQL
    docker compose up -d postgres

    # 2. 运行测试
    python knowledge_base_system/tests/e2e/e2e_phase2_markdown_docx.py

    # 3. 无 VOLCENGINE_API_KEY 时跳过语义抽取验证
    python knowledge_base_system/tests/e2e/e2e_phase2_markdown_docx.py --allow-zero-chunks

输入文件::

    data/simulated_inputs/phase2_product_manual.md
    data/simulated_inputs/phase2_technical_spec.docx

输出报告::

    knowledge_base_system/tests/results/e2e/phase2_e2e_YYYYMMDD_HHMMSS.md
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

# ── 路径常量 ────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
TESTS_DIR = SCRIPT_DIR.parent
PACKAGE_ROOT = TESTS_DIR.parent
REPO_ROOT = PACKAGE_ROOT.parent
INPUT_DIR = REPO_ROOT / "data" / "simulated_inputs"
RESULTS_DIR = TESTS_DIR / "results" / "e2e"

MARKDOWN_INPUT = INPUT_DIR / "phase2_product_manual.md"
DOCX_INPUT = INPUT_DIR / "phase2_technical_spec.docx"
DEFAULT_CATEGORY = "phase2-e2e"

if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/markdown", ".markdown")
mimetypes.add_type(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
)


# ── 数据结构 ────────────────────────────────────────────────────────


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Step:
    name: str
    ok: bool
    elapsed_seconds: float = 0.0
    request: dict[str, Any] = field(default_factory=dict)
    response: Any = None
    checks: list[Check] = field(default_factory=list)
    error: str | None = None


@dataclass
class CaseResult:
    name: str
    input_path: str
    source_type: str
    steps: list[Step]

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)


# ── 工具 ────────────────────────────────────────────────────────────


def _source_type_for(path: Path) -> str:
    """根据文件后缀返回 source_type。"""
    mapping = {".md": "markdown", ".markdown": "markdown", ".txt": "txt", ".docx": "docx"}
    suffix = path.suffix.lower()
    if suffix not in mapping:
        raise ValueError(f"不支持的文件后缀: {suffix}")
    return mapping[suffix]


def _content_type_for(path: Path) -> str:
    """返回 HTTP Content-Type。"""
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _exec(name: str, fn, request: dict | None = None) -> Step:
    """执行步骤，捕获异常并记录耗时。"""
    started = time.perf_counter()
    try:
        resp, checks = fn()
        return Step(
            name=name, ok=all(c.passed for c in checks),
            elapsed_seconds=time.perf_counter() - started,
            request=request or {}, response=_json_safe(resp), checks=checks,
        )
    except Exception as exc:
        return Step(
            name=name, ok=False, elapsed_seconds=time.perf_counter() - started,
            request=request or {}, error=f"{type(exc).__name__}: {exc}",
        )


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


_ICON = {True: "[PASS]", False: "[FAIL]"}


# ── API 步骤 ────────────────────────────────────────────────────────


def health(client: TestClient) -> Step:
    """GET /health"""
    def call():
        r = client.get("/health")
        body = r.json()
        return (
            {"status_code": r.status_code, "body": body},
            [Check("HTTP 200", r.status_code == 200),
             Check("status=ok", body.get("status") == "ok")],
        )
    return _exec("GET /health", call)


def upload(client: TestClient, path: Path, title: str, category: str) -> Step:
    """POST /upload — 上传文件，返回 source_uri。"""
    req = {"file": path.name, "title": title, "category": category}

    def call():
        with path.open("rb") as f:
            r = client.post(
                "/upload",
                files={"file": (path.name, f, _content_type_for(path))},
                data={"title": title, "category": category},
            )
        body = r.json()
        uri = body.get("source_uri", "")
        return (
            {"status_code": r.status_code, "body": body},
            [Check("HTTP 200", r.status_code == 200),
             Check("source_uri", bool(uri), uri),
             Check("sha256 hash", body.get("source_hash", "").startswith("sha256:")),
             Check("title", body.get("title") == title),
             Check("category", body.get("category") == category)],
        )
    return _exec("POST /upload", call, req)


def ingest(client: TestClient, up_body: dict, source_type: str, category: str) -> Step:
    """POST /ingest — 提交异步入库任务，返回 job_id。"""
    payload = {
        "documents": [{
            "title": up_body.get("title", ""),
            "source_type": source_type,
            "source_uri": up_body.get("source_uri", ""),
            "source_hash": up_body.get("source_hash", ""),
            "category": category,
        }],
        "options": {"max_depth": 1, "extract_assets": True},
    }

    def call():
        r = client.post("/ingest", json=payload)
        body = r.json()
        return (
            {"status_code": r.status_code, "body": body},
            [Check("HTTP 202", r.status_code == 202),
             Check("accepted", body.get("status") == "accepted"),
             Check("job_id", bool(body.get("job_id")))],
        )
    return _exec("POST /ingest", call, payload)


def poll(client: TestClient, job_id: str, timeout_s: float, require_chunks: bool) -> Step:
    """GET /ingest/{job_id} — 轮询直到 completed 或超时。"""
    req = {"job_id": job_id, "timeout_s": timeout_s}

    def call():
        deadline = time.time() + timeout_s
        polls, final = [], {}
        while time.time() < deadline:
            r = client.get(f"/ingest/{job_id}")
            body = r.json()
            polls.append({"status_code": r.status_code, **body})
            final = {"status_code": r.status_code, **body}
            if body.get("status") in ("completed", "failed"):
                break
            time.sleep(0.5)

        n_chunks = int(final.get("chunk_count") or 0)
        return (
            {"polls": polls, "final": final},
            [Check("HTTP 200", final.get("status_code") == 200),
             Check("completed", final.get("status") == "completed"),
             Check("no error", not final.get("error")),
             Check("chunks>0" if require_chunks else "ok",
                   n_chunks > 0 if require_chunks else True, str(n_chunks))],
        )
    return _exec("GET /ingest/{job_id}", call, req)


def search(client: TestClient, query: str, category: str, require: bool) -> Step:
    """POST /search — 检索并验证结果结构。"""
    payload = {"query": query, "top_k": 5, "filters": {"category": category}}

    def call():
        r = client.post("/search", json=payload)
        body = r.json()
        results = body.get("results") or []
        first = results[0] if results else {}
        return (
            {"status_code": r.status_code, "body": body},
            [Check("HTTP 200", r.status_code == 200),
             Check("有结果" if require else "ok",
                   len(results) > 0 if require else True, f"count={len(results)}"),
             Check("score_components", bool(first.get("score_components"))),
             Check("source_refs", bool(first.get("source_refs"))),
             Check("category 匹配", all(it.get("category") == category for it in results))],
        )
    return _exec(f"POST /search ({query})", call, payload)


# ── 用例执行 ────────────────────────────────────────────────────────


def _chunks_from(step: Step) -> int:
    if not isinstance(step.response, dict):
        return 0
    return int((step.response.get("final") or {}).get("chunk_count") or 0)


def run_case(
    client: TestClient,
    name: str,
    path: Path,
    query: str,
    category: str,
    timeout_s: float,
    require_chunks: bool,
) -> CaseResult:
    """执行单个文件的完整 API 链路。"""
    st = _source_type_for(path)
    title = f"{name}-{datetime.now().strftime('%H%M%S')}"
    steps: list[Step] = []

    steps.append(health(client))

    up = upload(client, path, title, category)
    steps.append(up)
    up_body = up.response.get("body", {}) if isinstance(up.response, dict) else {}

    if up.ok:
        ing = ingest(client, up_body, st, category)
    else:
        ing = Step("POST /ingest", False, error="上传失败，跳过")
    steps.append(ing)
    ing_body = ing.response.get("body", {}) if isinstance(ing.response, dict) else {}

    if ing.ok and ing_body.get("job_id"):
        pol = poll(client, ing_body["job_id"], timeout_s, require_chunks)
    else:
        pol = Step("GET /ingest/{job_id}", False, error="入库提交失败，跳过")
    steps.append(pol)

    if pol.ok and _chunks_from(pol) > 0:
        steps.append(search(client, query, category, require_chunks))
    else:
        steps.append(Step(
            "POST /search", False if require_chunks else True,
            error="无可用知识块，跳过检索",
            checks=[Check("skip ok", not require_chunks, f"chunks={_chunks_from(pol)}")],
        ))

    return CaseResult(name=name, input_path=str(path), source_type=st, steps=steps)


# ── 报告生成 ────────────────────────────────────────────────────────


def _render(cases: list[CaseResult], started: str, finished: str, backend: str, has_key: bool) -> str:
    ok = all(c.ok for c in cases)
    lines = [
        "# Phase 2 端到端测试报告",
        "",
        f"- 开始: {started}",
        f"- 结束: {finished}",
        f"- 结果: {_ICON[ok]}",
        f"- 后端: `{backend}`  |  API Key: {'已配置' if has_key else '未配置'}",
        f"- 通过: {sum(1 for c in cases if c.ok)}/{len(cases)}",
        "",
        "| 用例 | 类型 | 结果 |",
        "|------|------|------|",
    ]
    for c in cases:
        lines.append(f"| {c.name} | `{c.source_type}` | {_ICON[c.ok]} |")

    for c in cases:
        lines.extend(["", f"## {c.name}", "", f"输入: `{c.input_path}`  ({c.source_type})", ""])
        for i, s in enumerate(c.steps, 1):
            lines.extend([
                f"### {i}. {s.name}", "",
                f"{_ICON[s.ok]}  |  {s.elapsed_seconds:.1f}s",
            ])
            if s.error:
                lines.append(f"\n错误: `{s.error}`")
            if s.checks:
                lines.extend(["", "| 检查项 | 结果 | 详情 |", "|--------|------|------|"])
                for ch in s.checks:
                    d = str(ch.detail)[:300].replace("\n", " ")
                    lines.append(f"| {ch.name} | {_ICON[ch.passed]} | `{d}` |")
            lines.extend(["", "<details><summary>请求 / 响应</summary>", "", "```json"])
            lines.append(json.dumps({"request": s.request, "response": s.response}, ensure_ascii=False, indent=2))
            lines.extend(["```", "", "</details>"])

    return "\n".join(lines) + "\n"


# ── 入口 ────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--timeout", type=float, default=300.0, help="单用例最长等待秒数（默认 300）")
    p.add_argument("--category", default=DEFAULT_CATEGORY)
    p.add_argument("--allow-zero-chunks", action="store_true",
                   help="无 VOLCENGINE_API_KEY 时跳过 chunk_count 检查")
    args = p.parse_args()

    for f in [MARKDOWN_INPUT, DOCX_INPUT]:
        if not f.exists():
            print(f"[ERROR] 缺少: {f}")
            return 1

    os.chdir(PACKAGE_ROOT)
    from app.core.config import settings
    from app.main import app

    require = not args.allow_zero_chunks
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client = TestClient(app)

    cases = [
        run_case(client, "markdown-manual", MARKDOWN_INPUT,
                 "知识库系统支持哪些文档格式？上传大小限制是多少？",
                 args.category, args.timeout, require),
        run_case(client, "docx-techspec", DOCX_INPUT,
                 "系统架构分为哪几层？核心数据模型有哪些？",
                 args.category, args.timeout, require),
    ]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rpt = RESULTS_DIR / f"phase2_e2e_{stamp}.md"
    rpt.write_text(_render(cases, started, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            settings.backend, bool(settings.api_key)), encoding="utf-8")

    print(f"报告: {rpt}")
    print(f"结果: {_ICON[all(c.ok for c in cases)]}")
    return 0 if all(c.ok for c in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
