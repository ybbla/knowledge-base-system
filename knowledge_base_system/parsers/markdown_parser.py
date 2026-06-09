import re
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.core.models import (
    Asset,
    AssetType,
    Document,
    ElementType,
    ParsedElement,
    SourceLocation,
    compute_hash,
    new_id,
)
from parsers.base import DocumentParser, ParseResult


class MarkdownParser(DocumentParser):
    """Parse Markdown and plain-text documents into ParsedElements."""

    _SUPPORTED = {"markdown", "md", "txt", "text"}

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self._SUPPORTED

    def parse(self, doc: Document) -> ParseResult:
        md = MarkdownIt("commonmark", {"breaks": True, "html": False})
        md.enable("table")
        content = self._read_content(doc)
        tokens = md.parse(content)
        elements: list[ParsedElement] = []
        assets: list[Asset] = []

        state = _ParseState(doc.doc_id, doc.version)

        for token in tokens:
            self._process_token(token, state, assets)

        elements = state.flush_elements()
        self._link_assets_to_elements(elements, assets)

        # Update document hash
        doc.source_hash = compute_hash(content)

        return ParseResult(doc=doc, elements=elements, assets=assets)

    def _read_content(self, doc: Document) -> str:
        raw = doc.metadata.get("raw_content", "")
        if not raw and doc.source_uri.startswith("file://"):
            import pathlib
            filepath = pathlib.Path(doc.source_uri.replace("file:///", ""))
            if filepath.exists():
                raw = filepath.read_text(encoding="utf-8")
        return raw

    # ── token processing ──────────────────────────────────────────

    def _process_token(
        self, token: Token, state: "_ParseState", assets: list[Asset]
    ) -> None:
        ttype = token.type

        if ttype == "heading_open":
            level = int(token.tag[1])
            state.open_heading(level)

        elif ttype == "heading_close":
            heading_text = state.pop_heading_text()
            state.add_title(heading_text, state.heading_level)

        elif ttype == "paragraph_open":
            # Skip paragraph mode inside table cells and list items
            if not state.in_table_cell and not state.in_list_item:
                state.in_paragraph = True
                state.para_text = ""

        elif ttype == "paragraph_close":
            if state.in_paragraph:
                text = state.para_text.strip()
                if text:
                    state.add_paragraph(text)
                state.in_paragraph = False
                state.para_text = ""

        elif ttype == "inline":
            inline_text = self._render_inline_text(token)
            # Collect image assets
            for child in token.children or []:
                if child.type == "image":
                    asset = self._asset_from_image(child, state)
                    assets.append(asset)
                    state.add_asset_id(asset.asset_id)

            if state.in_heading:
                state.heading_text_parts.append(inline_text)
            elif state.in_table_cell:
                if state._current_row is not None:
                    state._current_row.append(inline_text)
            elif state.in_list_item:
                state._pending_list_text += inline_text
            elif state.in_paragraph:
                state.para_text += inline_text

        elif ttype == "bullet_list_open":
            state.open_list(ordered=False)

        elif ttype == "ordered_list_open":
            state.open_list(ordered=True)

        elif ttype == "list_item_open":
            state.in_list_item = True
            state._pending_list_text = ""

        elif ttype == "list_item_close":
            if state._pending_list_text.strip():
                state.add_list_item(state._pending_list_text.strip())
            state._pending_list_text = ""
            state.in_list_item = False

        elif ttype in ("bullet_list_close", "ordered_list_close"):
            list_el = state.close_list()
            if list_el:
                state.elements.append(list_el)

        elif ttype == "table_open":
            state.open_table()

        elif ttype == "table_close":
            table_el = state.close_table()
            if table_el:
                state.elements.append(table_el)

        elif ttype == "thead_open":
            state.in_thead = True

        elif ttype == "thead_close":
            if state._current_row:
                state.table_headers = state._current_row
                state._current_row = None
            state.in_thead = False

        elif ttype == "tbody_open":
            state.in_tbody = True

        elif ttype == "tbody_close":
            state.in_tbody = False

        elif ttype == "tr_open":
            state._current_row = []

        elif ttype == "tr_close":
            if state._current_row:
                if state.in_thead:
                    state.table_headers = state._current_row
                else:
                    state.table_rows.append(state._current_row)
                state._current_row = None

        elif ttype in ("th_open", "td_open"):
            state.in_table_cell = True

        elif ttype in ("th_close", "td_close"):
            state.in_table_cell = False

        elif ttype == "fence":
            state.add_code(token.content, token.info or "")

        elif ttype == "blockquote_open":
            pass  # treat as paragraph

        elif ttype == "blockquote_close":
            pass

    # ── inline rendering ──────────────────────────────────────────

    def _render_inline_text(self, token: Token) -> str:
        """Extract plain text from an inline token."""
        if not token.children:
            return token.content
        parts: list[str] = []
        for child in token.children:
            if child.type == "text":
                parts.append(child.content)
            elif child.type == "softbreak":
                parts.append(" ")
            elif child.type == "hardbreak":
                parts.append("\n")
            elif child.type == "image":
                alt = ""
                if isinstance(child.attrs, dict):
                    alt = child.attrs.get("alt", "")
                if alt:
                    parts.append(f"[图片: {alt}]")
                else:
                    parts.append("[图片]")
            elif child.type == "link":
                link_text = self._render_inline_text(child) if child.children else ""
                parts.append(link_text)
            elif child.type == "code_inline":
                parts.append(child.content)
            else:
                if child.content:
                    parts.append(child.content)
        return "".join(parts)

    def _asset_from_image(
        self, token: Token, state: "_ParseState"
    ) -> Asset:
        """Create an Asset from a markdown image token."""
        src = ""
        alt = ""
        if isinstance(token.attrs, dict):
            src = token.attrs.get("src", "")
            alt = token.attrs.get("alt", "")

        return Asset(
            doc_id=state.doc_id,
            asset_type=AssetType.image,
            original_uri=src,
            mime_type=self._guess_mime(src),
            metadata={"alt": alt},
        )

    @staticmethod
    def _link_assets_to_elements(
        elements: list[ParsedElement],
        assets: list[Asset],
    ) -> None:
        """Backfill source_element_id after elements have their generated IDs."""
        elements_by_asset_id = {
            asset_id: el.element_id
            for el in elements
            for asset_id in el.asset_ids
        }
        for asset in assets:
            if not asset.source_element_id:
                asset.source_element_id = elements_by_asset_id.get(
                    asset.asset_id, ""
                )

    @staticmethod
    def _guess_mime(uri: str) -> str:
        ext = uri.rsplit(".", 1)[-1].lower() if "." in uri else ""
        mime_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
            "svg": "image/svg+xml",
            "mp4": "video/mp4",
            "webm": "video/webm",
        }
        return mime_map.get(ext, "application/octet-stream")


# ── internal parse state machine ──────────────────────────────────


class _ParseState:
    """Mutable state machine for building elements during token traversal."""

    def __init__(self, doc_id: str, doc_version: int):
        self.doc_id = doc_id
        self.doc_version = doc_version
        self.elements: list[ParsedElement] = []
        self._seq = 0
        self._section_path: list[str] = []

        # heading
        self.heading_level = 0
        self.in_heading = False
        self.heading_text_parts: list[str] = []

        # paragraph
        self.in_paragraph = False
        self.para_text = ""

        # list
        self.in_list = False
        self.in_list_item = False
        self._pending_list_text = ""
        self._list_ordered = False
        self._list_items: list[str] = []
        self._list_seq_start = 0
        self._list_section_path: list[str] = []

        # table
        self.in_table = False
        self.in_thead = False
        self.in_tbody = False
        self.in_table_cell = False
        self.table_headers: list[str] = []
        self.table_rows: list[list[str]] = []
        self._current_row: list[str] | None = None

        # tracking for sequence
        self._tracked_assets: list[str] = []

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def flush_elements(self) -> list[ParsedElement]:
        """Return elements, cleaning up any unclosed state."""
        return self.elements

    # ── heading ───────────────────────────────────────────────────

    def open_heading(self, level: int) -> None:
        self.heading_level = level
        self.in_heading = True
        self.heading_text_parts = []
        # Update section path
        while len(self._section_path) >= level:
            self._section_path.pop()

    def pop_heading_text(self) -> str:
        self.in_heading = False
        return "".join(self.heading_text_parts).strip()

    def add_title(self, text: str, level: int) -> None:
        if not text:
            return
        self._section_path.append(text)
        self.elements.append(
            ParsedElement(
                doc_id=self.doc_id,
                doc_version=self.doc_version,
                sequence_order=self._next_seq(),
                element_type=ElementType.title,
                text=text,
                source_location=SourceLocation(section_path=list(self._section_path)),
                metadata={"heading_level": level},
            )
        )

    # ── paragraph ─────────────────────────────────────────────────

    def add_paragraph(self, text: str) -> None:
        el = ParsedElement(
            doc_id=self.doc_id,
            doc_version=self.doc_version,
            sequence_order=self._next_seq(),
            element_type=ElementType.paragraph,
            text=text,
            source_location=SourceLocation(section_path=list(self._section_path)),
        )
        if self._tracked_assets:
            el.asset_ids = list(self._tracked_assets)
            self._tracked_assets = []
        self.elements.append(el)

    # ── list ──────────────────────────────────────────────────────

    def open_list(self, ordered: bool) -> None:
        self.in_list = True
        self._list_ordered = ordered
        self._list_items = []
        self._list_seq_start = self._seq + 1
        self._list_section_path = list(self._section_path)

    def add_list_item(self, text: str) -> None:
        self._list_items.append(text)

    def close_list(self) -> ParsedElement | None:
        self.in_list = False
        if not self._list_items:
            return None

        container = ParsedElement(
            doc_id=self.doc_id,
            doc_version=self.doc_version,
            sequence_order=self._next_seq(),
            element_type=ElementType.list,
            text="",
            source_location=SourceLocation(section_path=self._list_section_path),
            metadata={"ordered": self._list_ordered},
        )

        for item_text in self._list_items:
            self.elements.append(
                ParsedElement(
                    doc_id=self.doc_id,
                    doc_version=self.doc_version,
                    parent_element_id=container.element_id,
                    sequence_order=self._next_seq(),
                    element_type=ElementType.paragraph,
                    text=item_text,
                    source_location=SourceLocation(section_path=self._list_section_path),
                )
            )
        self._list_items = []
        return container

    # ── code ──────────────────────────────────────────────────────

    def add_code(self, content: str, language: str) -> None:
        self.elements.append(
            ParsedElement(
                doc_id=self.doc_id,
                doc_version=self.doc_version,
                sequence_order=self._next_seq(),
                element_type=ElementType.code,
                text=content,
                source_location=SourceLocation(section_path=list(self._section_path)),
                metadata={"language": language},
            )
        )

    # ── table ─────────────────────────────────────────────────────

    def open_table(self) -> None:
        self.in_table = True
        self.table_headers = []
        self.table_rows = []
        self._current_row = None

    def close_table(self) -> ParsedElement | None:
        self.in_table = False
        if not self.table_rows:
            return None

        structured = {
            "table": {
                "caption": "",
                "headers": self.table_headers,
                "rows": [
                    {
                        "cells": [
                            {"text": cell, "asset_ids": []}
                            for cell in row
                        ]
                    }
                    for row in self.table_rows
                ],
            }
        }

        flat = ""
        if self.table_headers:
            flat += " | ".join(self.table_headers) + "\n"
        for row in self.table_rows:
            flat += " | ".join(row) + "\n"

        return ParsedElement(
            doc_id=self.doc_id,
            doc_version=self.doc_version,
            sequence_order=self._next_seq(),
            element_type=ElementType.table,
            text=flat.strip(),
            structured_data=structured,
            source_location=SourceLocation(section_path=list(self._section_path)),
        )

    # ── assets ────────────────────────────────────────────────────

    def add_asset_id(self, asset_id: str) -> None:
        self._tracked_assets.append(asset_id)
