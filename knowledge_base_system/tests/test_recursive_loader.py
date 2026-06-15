import logging

from app.core.models import Document, ElementType, ParsedElement
from ingestion.recursive_loader import RecursiveLoader
from parsers.base import ParseResult


class _BoundaryParser:
    def __init__(self) -> None:
        self.parsed_doc_ids: list[str] = []

    def parse(self, doc):
        self.parsed_doc_ids.append(doc.doc_id)
        doc.source_hash = f"sha256:{doc.doc_id}"
        return ParseResult(
            doc=doc,
            elements=[
                ParsedElement(
                    doc_id=doc.doc_id,
                    doc_version=doc.version,
                    sequence_order=1,
                    element_type=ElementType.paragraph,
                    text=f"{doc.doc_id} 内容",
                )
            ],
        )


class _DuplicateHashParser:
    def __init__(self) -> None:
        self.parsed_doc_ids: list[str] = []

    def parse(self, doc):
        self.parsed_doc_ids.append(doc.doc_id)
        doc.source_hash = "sha256:same-child"
        return ParseResult(
            doc=doc,
            elements=[
                ParsedElement(
                    doc_id=doc.doc_id,
                    doc_version=doc.version,
                    sequence_order=1,
                    element_type=ElementType.paragraph,
                    text=f"{doc.doc_id} 内容",
                )
            ],
        )


def _root_doc() -> Document:
    return Document(
        doc_id="doc_root",
        title="Root",
        source_type="markdown",
        source_uri="memory://root",
        source_hash="sha256:root",
    )


def _embedded_element(embedded_doc_id: str = "doc_child") -> ParsedElement:
    return ParsedElement(
        doc_id="doc_root",
        sequence_order=1,
        element_type=ElementType.paragraph,
        text="嵌入入口",
        embedded_doc_id=embedded_doc_id,
    )


def test_load_embedded_respects_max_depth_without_reparsing_root():
    parser = _BoundaryParser()
    loader = RecursiveLoader(parser.parse, max_depth=0)

    docs, elements = loader.load_embedded(_root_doc(), [_embedded_element()])

    assert parser.parsed_doc_ids == []
    assert len(docs) == 1
    assert docs[0].doc_id == "doc_child"
    assert docs[0].metadata["skipped_reason"] == "max_depth_exceeded"
    assert elements == []


def test_load_embedded_counts_root_elements_for_max_elements(caplog):
    parser = _BoundaryParser()
    loader = RecursiveLoader(parser.parse, max_elements=1)
    root_elements = [
        _embedded_element("doc_child_a"),
        _embedded_element("doc_child_b"),
    ]

    with caplog.at_level(logging.WARNING):
        loader.load_embedded(_root_doc(), root_elements)

    assert any("Max elements 1 exceeded" in record.message for record in caplog.records)


def test_load_embedded_skips_duplicate_hash_after_parse():
    parser = _DuplicateHashParser()
    loader = RecursiveLoader(parser.parse)
    root_elements = [
        _embedded_element("doc_child_a"),
        _embedded_element("doc_child_b"),
    ]

    docs, elements = loader.load_embedded(_root_doc(), root_elements)

    assert parser.parsed_doc_ids == ["doc_child_a", "doc_child_b"]
    assert [doc.doc_id for doc in docs] == ["doc_child_a", "doc_child_b"]
    assert docs[1].metadata["skipped_reason"] == "duplicated_document"
    assert [el.doc_id for el in elements] == ["doc_child_a"]
