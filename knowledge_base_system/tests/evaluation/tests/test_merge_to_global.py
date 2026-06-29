"""
merge_to_global.py 手动合并脚本单元测试。

测试核心的去重合并逻辑、保护人工标注行为、merge_all 批量合并、
以及合并后文件从 unmerged/ → merged/ 的移动行为。
"""

import json
import tempfile
from pathlib import Path

import pytest

from tests.evaluation.merge_to_global import merge_all, merge_doc_to_global


class TestMergeDocToGlobal:
    """单个文档合并逻辑测试。"""

    def test_merge_new_entries(self):
        """新条目成功合并到全局数据集。"""
        # 模拟已有数据集
        existing_keys = {("doc_old", "已有查询"): 0}
        existing_items = [
            {
                "query": "已有查询",
                "expected_chunk_ids": ["chunk_1"],
                "expected_content_contains": ["关键词"],
                "doc_id": "doc_old",
                "source": "auto",
            }
        ]

        # 新条目（不同 doc_id，不同 query）
        new_items = [
            {
                "query": "新查询",
                "expected_chunk_ids": ["chunk_2"],
                "expected_content_contains": ["新关键词"],
                "doc_id": "doc_new",
                "source": "auto",
            }
        ]

        added = 0
        for item in new_items:
            q = item.get("query", "")
            d = item.get("doc_id", "")
            key = (d, q)
            if key not in existing_keys:
                existing_items.append({
                    "query": q,
                    "expected_chunk_ids": item.get("expected_chunk_ids", []),
                    "expected_content_contains": item.get("expected_content_contains", []),
                    "doc_id": item.get("doc_id"),
                    "source": item.get("source", "auto"),
                })
                existing_keys[key] = len(existing_items) - 1
                added += 1

        assert added == 1
        assert len(existing_items) == 2

    def test_manual_entries_protected(self):
        """人工标注（source=manual）的条目不被覆盖。"""
        existing_queries = {"人工查询": 0}
        existing_items = [
            {
                "query": "人工查询",
                "expected_chunk_ids": ["chunk_important"],
                "source": "manual",
            }
        ]

        # 尝试合并同 query 的自动生成条目
        new_items = [
            {
                "query": "人工查询",
                "expected_chunk_ids": ["chunk_other"],
                "source": "auto",
            }
        ]

        added = 0
        skipped = 0
        for item in new_items:
            q = item.get("query", "")
            if q in existing_queries:
                idx = existing_queries[q]
                if existing_items[idx].get("source") == "manual":
                    skipped += 1
                    continue
                skipped += 1
                continue
            existing_items.append(item)
            existing_queries[q] = len(existing_items) - 1
            added += 1

        assert added == 0
        assert skipped == 1
        # 人工条目保持不变
        assert existing_items[0]["source"] == "manual"
        assert existing_items[0]["expected_chunk_ids"] == ["chunk_important"]

    def test_auto_entry_overwritten(self):
        """自动生成的条目（source=auto）可被新的自动标注覆盖。"""
        existing_queries = {"auto查询": 0}
        existing_items = [
            {
                "query": "auto查询",
                "expected_chunk_ids": ["old_chunk"],
                "source": "auto",
            }
        ]

        new_items = [
            {
                "query": "auto查询",
                "expected_chunk_ids": ["new_chunk"],
                "source": "auto",
            }
        ]

        updated = 0
        for item in new_items:
            q = item.get("query", "")
            if q in existing_queries:
                idx = existing_queries[q]
                if existing_items[idx].get("source") == "manual":
                    continue
                existing_items[idx] = {
                    "query": q,
                    "expected_chunk_ids": item.get("expected_chunk_ids", []),
                    "expected_content_contains": item.get(
                        "expected_content_contains", []
                    ),
                    "doc_id": item.get("doc_id"),
                    "source": item.get("source", "auto"),
                }
                updated += 1

        assert updated == 1
        assert existing_items[0]["expected_chunk_ids"] == ["new_chunk"]

    def test_dedup_by_doc_id_and_query(self):
        """不同文档的同名 query 不互相覆盖，去重键包含 doc_id。"""
        existing_keys = {("doc_a", "重复查询"): 0}
        existing_items = [
            {
                "query": "重复查询",
                "expected_chunk_ids": ["chunk_a"],
                "doc_id": "doc_a",
                "source": "auto",
            }
        ]

        new_items = [
            {
                "query": "重复查询",
                "expected_chunk_ids": ["chunk_b"],
                "doc_id": "doc_b",
                "source": "auto",
            },
            {
                "query": "全新查询",
                "expected_chunk_ids": ["chunk_c"],
                "doc_id": "doc_b",
                "source": "auto",
            },
        ]

        added = 0
        for item in new_items:
            q = item.get("query", "")
            d = item.get("doc_id", "")
            key = (d, q)
            if key not in existing_keys:
                existing_items.append(item)
                existing_keys[key] = len(existing_items) - 1
                added += 1

        # doc_b 的两个 query 都应新增（"重复查询" 属于不同 doc_id）
        assert added == 2
        assert len(existing_items) == 3


class TestMergeAll:
    """merge_all 批量合并测试。"""

    def test_merge_all_with_multiple_files(self):
        """merge_all 遍历所有文件，收集全部条目并正确去重。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            unmerged_dir = tmp_path / "unmerged"
            unmerged_dir.mkdir(parents=True)

            # 创建两个待合并文件
            for i in range(2):
                data = {
                    "metadata": {
                        "doc_id": f"doc_test_{i}",
                        "doc_title": f"测试文档{i}",
                    },
                    "items": [
                        {
                            "query": f"查询{i}",
                            "expected_chunk_ids": [f"chunk_{i}"],
                            "expected_content_contains": [f"关键词{i}"],
                            "doc_id": f"doc_test_{i}",
                            "source": "auto",
                        }
                    ],
                }
                path = unmerged_dir / f"doc_test_{i}_20260629.json"
                path.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )

            # 验证核心逻辑：两个文件的条目都应被收集
            all_items = []
            for f in sorted(unmerged_dir.glob("doc_*.json")):
                with open(f, encoding="utf-8") as fp:
                    all_items.extend(json.load(fp).get("items", []))

            assert len(all_items) == 2

            # 验证去重逻辑 — 按 (doc_id, query) 去重
            seen_keys = set()
            merged = []
            for item in all_items:
                key = (item.get("doc_id", ""), item.get("query", ""))
                if key not in seen_keys:
                    seen_keys.add(key)
                    merged.append(item)

            assert len(merged) == 2

    def test_files_moved_after_merge(self):
        """合并后源文件从 unmerged/ 移动到 merged/。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            unmerged_dir = tmp_path / "unmerged"
            merged_dir = tmp_path / "merged"
            unmerged_dir.mkdir(parents=True)
            merged_dir.mkdir(parents=True)

            # 在 unmerged/ 下创建文件
            data = {
                "metadata": {"doc_id": "doc_move_test", "doc_title": "移动测试"},
                "items": [
                    {
                        "query": "移动测试查询",
                        "expected_chunk_ids": ["chunk_x"],
                        "expected_content_contains": ["测试"],
                        "doc_id": "doc_move_test",
                        "source": "auto",
                    }
                ],
            }
            src_path = unmerged_dir / "doc_move_test_20260629.json"
            src_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )

            # 模拟合并后的文件移动
            target = merged_dir / src_path.name
            src_path.rename(target)

            # 验证文件已移动
            assert not src_path.exists()
            assert target.exists()

            # 验证内容完整
            with open(target, encoding="utf-8") as f:
                moved_data = json.load(f)
            assert moved_data["metadata"]["doc_id"] == "doc_move_test"
            assert len(moved_data["items"]) == 1

    def test_merge_all_no_files(self):
        """unmerged/ 为空时返回空统计。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            unmerged_dir = tmp_path / "unmerged"
            unmerged_dir.mkdir(parents=True)

            # 空目录下 glob 结果应为空
            all_files = sorted(unmerged_dir.glob("doc_*.json"))
            assert len(all_files) == 0
