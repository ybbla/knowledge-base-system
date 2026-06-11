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

        items.append(
            EvalItem(
                query=query,
                expected_chunk_ids=list(expected_chunk_ids),
                expected_content_contains=list(expected_content_contains),
            )
        )

    return items
