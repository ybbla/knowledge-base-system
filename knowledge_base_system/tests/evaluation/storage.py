"""评测数据与结果存储封装。

提供：
- 分文档评测数据集保存到 datasets/ 目录
- 评测结果以 JSONL 格式追加写入 results/history.jsonl
- 存储目录初始化
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
DATASETS_DIR = EVAL_DIR / "datasets"
RESULTS_DIR = EVAL_DIR / "results"


def init_storage() -> None:
    """初始化存储目录结构 — 确保 datasets/ 和 results/ 存在。"""
    DATASETS_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)


def save_per_doc_dataset(
    doc_id: str,
    doc_title: str,
    items: list[dict[str, Any]],
    chunk_count: int,
) -> Path:
    """保存单个文档的评测数据到 datasets/ 目录。

    文件命名：doc_{doc_id前12位}_{日期}.json
    写入内容：{ metadata: {...}, items: [...] }

    Args:
        doc_id: 文档 ID。
        doc_title: 文档标题。
        items: 评测条目列表，每个 dict 包含 query、expected_chunk_ids、
               expected_content_contains、doc_id、source 字段。
        chunk_count: 该文档包含的知识块数量。

    Returns:
        保存的文件路径。
    """
    init_storage()

    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"doc_{doc_id[:12]}_{timestamp}.json"
    path = DATASETS_DIR / filename

    data = {
        "metadata": {
            "doc_id": doc_id,
            "doc_title": doc_title,
            "generated_at": datetime.now().isoformat(),
            "generated_by": "auto-ingest",
            "chunk_count": chunk_count,
            "query_count": len(items),
        },
        "items": items,
    }

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def append_eval_result(
    search_params: dict[str, Any],
    metrics: dict[str, float | None],
    query_count: int,
) -> Path:
    """将本次评测结果以一行 JSON 追加写入 results/history.jsonl。

    每条记录包含时间戳、检索参数、评测指标和查询总数，便于时间序列分析。

    Args:
        search_params: 检索参数字典，包含 rewrite、vector_top_k、bm25_top_k、
                       rrf_k、rerank、top_k 等字段。
        metrics: 评测指标字典，包含 recall_at_5 和 mrr。
        query_count: 参与评测的查询总数。

    Returns:
        history.jsonl 的文件路径。
    """
    init_storage()

    record = {
        "timestamp": datetime.now().isoformat(),
        "search_params": search_params,
        "metrics": metrics,
        "query_count": query_count,
    }

    history_path = RESULTS_DIR / "history.jsonl"
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return history_path
