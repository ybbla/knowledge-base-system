"""评测数据与结果存储封装。

提供统一的接口用于：
- 保存单个文档生成的评测数据到 datasets/ 目录
- 增量合并到全局评测数据集
- 保存评测结果到 results/ 目录
- 加载所有评测数据（全局 + 分文档）
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.evaluation.dataset import EvalItem

EVAL_DIR = Path(__file__).resolve().parent
DATASETS_DIR = EVAL_DIR / "datasets"
RESULTS_DIR = EVAL_DIR / "results"
GLOBAL_DATASET = EVAL_DIR / "eval_dataset.json"


def init_storage() -> None:
    """初始化存储目录结构。"""
    DATASETS_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)


def save_per_doc_dataset(
    doc_id: str,
    doc_title: str,
    items: list[dict[str, Any]],
    chunk_count: int,
) -> Path:
    """保存单个文档的评测数据。

    Args:
        doc_id: 文档 ID
        doc_title: 文档标题
        items: 评测条目列表
        chunk_count: 文档包含的知识块数量

    Returns:
        保存的文件路径
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

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def merge_to_global_dataset(items: list[dict[str, Any]]) -> int:
    """增量合并到全局评测数据集。

    按 query 文本去重，已存在的条目保持不变，保护人工修正的数据。

    Args:
        items: 待合并的新评测条目

    Returns:
        实际新增的条目数量
    """
    init_storage()

    existing: list[dict[str, Any]] = []
    if GLOBAL_DATASET.exists():
        with open(GLOBAL_DATASET, encoding="utf-8") as f:
            existing = json.load(f)

    existing_queries = {item["query"] for item in existing if "query" in item}
    added = 0

    for item in items:
        q = item.get("query", "")
        if q and q not in existing_queries:
            existing.append({
                "query": q,
                "expected_chunk_ids": item.get("expected_chunk_ids", []),
                "expected_content_contains": item.get("expected_content_contains", []),
                "source_doc_id": item.get("source_doc_id"),
                "source_doc_title": item.get("source_doc_title"),
                "category": item.get("category"),
                "difficulty": item.get("difficulty", "medium"),
                "source": item.get("source", "auto"),
                "generated_at": item.get("generated_at"),
            })
            existing_queries.add(q)
            added += 1

    if added > 0:
        GLOBAL_DATASET.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return added


def save_eval_result(
    metrics: dict[str, Any],
    details: list[dict[str, Any]],
    trigger: str = "manual",
    trigger_doc_id: str | None = None,
) -> Path:
    """保存评测结果。

    Args:
        metrics: 指标字典（recall@5, mrr, keyword_recall@5 等）
        details: 每条查询的详细结果
        trigger: 触发方式（manual / auto-ingest / scheduled）
        trigger_doc_id: 触发的文档 ID（如果是入库触发）

    Returns:
        保存的文件路径
    """
    init_storage()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"eval_result_{timestamp}.json"
    path = RESULTS_DIR / filename

    data = {
        "metadata": {
            "run_at": datetime.now().isoformat(),
            "trigger": trigger,
            "trigger_doc_id": trigger_doc_id,
            "total_queries": len(details),
            "duration_seconds": metrics.get("duration", 0),
        },
        "metrics": metrics,
        "details": details,
    }

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 更新 latest.json 快捷方式
    latest = RESULTS_DIR / "latest.json"
    shutil.copy(path, latest)

    return path


def load_all_datasets() -> list[EvalItem]:
    """加载所有评测数据（全局 + 分文档）。

    按 query 文本去重，重复条目保留先出现的版本（全局文件优先）。

    Returns:
        去重后的 EvalItem 列表
    """
    init_storage()
    all_items: list[EvalItem] = []
    seen_queries: set[str] = set()

    # 1. 先加载全局数据集（优先级最高）
    if GLOBAL_DATASET.exists():
        with open(GLOBAL_DATASET, encoding="utf-8") as f:
            raw_items = json.load(f)
        for item in raw_items:
            if "query" in item and item["query"] not in seen_queries:
                eval_item = EvalItem.from_dict(item)
                all_items.append(eval_item)
                seen_queries.add(eval_item.query)

    # 2. 加载分文档数据集
    for dataset_file in DATASETS_DIR.glob("doc_*.json"):
        try:
            with open(dataset_file, encoding="utf-8") as f:
                data = json.load(f)
            raw_items = data.get("items", [])
            for item in raw_items:
                if "query" in item and item["query"] not in seen_queries:
                    eval_item = EvalItem.from_dict(item)
                    all_items.append(eval_item)
                    seen_queries.add(eval_item.query)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("Failed to load dataset file %s: %s", dataset_file, e)

    return all_items


def load_latest_eval_result() -> dict[str, Any] | None:
    """加载最新的评测结果。

    Returns:
        最新的评测结果字典，如果不存在则返回 None
    """
    latest = RESULTS_DIR / "latest.json"
    if not latest.exists():
        return None

    try:
        with open(latest, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning("Failed to load latest eval result: %s", e)
        return None
