"""Load and validate the evaluation dataset."""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalItem:
    """A single evaluation query."""

    query: str
    expected_chunk_ids: list[str] = field(default_factory=list)
    expected_content_contains: list[str] = field(default_factory=list)

    # 新增元数据字段（用于筛选和追溯）
    source_doc_id: str | None = None
    source_doc_title: str | None = None
    category: str | None = None
    difficulty: str = "medium"
    source: str = "auto"  # auto / manual
    generated_at: str | None = None

    # 运行时字段（仅用于筛选上次失败的）
    _last_passed: bool | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "EvalItem":
        """从字典创建 EvalItem，缺失字段使用默认值。"""
        return cls(
            query=data["query"],
            expected_chunk_ids=data.get("expected_chunk_ids", []),
            expected_content_contains=data.get("expected_content_contains", []),
            source_doc_id=data.get("source_doc_id"),
            source_doc_title=data.get("source_doc_title"),
            category=data.get("category"),
            difficulty=data.get("difficulty", "medium"),
            source=data.get("source", "auto"),
            generated_at=data.get("generated_at"),
        )


def load_dataset(path: Path | str | None = None) -> list[EvalItem]:
    """Load evaluation dataset from JSON file.

    Args:
        path: Path to eval_dataset.json. Defaults to tests/evaluation/eval_dataset.json.

    Returns:
        List of EvalItem validated records.

    Raises:
        FileNotFoundError: If dataset file doesn't exist.
        ValueError: If any record is missing required fields.
    """
    if path is None:
        path = Path(__file__).parent / "eval_dataset.json"

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    items = []
    for i, record in enumerate(raw):
        query = record.get("query")
        if not query:
            raise ValueError(f"Record {i}: missing required field 'query'")

        expected_chunk_ids = record.get("expected_chunk_ids", [])
        expected_content_contains = record.get("expected_content_contains", [])

        if not expected_chunk_ids and not expected_content_contains:
            raise ValueError(
                f"Record {i} ('{query}'): must have at least one of "
                "expected_chunk_ids or expected_content_contains"
            )

        # 使用 from_dict 支持所有新字段的解析，保持向后兼容
        items.append(EvalItem.from_dict(record))

    return items
