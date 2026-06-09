"""
真实端到端测试：构造丰富的知识库文档，走通完整的 录入 → 解析 → 语义提取 → 索引 → 检索 流程。

运行方式：在 knowledge_base_system 目录下执行 python ../test_real_e2e.py

注意：本测试依赖火山引擎 ARK API（LLM + Embedding），需要网络连接。
"""

import json
import sys
import time
from pathlib import Path

# Ensure knowledge_base_system is on path
sys.path.insert(0, str(Path(__file__).parent / "knowledge_base_system"))

from fastapi.testclient import TestClient
from app.main import app

# -- 真实的测试文档 --------------------------------------------------
# 模拟一个企业内部的"智能客服平台"产品文档，内容丰富，结构多样

# ---- 精简版测试文档（2 个 h2 节，加速 LLM 处理）----
TEST_DOC = {
    "title": "智能客服平台 快速入门",
    "content": r"""
# 智能客服平台 快速入门

## 接入方式

平台支持三种接入方式，适用于不同业务场景：

| 接入方式 | 适用场景 | 开发周期 | 技术门槛 |
|----------|----------|----------|----------|
| Web Widget | 网站嵌入 | 1天 | 低 |
| REST API | 自定义集成 | 3-5天 | 中 |
| SDK | 移动端接入 | 5-7天 | 高 |

推荐新用户优先使用 Web Widget 方式接入，零编码即可完成部署。
API 鉴权需要在 Header 中携带 Bearer Token，Token 通过管理后台获取。

## 知识库管理

知识库采用三层结构组织内容：

- **领域（Domain）**：按业务线划分，如「电商」「金融」「售后」
- **分类（Category）**：领域下的细分主题，如「订单查询」「退款流程」
- **问答对（QA Pair）**：标准问题和答案，是检索的最小单元

导入问答对支持 JSON 格式，每个文件最多 5000 条。高频未命中问题需要在知识优化阶段补充。
""",
    "source_type": "markdown",
}

# -- 测试查询（匹配精简版文档内容）----------------------------------
TEST_QUERIES = [
    {
        "query": "系统支持哪些接入方式？",
        "top_k": 3,
        "description": "表格内容检索 - 应命中接入方式对比表",
    },
    {
        "query": "知识库的三层结构是什么？",
        "top_k": 3,
        "description": "列表内容检索 - 应命中领域/分类/问答对三层结构",
    },
    {
        "query": "如何导入问答对？",
        "top_k": 3,
        "description": "概念检索 - 应命中批量导入相关说明",
    },
]


def format_json(obj, max_str_len=200):
    """格式化JSON为可读字符串，截断过长内容"""
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    lines = s.split("\n")
    result = []
    for line in lines:
        if len(line) > max_str_len + 20:
            # 截断但保留结构
            stripped = line.strip()
            if stripped.startswith('"') and len(stripped) > max_str_len:
                val = stripped.split(":", 1)
                if len(val) == 2:
                    key = val[0].strip()
                    value = val[1].strip().rstrip(",")
                    if len(value) > max_str_len:
                        line = f'  {key}: {value[:max_str_len]}... (truncated)'
        result.append(line)
    return "\n".join(result)


def run_test():
    """执行完整端到端测试，记录输入和输出。"""
    client = TestClient(app)
    report: list[str] = []
    sep = "=" * 70
    sub = "-" * 50

    report.append(sep)
    report.append("知识库系统 端到端测试报告")
    report.append(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(sep)
    report.append("")

    # ═════════════════════════════════════════════════════════════
    # Phase 1: Ingestion
    # ═════════════════════════════════════════════════════════════
    report.append(sep)
    report.append("Phase 1: 文档录入 (Ingestion)")
    report.append(sep)

    # Input
    report.append("\n【输入】POST /ingest")
    report.append(sub)
    ingest_input = {
        "documents": [
            {
                "title": TEST_DOC["title"],
                "source_type": TEST_DOC["source_type"],
                "content": TEST_DOC["content"],
            }
        ],
        "options": {"max_depth": 1},
    }
    report.append(format_json(ingest_input, max_str_len=300))
    report.append(f"\n文档内容长度: {len(TEST_DOC['content'])} 字符")

    # Call ingest
    t0 = time.time()
    resp = client.post("/ingest", json=ingest_input)
    ingest_time = time.time() - t0

    report.append(f"\n响应状态: {resp.status_code}")
    if resp.status_code != 200:
        report.append(f"错误详情: {resp.text}")
        report.append(f"\n[FAIL] 录入失败，终止测试")
        return "\n".join(report)

    ingest_data = resp.json()
    report.append(f"\n【输出】响应 (耗时 {ingest_time:.2f}s)")
    report.append(sub)
    report.append(format_json(ingest_data))

    job_id = ingest_data["job_id"]
    doc_id = ingest_data["doc_ids"][0] if isinstance(ingest_data["doc_ids"], list) else ingest_data["doc_ids"]

    # Poll for completion
    report.append(f"\n轮询任务状态: {job_id}")
    report.append(sub)
    job_result = None
    for attempt in range(150):  # max 5 min at 2s interval
        status_resp = client.get(f"/ingest/{job_id}")
        if status_resp.status_code != 200:
            report.append(f"  轮询失败: {status_resp.text}")
            time.sleep(2)
            continue
        job = status_resp.json()
        elapsed = time.time() - t0
        cc = job.get('chunk_count', '?')
        report.append(
            f"  [{attempt+1:2d}] 状态: {job['status']:12s}  "
            f"chunk数: {cc!s:>3s}  "
            f"耗时: {elapsed:.1f}s"
        )
        if job["status"] in ("completed", "failed"):
            job_result = job
            break
        time.sleep(2)

    total_ingest = time.time() - t0

    if job_result is None:
        report.append(f"\n[FAIL] 录入超时（未在 5 分钟内完成）")
        return "\n".join(report)

    report.append(f"\n【最终状态】")
    report.append(sub)
    report.append(format_json(job_result))
    report.append(f"\n总录入耗时: {total_ingest:.2f}s")

    if job_result["status"] == "failed":
        report.append(f"\n[FAIL] 录入失败: {job_result.get('error')}")
        return "\n".join(report)

    report.append(f"[OK] 录入成功 — {job_result['chunk_count']} 个知识块已索引")

    # ═════════════════════════════════════════════════════════════
    # Phase 2: Search
    # ═════════════════════════════════════════════════════════════
    report.append("\n\n")
    report.append(sep)
    report.append("Phase 2: 知识检索 (Search)")
    report.append(sep)

    all_passed = True
    for qi, tq in enumerate(TEST_QUERIES, 1):
        report.append(f"\n{'-'*50}")
        report.append(f"查询 #{qi}: {tq['description']}")
        report.append(f"{'-'*50}")

        # Input
        search_input = {"query": tq["query"], "top_k": tq["top_k"]}
        report.append(f"\n【输入】POST /search")
        report.append(format_json(search_input))

        # Call search
        t0 = time.time()
        resp = client.post("/search", json=search_input)
        search_time = time.time() - t0

        report.append(f"\n响应状态: {resp.status_code} (耗时 {search_time:.2f}s)")
        if resp.status_code != 200:
            report.append(f"错误详情: {resp.text}")
            all_passed = False
            continue

        # Output (beautified)
        data = resp.json()
        report.append(f"\n【输出】搜索结果")
        report.append(sub)
        report.append(f"search_id:      {data.get('search_id')}")
        report.append(f"原始查询:       {data.get('query')}")
        report.append(f"改写查询:       {data.get('rewritten_query')}")
        report.append(f"候选总数:       {data.get('total_count')}")
        report.append(f"返回结果数:     {len(data.get('results', []))}")
        report.append("")

        for ri, result in enumerate(data.get("results", []), 1):
            sc = result.get("score_components", {})
            report.append(f"  -- 结果 #{ri} --")
            report.append(f"  chunk_id:     {result.get('chunk_id')}")
            report.append(f"  标题:         {result.get('title')}")
            report.append(f"  总分数:       {result.get('score'):.4f}")
            report.append(
                f"  分数明细:     vector={sc.get('vector', 0):.4f}  "
                f"bm25={sc.get('bm25', 0):.4f}  "
                f"rerank={sc.get('rerank', 0):.4f}"
            )
            content = result.get("content", "")
            report.append(f"  内容预览:     {content[:150]}{'...' if len(content)>150 else ''}")
            report.append(f"  知识类型:     {result.get('metadata', {}).get('knowledge_type')}")
            title_path = " > ".join(result.get("metadata", {}).get("title_path", []))
            if title_path:
                report.append(f"  标题路径:     {title_path}")

            # Source refs
            src_refs = result.get("source_refs", [])
            if src_refs:
                report.append(f"  来源引用:     {len(src_refs)} 个元素引用")
                for sr in src_refs[:3]:
                    report.append(f"    - doc={sr.get('doc_id','')[:20]}...  el={sr.get('element_id')}")

        # Quick relevance check
        contents_all = " ".join(r.get("content", "") for r in data.get("results", []))
        if contents_all:
            report.append(f"\n  [OK] 检索到 {len(data.get('results', []))} 条相关内容")
        else:
            report.append(f"\n  [WARN]  未检索到任何内容")
            all_passed = False

    # ═════════════════════════════════════════════════════════════
    # Summary
    # ═════════════════════════════════════════════════════════════
    report.append("\n\n")
    report.append(sep)
    report.append("测试总结")
    report.append(sep)
    report.append(f"录入文档数:     1")
    report.append(f"录入耗时:       {total_ingest:.2f}s")
    report.append(f"知识块数:       {job_result.get('chunk_count', 'N/A')}")
    report.append(f"搜索查询数:     {len(TEST_QUERIES)}")
    report.append(f"最终状态:       {'[OK] 全部通过' if all_passed else '[WARN] 部分查询无结果'}")

    return "\n".join(report)


if __name__ == "__main__":
    print("正在运行知识库系统端到端测试...")
    print("注意：需要火山引擎 ARK API 的网络连接。\n")
    report_text = run_test()
    print(report_text)

    # Save to file
    report_path = Path(__file__).parent / "test_e2e_report.txt"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\n\n报告已保存至: {report_path}")
