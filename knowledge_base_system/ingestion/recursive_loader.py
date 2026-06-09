import logging
from collections.abc import Callable

from app.core.config import settings
from app.core.models import Document
from parsers.base import ParseResult

logger = logging.getLogger(__name__)

ParseFn = Callable[[Document], ParseResult]


class RecursiveLoader:
    """Load and recursively parse embedded documents with boundary protection."""

    def __init__(
        self,
        parser_fn: ParseFn,
        max_depth: int | None = None,
        max_elements: int | None = None,
    ) -> None:
        self._parse = parser_fn
        self._max_depth = max_depth or settings.max_recursion_depth
        self._max_elements = max_elements or settings.max_elements_per_doc
        self._visited_hashes: set[str] = set()
        self._total_elements = 0

    def load(self, root_doc: Document, raw_content: str = "") -> tuple[list[Document], list]:
        """Entry: parse root doc and all embedded docs recursively.

        Returns (all_docs, all_elements).
        """
        root_doc.metadata["raw_content"] = raw_content
        all_docs: list[Document] = []
        all_elements: list = []
        self._parse_recursive(root_doc, depth=0, all_docs=all_docs, all_elements=all_elements)
        return all_docs, all_elements

    def _parse_recursive(
        self, doc: Document, depth: int, all_docs: list[Document], all_elements: list
    ) -> None:
        if depth > self._max_depth:
            logger.warning("Max depth %d exceeded for %s", self._max_depth, doc.doc_id)
            doc.metadata["skipped_reason"] = "max_depth_exceeded"
            doc.status = "failed"
            all_docs.append(doc)
            return

        if doc.source_hash and doc.source_hash in self._visited_hashes:
            doc.metadata["skipped_reason"] = "duplicated_document"
            doc.status = "failed"
            all_docs.append(doc)
            return

        if doc.source_hash:
            self._visited_hashes.add(doc.source_hash)

        # Parse this document
        result = self._parse(doc)
        elements = result.elements
        self._total_elements += len(elements)

        if self._total_elements > self._max_elements:
            logger.warning("Max elements %d exceeded", self._max_elements)

        doc.status = "active"
        all_docs.append(doc)
        all_elements.extend(elements)

        # Find and recurse into embedded documents
        for el in elements:
            if el.embedded_doc_id:
                child = Document(
                    doc_id=el.embedded_doc_id,
                    title=el.text or "Embedded Document",
                    source_type=doc.source_type,
                    source_uri="",
                    parent_doc_id=doc.doc_id,
                    root_doc_id=doc.root_doc_id or doc.doc_id,
                    ingest_job_id=doc.ingest_job_id,
                    metadata={
                        "embed_path": [doc.doc_id, el.embedded_doc_id],
                        "depth": depth + 1,
                    },
                )
                self._parse_recursive(child, depth + 1, all_docs, all_elements)
