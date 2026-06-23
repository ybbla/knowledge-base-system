"""
存储层单元测试。

测试 storage.py 中的核心功能：
- save_per_doc_dataset() 输出文件格式和字段完整性
- append_eval_result() JSONL 追加写入正确性
- init_storage() 目录创建
"""

import json
import tempfile
from pathlib import Path

from tests.evaluation.storage import (
    append_eval_result,
    init_storage,
    save_per_doc_dataset,
)


class TestSavePerDocDataset:
    """分文档数据集存储测试。"""

    def test_output_format(self):
        """验证 save_per_doc_dataset 输出文件的 metadata 和 items 结构。"""
        items = [
            {
                "query": "测试查询一",
                "expected_chunk_ids": ["chunk_1"],
                "expected_content_contains": ["关键词A"],
                "doc_id": "doc_test_001",
                "source": "auto",
            },
            {
                "query": "测试查询二",
                "expected_chunk_ids": ["chunk_2"],
                "expected_content_contains": ["关键词B"],
                "doc_id": "doc_test_001",
                "source": "auto",
            },
        ]

        path = save_per_doc_dataset(
            doc_id="doc_test_001",
            doc_title="测试文档",
            items=items,
            chunk_count=3,
        )

        assert path.exists()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # 验证 metadata 结构
        meta = data["metadata"]
        assert meta["doc_id"] == "doc_test_001"
        assert meta["doc_title"] == "测试文档"
        assert meta["generated_by"] == "auto-ingest"
        assert meta["chunk_count"] == 3
        assert meta["query_count"] == 2

        # 验证 items 使用新字段名
        assert len(data["items"]) == 2
        assert data["items"][0]["query"] == "测试查询一"
        assert data["items"][0]["expected_chunk_ids"] == ["chunk_1"]
        assert data["items"][0]["doc_id"] == "doc_test_001"
        assert data["items"][0]["source"] == "auto"

    def test_save_empty_items(self):
        """保存空的条目列表也应生成合法文件。"""
        path = save_per_doc_dataset(
            doc_id="doc_empty",
            doc_title="空文档",
            items=[],
            chunk_count=0,
        )

        assert path.exists()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["metadata"]["query_count"] == 0
        assert data["items"] == []


class TestAppendEvalResult:
    """评测结果 JSONL 追加写入测试。"""

    def test_append_creates_jsonl_line(self):
        """验证 append_eval_result 在 history.jsonl 中追加一行完整 JSON 记录。"""
        search_params = {
            "rewrite": True,
            "vector_top_k": 30,
            "bm25_top_k": 30,
            "rrf_k": 60,
            "rerank": True,
            "top_k": 5,
        }
        metrics = {
            "recall_at_5": 0.667,
            "mrr": 0.583,
        }

        path = append_eval_result(
            search_params=search_params,
            metrics=metrics,
            query_count=50,
        )

        assert path.exists()

        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) >= 1
        record = json.loads(lines[-1])

        assert "timestamp" in record
        assert record["search_params"]["rewrite"] is True
        assert record["search_params"]["vector_top_k"] == 30
        assert record["search_params"]["top_k"] == 5
        assert record["metrics"]["recall_at_5"] == 0.667
        assert record["metrics"]["mrr"] == 0.583
        assert record["query_count"] == 50

    def test_multiple_appends(self):
        """多次追加写入不会覆盖已有记录，每行独立。"""
        append_eval_result(
            search_params={"top_k": 5},
            metrics={"recall_at_5": 0.5, "mrr": 0.4},
            query_count=10,
        )
        path = append_eval_result(
            search_params={"top_k": 10},
            metrics={"recall_at_5": 0.8, "mrr": 0.7},
            query_count=20,
        )

        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) >= 2
        first = json.loads(lines[-2])
        second = json.loads(lines[-1])

        assert first["metrics"]["recall_at_5"] == 0.5
        assert second["metrics"]["recall_at_5"] == 0.8


class TestInitStorage:
    """存储目录初始化测试。"""

    def test_creates_directories(self):
        """验证 init_storage 创建 datasets/ 和 results/ 目录（幂等）。"""
        init_storage()
        from tests.evaluation.storage import DATASETS_DIR, RESULTS_DIR

        assert DATASETS_DIR.exists()
        assert RESULTS_DIR.exists()
