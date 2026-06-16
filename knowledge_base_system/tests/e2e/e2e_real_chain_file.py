"""使用模拟输入文件运行真实端到端 API 链路。

本脚本是知识库系统的端到端集成测试，只模拟 **唯一外部依赖**（输入文件），其余全部走真实代码链路。

测试输入文件从仓库根目录 ``data/simulated_inputs`` 读取，
然后依次执行完整的 4 步 API 链路：

.. code-block:: text

    ┌──────────┐    ┌──────────┐    ┌───────────────┐    ┌──────────┐
    │ ① upload │───▶│ ② ingest │───▶│ ③ poll status │───▶│ ④ search │
    └──────────┘    └──────────┘    └───────────────┘    └──────────┘
        上传文件         提交入库         轮询入库状态          检索验证
                      （异步入库）     （等待完成）

每个步骤都会记录请求、响应、校验项和耗时，最终生成一份 Markdown 报告
写入到 ``tests/results/e2e`` 目录。

.. note::

    入库步骤依赖 VOLCENGINE_API_KEY 环境变量。未配置时，LLM 语义抽取
    无法工作，chunk_count 将为 0，导致检索步骤无结果。
    其他链路（上传 → 提交入库 → 轮询完成）不受影响。

.. important::

    运行前请先切换到 knowledge_base_system/ 目录。Settings 通过相对路径
    ``env_file=".env"`` 加载环境变量，因此当前工作目录必须是
    ``.env`` 文件所在目录（即 knowledge_base_system/）。

使用方式::

    # 先切换到 knowledge_base_system 目录
    cd knowledge_base_system

    # 使用默认输入文件
    python tests/e2e/e2e_real_chain_file.py

    # 指定输入文件和超时
    python tests/e2e/e2e_real_chain_file.py --input my_doc.md --timeout 300

    # 指定标题和分类
    python tests/e2e/e2e_real_chain_file.py --title "产品手册" --category "技术文档"
"""

from __future__ import annotations

# 运行说明：
# 1. 安装依赖：pip install -r requirements.txt
# 2. 如需入库生成知识块和检索结果，配置 VOLCENGINE_API_KEY。
# 3. 在项目根目录运行：
#    python knowledge_base_system/tests/e2e/e2e_real_chain_file.py
# 4. 可通过 --input、--title、--category、--timeout 指定输入文件、标题、分类和超时时间。
#
# 执行流程：
# 1. 读取 data/simulated_inputs/product_manual_source.md 或 --input 指定文件。
# 2. 通过 TestClient 加载真实 FastAPI app，不需要单独启动 uvicorn。
# 3. 依次执行 POST /upload、POST /ingest、轮询 GET /ingest/{job_id}、POST /search。
# 4. 每一步记录请求摘要、响应内容、校验项、耗时和异常信息。
#
# 结果保存：
# - 上传文件写入 data/uploads/。
# - Markdown 报告写入 knowledge_base_system/tests/results/e2e/e2e_real_chain_file_report.md。

import argparse
import json
import mimetypes
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

# ──────────────────────────────────────────────────────────────────────
# 路径常量
# ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
TESTS_DIR = SCRIPT_DIR.parent
PACKAGE_ROOT = TESTS_DIR.parent  # knowledge_base_system/
REPO_ROOT = PACKAGE_ROOT.parent  # 项目根目录
INPUT_DIR = REPO_ROOT / "data" / "simulated_inputs"
DEFAULT_INPUT = INPUT_DIR / "product_manual_source.md"
REPORT_PATH = TESTS_DIR / "results" / "e2e" / "e2e_real_chain_file_report.md"

# 确保 knowledge_base_system 包在 sys.path 中（FastAPI app 导入需要）
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

# ──────────────────────────────────────────────────────────────────────
# 文件后缀 → source_type 映射（用于 API 请求中的 source_type 字段）
# ──────────────────────────────────────────────────────────────────────

SOURCE_TYPE_BY_SUFFIX: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".text": "text",
    ".docx": "docx",
}

# 初始化 mimetypes，确保 .md 文件被正确识别为 text/markdown。
# Windows 上系统注册表不包含 Markdown 类型，mimetypes 会回退到
# application/octet-stream，导致 FastAPI 无法正确解析上传文件。
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/markdown", ".markdown")


# ──────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────


@dataclass
class InputFile:
    """封装一个测试输入文件的全部信息。

    从磁盘读取文件后创建此实例，包含内容、类型、元数据等，
    后续传递给 upload / ingest 步骤使用。
    """

    path: Path
    """磁盘上文件的绝对路径。"""
    content: bytes
    """文件原始字节内容（用于上传）。"""
    source_type: str
    """knowledge_base_system 内部的 source_type 标识（如 'markdown'）。"""
    content_type: str
    """HTTP Content-Type（如 'text/markdown'）。"""
    title: str
    """文档标题（默认为文件名主干）。"""
    category: str
    """文档分类标签（用于入库和检索过滤）。"""

    @property
    def preview(self) -> str:
        """生成文件内容的文本预览（最多 1200 字符），用于报告展示。

        文本类格式返回解码后的前 1200 字符；
        二进制格式返回文件名和大小摘要。
        """
        if self.source_type in {"markdown", "txt", "text"}:
            return self.content.decode("utf-8", errors="replace")[:1200]
        return f"<二进制文件 {self.path.name}, {len(self.content)} 字节>"


@dataclass
class Check:
    """单个校验项，记录检查名称、通过状态和详情。"""

    name: str
    """校验项名称（如 'HTTP 200'）。"""
    passed: bool
    """是否通过。"""
    detail: str = ""
    """详情（如实际返回的状态码或值）。"""


@dataclass
class Step:
    """API 链路上的一个步骤（upload / ingest / poll / search）。

    记录请求内容、响应内容、校验结果、耗时和异常信息。
    """

    name: str
    """步骤名称（如 'POST /upload'）。"""
    ok: bool
    """该步骤所有校验是否通过。"""
    request: dict[str, Any] = field(default_factory=dict)
    """发送的请求摘要（用于报告展示）。"""
    response: Any = None
    """响应内容（含 status_code 和 body）。"""
    checks: list[Check] = field(default_factory=list)
    """该步骤的所有校验项。"""
    elapsed_seconds: float = 0.0
    """步骤耗时（秒）。"""
    error: str | None = None
    """异常时的完整 traceback 字符串。"""


# ──────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────


def _json(value: Any) -> str:
    """将任意值序列化为格式化的 JSON 字符串（用于报告嵌入）。"""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _source_type_for(path: Path) -> str:
    """根据文件后缀解析对应的 source_type。

    Args:
        path: 输入文件路径。

    Returns:
        source_type 字符串（如 'markdown'）。

    Raises:
        ValueError: 后缀不在支持列表中。
    """
    suffix = path.suffix.lower()
    if suffix not in SOURCE_TYPE_BY_SUFFIX:
        supported = ", ".join(sorted(SOURCE_TYPE_BY_SUFFIX))
        raise ValueError(
            f"不支持的输入文件后缀 '{suffix}'。支持的后缀：{supported}"
        )
    return SOURCE_TYPE_BY_SUFFIX[suffix]


def _load_input_file(path: Path, title: str | None, category: str) -> InputFile:
    """从磁盘加载输入文件并构造 InputFile 实例。

    会验证路径存在且为文件，自动探测 MIME 类型和 source_type。
    如果未指定 title，默认使用文件名主干（不含后缀）。

    Args:
        path: 输入文件的绝对路径。
        title: 文档标题，为 None 时自动从文件名推导。
        category: 文档分类标签。

    Returns:
        封装好的 InputFile 实例。

    Raises:
        FileNotFoundError: 路径不存在。
        ValueError: 路径不是文件，或后缀不支持。
    """
    if not path.is_file():
        if not path.exists():
            raise FileNotFoundError(f"未找到输入文件：{path}")
        raise ValueError(f"输入路径不是文件：{path}")

    # 使用 mimetypes 探测 Content-Type（用于 HTTP multipart 上传）
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    return InputFile(
        path=path,
        content=path.read_bytes(),
        source_type=_source_type_for(path),
        content_type=content_type,
        title=title or path.stem,
        category=category,
    )


# ──────────────────────────────────────────────────────────────────────
# API 步骤函数（每个函数对应 API 链路中的一个步骤）
# ──────────────────────────────────────────────────────────────────────


def _post_upload(client: TestClient, input_file: InputFile) -> Step:
    """步骤① — POST /upload：上传文件到知识库系统。

    将 InputFile 的内容以 multipart/form-data 格式发送到 /upload 端点。
    验证服务端正确落盘文件并返回 source_uri、source_hash 等元数据。

    Args:
        client: FastAPI TestClient 实例。
        input_file: 要上传的输入文件。

    Returns:
        Step 实例，包含请求摘要、响应、校验和耗时。
    """
    started = time.perf_counter()
    step = Step(
        name="POST /upload",
        ok=False,
        request={
            "input_path": str(input_file.path),
            "file_name": input_file.path.name,
            "content_type": input_file.content_type,
            "title": input_file.title,
            "category": input_file.category,
            "size": len(input_file.content),
            "content_preview": input_file.preview,
        },
    )

    try:
        # 使用 multipart/form-data 上传文件，同时附带 title 和 category
        response = client.post(
            "/upload",
            files={
                "file": (
                    input_file.path.name,
                    input_file.content,
                    input_file.content_type,
                )
            },
            data={"title": input_file.title, "category": input_file.category},
        )
        body = response.json()
        source_uri = body.get("source_uri", "")
        source_hash = body.get("source_hash", "")

        step.response = {"status_code": response.status_code, "body": body}
        step.checks = [
            Check("HTTP 200", response.status_code == 200, str(response.status_code)),
            Check("返回 source_uri", bool(source_uri), source_uri),
            Check(
                "返回 source_hash（sha256: 前缀）",
                isinstance(source_hash, str) and source_hash.startswith("sha256:"),
                source_hash,
            ),
            Check(
                "title 保留",
                body.get("title") == input_file.title,
                body.get("title", ""),
            ),
            Check(
                "category 保留",
                body.get("category") == input_file.category,
                body.get("category", ""),
            ),
        ]

        # 额外验证：文件确实落地到了 data/uploads/ 目录
        if source_uri.startswith("file://"):
            stored = Path(source_uri.replace("file://", ""))
            step.checks.append(
                Check("上传文件已落盘", stored.exists(), str(stored))
            )

        step.ok = all(check.passed for check in step.checks)
    except Exception:
        step.error = traceback.format_exc()
    finally:
        step.elapsed_seconds = time.perf_counter() - started

    return step


def _post_ingest(
    client: TestClient, input_file: InputFile, upload_body: dict[str, Any]
) -> Step:
    """步骤② — POST /ingest：提交文档入库任务。

    将上传步骤返回的 source_uri 等信息构建为 IngestRequest，
    发送到 /ingest 端点。该端点返回 202 Accepted 表示任务已提交，
    实际解析由后台线程异步执行。

    Args:
        client: FastAPI TestClient 实例。
        input_file: 原始输入文件（用于填充 source_type 等字段）。
        upload_body: 步骤① upload 响应中的 body 部分。

    Returns:
        Step 实例。job_id 在 response.body.job_id 中，
        用于步骤③轮询。
    """
    started = time.perf_counter()
    payload = {
        "documents": [
            {
                "title": upload_body.get("title", input_file.title),
                "source_type": input_file.source_type,
                "source_uri": upload_body.get("source_uri"),
                "source_hash": upload_body.get("source_hash", ""),
                "category": upload_body.get("category", input_file.category),
            }
        ],
        "options": {
            "max_depth": 1,
            "extract_assets": True,
        },
    }
    step = Step(name="POST /ingest", ok=False, request=payload)

    try:
        response = client.post("/ingest", json=payload)
        body = response.json()
        step.response = {"status_code": response.status_code, "body": body}
        step.checks = [
            Check("HTTP 202", response.status_code == 202, str(response.status_code)),
            Check("任务被接受", body.get("status") == "accepted", body.get("status", "")),
            Check("返回 job_id", bool(body.get("job_id")), str(body.get("job_id"))),
            Check("返回 doc_ids", bool(body.get("doc_ids")), str(body.get("doc_ids"))),
        ]
        step.ok = all(check.passed for check in step.checks)
    except Exception:
        step.error = traceback.format_exc()
    finally:
        step.elapsed_seconds = time.perf_counter() - started

    return step


def _poll_ingest(client: TestClient, job_id: str, timeout_seconds: float) -> Step:
    """步骤③ — GET /ingest/{job_id}：轮询异步入库任务状态。

    每 2 秒查询一次任务状态，直到任务 status 变为 'completed' 或 'failed'，
    或达到超时时间。每次轮询的快照记录在 polls 列表中。

    Note:
        实际入库耗时取决于 LLM 调用次数（语义抽取）。
        未配置 VOLCENGINE_API_KEY 时 LLM 调用会失败，
        但 parser 提取的元素仍会尝试索引。

    Args:
        client: FastAPI TestClient 实例。
        job_id: 步骤②返回的 job_id。
        timeout_seconds: 最长等待秒数。

    Returns:
        Step 实例。最终状态在 response.final 中。
    """
    started = time.perf_counter()
    step = Step(
        name=f"GET /ingest/{job_id}",
        ok=False,
        request={"job_id": job_id, "timeout_seconds": timeout_seconds},
        response={"polls": []},
    )

    try:
        deadline = time.time() + timeout_seconds
        last_body: dict[str, Any] = {}

        while time.time() < deadline:
            response = client.get(f"/ingest/{job_id}")
            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text}
            last_body = body

            # 记录本轮快照
            poll_entry = {
                "status_code": response.status_code,
                "status": body.get("status"),
                "chunk_count": body.get("chunk_count"),
                "asset_count": body.get("asset_count"),
                "error": body.get("error"),
            }
            step.response["polls"].append(poll_entry)

            # 终态或异常状态时停止轮询
            if response.status_code != 200 or body.get("status") in {"completed", "failed"}:
                break

            time.sleep(2)

        step.response["final"] = last_body
        last_poll = step.response["polls"][-1] if step.response["polls"] else {}
        chunk_count = int(last_body.get("chunk_count") or 0)

        step.checks = [
            Check(
                "状态接口 HTTP 200",
                last_poll.get("status_code") == 200,
                str(last_poll.get("status_code")),
            ),
            Check(
                "任务完成",
                last_body.get("status") == "completed",
                last_body.get("status", ""),
            ),
            Check(
                "生成知识块 (chunk_count > 0)",
                chunk_count > 0,
                f"chunk_count={chunk_count}（需要 VOLCENGINE_API_KEY）",
            ),
            Check(
                "任务无错误",
                not last_body.get("error"),
                str(last_body.get("error")),
            ),
        ]
        step.ok = all(check.passed for check in step.checks)
    except Exception:
        step.error = traceback.format_exc()
    finally:
        step.elapsed_seconds = time.perf_counter() - started

    return step


def _post_search(client: TestClient, query: str, category: str) -> Step:
    """步骤④ — POST /search：检索知识库内容。

    发送自然语言查询到 /search 端点，触发完整的检索链路：
    Query Rewrite → Vector/BM25 双路检索 → RRF 融合 → LLM Rerank。

    验证返回结果中包含 search_id、rewritten_query、结果列表、
    评分明细和来源引用。

    Args:
        client: FastAPI TestClient 实例。
        query: 自然语言查询字符串。
        category: 分类过滤（只检索该分类下的知识块）。

    Returns:
        Step 实例。检索结果在 response.body.results 中。
    """
    started = time.perf_counter()
    payload = {"query": query, "top_k": 5, "filters": {"category": category}}
    step = Step(name=f"POST /search ({query})", ok=False, request=payload)

    try:
        response = client.post("/search", json=payload)
        body = response.json()
        results = body.get("results", [])
        first = results[0] if results else {}

        step.response = {"status_code": response.status_code, "body": body}
        step.checks = [
            Check("HTTP 200", response.status_code == 200, str(response.status_code)),
            Check(
                "返回 search_id",
                bool(body.get("search_id")),
                body.get("search_id", ""),
            ),
            Check(
                "返回 rewritten_query",
                bool(body.get("rewritten_query")),
                body.get("rewritten_query", ""),
            ),
            Check(
                "检索有结果 (results > 0)",
                len(results) > 0,
                f"results={len(results)}（需要入库步骤成功生成知识块）",
            ),
            Check(
                "结果 category 匹配过滤条件",
                all(item.get("category") == category for item in results),
                category,
            ),
            Check(
                "包含评分明细 (score_components)",
                bool(first.get("score_components")),
                _json(first.get("score_components", {})),
            ),
            Check(
                "包含来源引用 (source_refs)",
                bool(first.get("source_refs")),
                _json(first.get("source_refs", [])),
            ),
        ]
        step.ok = all(check.passed for check in step.checks)
    except Exception:
        step.error = traceback.format_exc()
    finally:
        step.elapsed_seconds = time.perf_counter() - started

    return step


# ──────────────────────────────────────────────────────────────────────
# 报告生成
# ──────────────────────────────────────────────────────────────────────


def _render_report(
    steps: list[Step], input_file: InputFile, started_at: str
) -> str:
    """生成 Markdown 格式的端到端测试报告。

    报告结构：
    1. 总体摘要（时间、结果、环境信息）
    2. 输入文件预览
    3. 每个步骤的详细信息（请求、响应、校验表格）

    Args:
        steps: 所有已执行的步骤列表。
        input_file: 输入文件信息。
        started_at: 测试开始时间的字符串表示。

    Returns:
        Markdown 格式的报告全文。
    """
    lines: list[str] = []
    passed = all(step.ok for step in steps)

    # ── 总体摘要 ──
    lines.append("# 真实链路端到端测试报告")
    lines.append("")
    lines.append(f"- **开始时间**: {started_at}")
    lines.append(f"- **结束时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **总体结果**: {'✅ PASS' if passed else '❌ FAIL'}")
    lines.append(f"- **工作目录**: `{Path.cwd()}`")
    lines.append(f"- **输入文件**: `{input_file.path}`")
    lines.append(f"- **输入 source_type**: `{input_file.source_type}`")
    from app.core.config import settings

    lines.append(f"- **BACKEND**: `{settings.backend}`")
    lines.append(
        f"- **VOLCENGINE_API_KEY 已配置**: "
        f"`{bool(settings.api_key)}`"
    )

    # 统计摘要
    total = len(steps)
    ok_count = sum(1 for s in steps if s.ok)
    lines.append(f"- **步骤通过**: {ok_count}/{total}")
    lines.append("")

    # 如果失败，显示失败原因摘要
    failed_steps = [s for s in steps if not s.ok]
    if failed_steps:
        lines.append("### 失败步骤摘要")
        lines.append("")
        for fs in failed_steps:
            failed_checks = [c for c in fs.checks if not c.passed]
            if failed_checks:
                lines.append(
                    f"- **{fs.name}**: "
                    + ", ".join(c.name for c in failed_checks)
                )
            elif fs.error:
                lines.append(f"- **{fs.name}**: 异常 — `{fs.error[:200]}`")
            else:
                lines.append(f"- **{fs.name}**: 未执行或跳过")
        lines.append("")

    # ── 输入文件预览 ──
    lines.append("## 输入文件预览")
    lines.append("")
    fence = "markdown" if input_file.source_type == "markdown" else "text"
    lines.append(f"```{fence}")
    lines.append(input_file.preview.strip())
    lines.append("```")
    lines.append("")

    # ── 各步骤详情 ──
    for index, step in enumerate(steps, 1):
        lines.append(f"## {index}. {step.name}")
        lines.append("")
        lines.append(f"- **结果**: {'✅ PASS' if step.ok else '❌ FAIL'}")
        lines.append(f"- **耗时**: {step.elapsed_seconds:.2f}s")

        # 异常信息
        if step.error:
            lines.append("")
            lines.append("### ⚠ 异常")
            lines.append("")
            lines.append("```text")
            lines.append(step.error.strip())
            lines.append("```")

        # 请求摘要
        lines.append("")
        lines.append("### 请求")
        lines.append("")
        lines.append("```json")
        lines.append(_json(step.request))
        lines.append("```")

        # 响应内容
        lines.append("")
        lines.append("### 响应")
        lines.append("")
        lines.append("```json")
        lines.append(_json(step.response))
        lines.append("```")

        # 校验表格
        lines.append("")
        lines.append("### 校验")
        lines.append("")
        lines.append("| 检查项 | 结果 | 详情 |")
        lines.append("|---|---|---|")
        if step.checks:
            for check in step.checks:
                # 将换行符替换为空格，避免破坏表格结构
                detail = check.detail.replace("\n", " ").replace("\r", " ") if check.detail else ""
                lines.append(
                    f"| {check.name} "
                    f"| {'✅ PASS' if check.passed else '❌ FAIL'} "
                    f"| `{detail}` |"
                )
        else:
            lines.append("| 未执行 | ❌ FAIL | `无校验结果` |")
        lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────


def run(
    input_path: Path,
    timeout_seconds: float,
    title: str | None,
    category: str,
) -> int:
    """执行完整的端到端测试链路。

    步骤顺序：
    1. 切换工作目录到项目根（FastAPI app 的相对路径依赖于此）
    2. 加载输入文件
    3. 创建 TestClient 并依次执行 upload → ingest → poll → search
    4. 每个步骤失败时，后续依赖步骤会跳过
    5. 生成 Markdown 报告写入磁盘

    Args:
        input_path: 输入文件的绝对路径。
        timeout_seconds: 等待入库完成的最长秒数。
        title: 文档标题（None 则自动推导）。
        category: 文档分类标签。

    Returns:
        退出码：0 表示所有步骤通过，1 表示有失败步骤。
    """
    os.chdir(PACKAGE_ROOT)
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    steps: list[Step] = []

    # ── 加载输入文件 ──
    input_file = _load_input_file(input_path, title=title, category=category)

    # ── 导入 FastAPI app 并创建 TestClient ──
    from app.main import app

    client = TestClient(app)

    # ── 步骤①：上传文件 ──
    upload_step = _post_upload(client, input_file)
    steps.append(upload_step)

    # 从 upload 响应中提取后续步骤所需的数据
    upload_body = (
        (upload_step.response or {}).get("body", {})
        if isinstance(upload_step.response, dict)
        else {}
    )

    # ── 步骤②：提交入库 ──
    if upload_step.ok:
        ingest_step = _post_ingest(client, input_file, upload_body)
    else:
        ingest_step = Step(
            "POST /ingest", False,
            error="因上传失败（步骤①）而跳过。请检查文件路径和权限。",
        )
    steps.append(ingest_step)

    # 提取 job_id：单个文档返回字符串，批量返回列表
    ingest_body = (
        (ingest_step.response or {}).get("body", {})
        if isinstance(ingest_step.response, dict)
        else {}
    )
    job_id = ingest_body.get("job_id")
    if isinstance(job_id, list):
        job_id = job_id[0] if job_id else None

    # ── 步骤③：轮询入库状态 ──
    if ingest_step.ok and job_id:
        poll_step = _poll_ingest(client, str(job_id), timeout_seconds)
    else:
        poll_step = Step(
            "GET /ingest/{job_id}", False,
            error="因入库任务提交失败（步骤②）而跳过。",
        )
    steps.append(poll_step)

    # ── 步骤④：检索验证（2 个查询） ──
    # 查询与输入文件内容相关，确保检索链路端到端可用。
    # 输入文件 product_manual_source.md 内容为产品使用手册，
    # 涉及上传文档、解析流程、知识库检索等主题。
    search_queries = [
        "如何上传文档到知识库？",
        "上传文档支持哪些格式？",
    ]
    for query in search_queries:
        steps.append(_post_search(client, query, input_file.category))

    # ── 生成并写入报告 ──
    report = _render_report(steps, input_file, started_at)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"报告已写入：{REPORT_PATH}")

    # 终端输出简要结果
    total = len(steps)
    ok_count = sum(1 for s in steps if s.ok)
    print(f"结果: {ok_count}/{total} 步骤通过")
    if ok_count == total:
        print("[PASS] 所有步骤通过")
    else:
        for s in steps:
            if not s.ok:
                failed = [c.name for c in s.checks if not c.passed]
                if failed:
                    print(f"  [FAIL] {s.name}: {', '.join(failed)}")

    return 0 if all(step.ok for step in steps) else 1


def main() -> int:
    """解析命令行参数并执行测试。"""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"输入文件路径。默认值：{DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="等待异步入库任务完成的秒数（默认 180）。",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="文档标题。默认使用输入文件名主干。",
    )
    parser.add_argument(
        "--category",
        default="系统测试",
        help="文档分类，用于入库和检索过滤。默认：'系统测试'。",
    )
    args = parser.parse_args()
    return run(
        input_path=args.input.resolve(),
        timeout_seconds=args.timeout,
        title=args.title,
        category=args.category,
    )


if __name__ == "__main__":
    raise SystemExit(main())
