"""
知识库系统真实 API 测试脚本

用法:
  1. 启动服务:
     cd knowledge_base_system
     python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

  2. 另开终端运行:
     python test_api.py

脚本会真实调用 HTTP API：
健康检查 -> 上传 Markdown 文件 -> 使用 source_uri 入库 -> 轮询状态 -> 按 category 检索

所有请求和响应会打印到终端，同时保存到 test_api_result.txt。
"""

from __future__ import annotations

import argparse
import json
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_CATEGORY = "产品使用"
RESULT_PATH = Path(__file__).parent / "test_api_result.txt"


DOC = {
    "title": "产品使用手册",
    "file_name": "product-manual.md",
    "source_type": "markdown",
    "category": DEFAULT_CATEGORY,
    "content": textwrap.dedent(
        """\
        # 产品使用手册

        ## 上传知识文档

        用户可以在知识库页面上传文档，支持 Markdown 和 TXT 格式。
        上传后系统会显示解析状态：处理中、成功、失败。

        | 状态 | 说明 |
        |------|------|
        | 处理中 | 系统正在解析文档 |
        | 成功 | 文档已经进入知识库 |
        | 失败 | 需要查看失败原因并重新上传 |

        ### 注意事项

        - 单文件不超过 10 MB
        - 支持批量上传
        - 上传完成后可以按业务分类检索文档内容
        """
    ).strip(),
}


QUERIES = [
    ("上传文档后如何判断解析成功？", 3),
    ("文件上传的大小限制是多少？", 3),
]


class ApiTestFailure(RuntimeError):
    """Raised when a real API check fails."""


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise ApiTestFailure(message)


def response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise ApiTestFailure(f"响应不是合法 JSON: {response.text[:300]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real API checks against a running knowledge-base service.")
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"API base URL, default: {DEFAULT_BASE}")
    parser.add_argument("--poll-seconds", type=int, default=300, help="Max seconds to wait for ingest completion.")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between ingest status checks.")
    parser.add_argument("--timeout", type=float, default=180.0, help="HTTP request timeout in seconds.")
    args = parser.parse_args()

    lines: list[str] = []

    def log(message: str = "", end: str = "\n") -> None:
        print(message, end=end)
        if end == "\n":
            lines.append(message)
        else:
            if not lines:
                lines.append("")
            lines[-1] += message

    def request(method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{args.base.rstrip('/')}{path}"
        log(f"  {method.upper()} {path}")
        try:
            response = client.request(method, url, **kwargs)
        except httpx.ConnectError as exc:
            raise ApiTestFailure(f"无法连接服务: {url}。请先启动 FastAPI 服务。") from exc
        log(f"    -> HTTP {response.status_code}")
        return response

    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    log("=" * 72)
    log("  知识库系统真实 API 测试")
    log(f"  base: {args.base}")
    log(f"  time: {started_at}")
    log("=" * 72)

    success = False
    try:
        with httpx.Client(timeout=args.timeout) as client:
            # 1. Health check
            log()
            log("--- 1. 健康检查 ---")
            health = request("GET", "/health")
            health_data = response_json(health)
            log(pretty_json(health_data))
            assert_true(health.status_code == 200, f"/health 状态码应为 200，实际为 {health.status_code}")
            assert_true(health_data.get("status") == "ok", "/health 响应缺少 status=ok")

            # 2. Upload real file
            log()
            log("--- 2. 上传 Markdown 文件：POST /upload ---")
            with tempfile.TemporaryDirectory(prefix="kb-api-test-") as tmp_dir:
                doc_path = Path(tmp_dir) / DOC["file_name"]
                doc_path.write_text(DOC["content"], encoding="utf-8")

                with doc_path.open("rb") as file_obj:
                    upload = request(
                        "POST",
                        "/upload",
                        files={"file": (DOC["file_name"], file_obj, "text/markdown")},
                        data={"title": DOC["title"], "category": DOC["category"]},
                    )

                upload_data = response_json(upload)
                log(pretty_json(upload_data))
                assert_true(upload.status_code == 200, f"/upload 状态码应为 200，实际为 {upload.status_code}")
                assert_true(upload_data.get("source_uri", "").startswith("file://"), "/upload 未返回 file:// source_uri")
                assert_true(upload_data.get("source_hash", "").startswith("sha256:"), "/upload 未返回 sha256 source_hash")
                assert_true(upload_data.get("title") == DOC["title"], "/upload 返回 title 不匹配")
                assert_true(upload_data.get("category") == DOC["category"], "/upload 返回 category 不匹配")
                assert_true(upload_data.get("size", 0) > 0, "/upload 返回 size 应大于 0")

            # 3. Ingest using source_uri
            log()
            log("--- 3. 使用 source_uri 入库：POST /ingest ---")
            ingest_payload = {
                "documents": [
                    {
                        "title": upload_data["title"],
                        "source_type": DOC["source_type"],
                        "source_uri": upload_data["source_uri"],
                        "category": upload_data["category"],
                    }
                ],
                "options": {"max_depth": 1},
            }
            ingest = request("POST", "/ingest", json=ingest_payload)
            ingest_data = response_json(ingest)
            log(pretty_json(ingest_data))
            assert_true(ingest.status_code == 202, f"/ingest 状态码应为 202，实际为 {ingest.status_code}")
            assert_true(ingest_data.get("status") == "accepted", "/ingest 响应 status 应为 accepted")
            assert_true(bool(ingest_data.get("job_id")), "/ingest 未返回 job_id")
            assert_true(bool(ingest_data.get("doc_ids")), "/ingest 未返回 doc_ids")
            job_id = ingest_data["job_id"]

            # 4. Poll ingest status
            log()
            log("--- 4. 轮询入库状态：GET /ingest/{job_id} ---")
            deadline = time.time() + args.poll_seconds
            status_data: dict[str, Any] | None = None
            last_status_key: tuple[Any, Any, Any, Any] | None = None
            while time.time() < deadline:
                status_response = request("GET", f"/ingest/{job_id}")
                status_data = response_json(status_response)
                assert_true(status_response.status_code == 200, f"/ingest/{job_id} 状态码应为 200")

                status_key = (
                    status_data.get("status"),
                    status_data.get("chunk_count"),
                    status_data.get("asset_count"),
                    status_data.get("error"),
                )
                if status_key != last_status_key:
                    log(pretty_json(status_data))
                    last_status_key = status_key

                if status_data.get("status") in {"completed", "failed"}:
                    break
                time.sleep(args.poll_interval)

            assert_true(status_data is not None, "未获取到入库状态")
            assert_true(status_data.get("status") == "completed", f"入库未完成: {status_data}")
            assert_true(status_data.get("chunk_count", 0) > 0, "入库完成但 chunk_count 为 0")

            # 5. Search with category filter
            log()
            log("--- 5. 分类过滤检索：POST /search ---")
            for index, (query, top_k) in enumerate(QUERIES, 1):
                log()
                log(f"  查询 {index}: {query}")
                search_payload = {
                    "query": query,
                    "top_k": top_k,
                    "filters": {"category": DOC["category"]},
                }
                start = time.time()
                search = request("POST", "/search", json=search_payload)
                elapsed = time.time() - start
                search_data = response_json(search)
                log(pretty_json(search_data))

                assert_true(search.status_code == 200, f"/search 状态码应为 200，实际为 {search.status_code}")
                assert_true("rewritten_query" in search_data, "/search 未返回 rewritten_query")
                assert_true(isinstance(search_data.get("results"), list), "/search results 应为列表")
                assert_true(len(search_data["results"]) > 0, "/search 没有返回结果")

                log(f"    returned={len(search_data['results'])}, total_count={search_data.get('total_count')}, time={elapsed:.1f}s")
                for result_index, item in enumerate(search_data["results"], 1):
                    assert_true(item.get("category") == DOC["category"], f"结果 #{result_index} category 不匹配")
                    assert_true(bool(item.get("knowledge_type")), f"结果 #{result_index} 缺少 knowledge_type")
                    assert_true("score_components" in item, f"结果 #{result_index} 缺少 score_components")
                    assert_true("source_refs" in item, f"结果 #{result_index} 缺少 source_refs")
                    log(
                        f"    #{result_index} [{item['category']} / {item['knowledge_type']}] "
                        f"{item.get('title', '<no title>')} score={item.get('score', 0):.4f}"
                    )

            success = True
            log()
            log("=" * 72)
            log("  真实 API 测试通过")
            log("=" * 72)

    except ApiTestFailure as exc:
        log()
        log("=" * 72)
        log("  真实 API 测试失败")
        log(f"  {exc}")
        log("=" * 72)
    finally:
        RESULT_PATH.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n结果已保存至: {RESULT_PATH}")

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
