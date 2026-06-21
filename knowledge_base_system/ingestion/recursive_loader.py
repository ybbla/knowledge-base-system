"""递归文档加载器 — 解析嵌入子文档，带深度和元素数量的边界保护。

支持 load（从头解析根文档）和 load_embedded（从已解析元素继续递归）两种入口。
通过 source_hash 去重和最大深度/元素数限制防止无限递归。
"""

import logging
from collections.abc import Callable

from app.core.config import settings
from app.core.models import DocStatus, Document, ParsedElement
from parsers.base import ParseResult

logger = logging.getLogger(__name__)

ParseFn = Callable[[Document], ParseResult]


class RecursiveLoader:
    """递归文档加载器 — 解析嵌入子文档并施加深度/数量边界保护。"""

    def __init__(
        self,
        parser_fn: ParseFn,
        max_depth: int | None = None,
        max_elements: int | None = None,
    ) -> None:
        self._parse = parser_fn
        self._max_depth = (
            settings.max_recursion_depth if max_depth is None else max_depth
        )
        self._max_elements = (
            settings.max_elements_per_doc if max_elements is None else max_elements
        )
        self._visited_hashes: set[str] = set()
        self._total_elements = 0

    def load(self, root_doc: Document, raw_content: str = "") -> tuple[list[Document], list]:
        """入口方法：解析根文档并递归解析所有嵌入子文档。

        返回 (all_docs, all_elements)。
        """
        # 仅在 raw_content 非空或 metadata 中尚无 raw_content 时设置，避免空值覆盖已有数据
        if raw_content or "raw_content" not in root_doc.metadata:
            root_doc.metadata["raw_content"] = raw_content
        all_docs: list[Document] = []
        all_elements: list = []
        self._parse_recursive(root_doc, depth=0, all_docs=all_docs, all_elements=all_elements)
        return all_docs, all_elements

    def load_embedded(
        self,
        root_doc: Document,
        root_elements: list[ParsedElement],
    ) -> tuple[list[Document], list[ParsedElement]]:
        """从已解析的根文档元素继续递归加载嵌入文档。

        根文档本身已经由调用方解析，本方法只返回嵌入文档产生的
        Document 和 ParsedElement，避免根元素被重复送入下游。
        """
        if root_doc.source_hash:
            self._visited_hashes.add(root_doc.source_hash)
        self._total_elements += len(root_elements)
        if self._total_elements > self._max_elements:
            logger.warning("已达到最大元素数 %d，跳过更多递归", self._max_elements)

        all_docs: list[Document] = []
        all_elements: list[ParsedElement] = []
        self._load_embedded_children(
            root_doc,
            root_elements,
            depth=0,
            all_docs=all_docs,
            all_elements=all_elements,
        )
        return all_docs, all_elements

    def _parse_recursive(
        self, doc: Document, depth: int, all_docs: list[Document], all_elements: list
    ) -> None:
        """递归解析单个文档及其嵌入子文档（内部方法）。"""
        if depth > self._max_depth:
            logger.warning("已达到最大递归深度 %d，文档 %s 跳过", self._max_depth, doc.doc_id)
            doc.metadata["skipped_reason"] = "max_depth_exceeded"
            doc.status = DocStatus.failed
            all_docs.append(doc)
            return

        pre_parse_hash = doc.source_hash
        if pre_parse_hash and pre_parse_hash in self._visited_hashes:
            doc.metadata["skipped_reason"] = "duplicated_document"
            doc.status = DocStatus.failed
            all_docs.append(doc)
            return

        if pre_parse_hash:
            self._visited_hashes.add(pre_parse_hash)

        # Parse this document
        result = self._parse(doc)
        doc = result.doc
        post_parse_hash = doc.source_hash
        if (
            post_parse_hash
            and post_parse_hash in self._visited_hashes
            and post_parse_hash != pre_parse_hash
        ):
            doc.metadata["skipped_reason"] = "duplicated_document"
            doc.status = DocStatus.failed
            all_docs.append(doc)
            return
        if post_parse_hash:
            self._visited_hashes.add(post_parse_hash)
        elements = result.elements
        self._total_elements += len(elements)

        if self._total_elements > self._max_elements:
            logger.warning("已达到最大元素数 %d，跳过更多解析", self._max_elements)

        doc.status = "active"
        all_docs.append(doc)
        all_elements.extend(elements)

        # Find and recurse into embedded documents
        self._load_embedded_children(doc, elements, depth, all_docs, all_elements)

    def _load_embedded_children(
        self,
        doc: Document,
        elements: list[ParsedElement],
        depth: int,
        all_docs: list[Document],
        all_elements: list[ParsedElement],
    ) -> None:
        """遍历元素中 embedded_doc_id，递归加载并解析嵌入的子文档。"""
        for el in elements:
            if el.embedded_doc_id:
                child = Document(
                    doc_id=el.embedded_doc_id,
                    title=el.text or "Embedded Document",
                    source_type=doc.source_type,
                    source_uri="",
                    parent_doc_id=doc.doc_id,
                    root_doc_id=doc.root_doc_id or doc.doc_id,
                    metadata={
                        "embed_path": [doc.doc_id, el.embedded_doc_id],
                        "depth": depth + 1,
                    },
                )
                self._parse_recursive(child, depth + 1, all_docs, all_elements)
