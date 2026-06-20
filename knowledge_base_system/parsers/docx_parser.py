import hashlib
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from app.core.paths import resolve_file_uri
from app.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    Document,
    ElementType,
    ParsedElement,
    SourceLocation,
    compute_hash,
)
from parsers.base import DocumentParser, ParseResult

logger = logging.getLogger(__name__)


class DocxParser(DocumentParser):
    """Parse DOCX documents into ParsedElements and Assets."""

    SUPPORTED_TYPES = {"docx"}
    VIDEO_URL_RE = re.compile(
        r"https?://[^\s\])<\"']*(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov|\.m4v)[^\s\])<\"']*",
        re.IGNORECASE,
    )

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc: Document) -> ParseResult:
        raw = self._read_content(doc)
        docx = DocxDocument(io.BytesIO(raw))
        state = _DocxParseState(doc.doc_id, doc.version)

        # Walk body elements in order
        for child in docx.element.body:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "p":
                self._process_paragraph(child, docx, state)
            elif tag == "tbl":
                self._process_table(child, docx, state)

        elements = state.flush_elements()

        # Extract images from zip
        assets = self._extract_images(doc, state._image_counter, elements)
        assets.extend(self._extract_videos(doc, elements))

        doc.source_hash = compute_hash(raw)

        return ParseResult(doc=doc, elements=elements, assets=assets)

    def _read_content(self, doc: Document) -> bytes:
        raw = doc.metadata.get("raw_content", "")
        if raw:
            if isinstance(raw, str):
                return raw.encode("utf-8")
            return raw

        if doc.source_uri.startswith("file://"):
            filepath = resolve_file_uri(doc.source_uri)
            if filepath.exists():
                return filepath.read_bytes()

        return b""

    # ── paragraph processing ───────────────────────────────────────

    def _process_paragraph(
        self, p_el, docx: DocxDocument, state: "_DocxParseState"
    ) -> None:
        """Process a w:p element (paragraph)."""
        # Get style name
        style_name = ""
        is_list = False
        pPr = p_el.find(qn("w:pPr"))
        if pPr is not None:
            pStyle = pPr.find(qn("w:pStyle"))
            if pStyle is not None:
                style_name = pStyle.get(qn("w:val"), "")
                is_list = style_name.lower().startswith("list")
            is_list = is_list or pPr.find(qn("w:numPr")) is not None

        # Extract text
        text = "".join(
            node.text or ""
            for node in p_el.iter()
            if node.tag == qn("w:t")
        )
        has_unknown_object = self._has_unsupported_object(p_el)

        if not text.strip():
            if has_unknown_object:
                state.add_unknown("[Unsupported embedded DOCX object]")
            # Empty paragraph — skip unless it's just whitespace
            return

        # Detect heading by style name
        heading_match = None
        if style_name.startswith("Heading") or style_name.startswith("heading"):
            level_str = style_name.replace("Heading", "").replace("heading", "").strip()
            try:
                heading_match = int(level_str)
            except ValueError:
                heading_match = None

        if heading_match is not None:
            state.add_title(text, heading_match)
        else:
            # Check paragraph style in docx styles
            try:
                for style in docx.styles:
                    if style.style_id == style_name and style.type == WD_STYLE_TYPE.PARAGRAPH:
                        if style.name and style.name.lower().startswith("heading"):
                            level_str = style.name.lower().replace("heading", "").strip()
                            try:
                                heading_match = int(level_str)
                                state.add_title(text, heading_match)
                            except ValueError:
                                pass
                            break
            except Exception:
                pass

        if heading_match is None and is_list:
            state.add_list_item(text)
        elif heading_match is None:
            state.add_paragraph(text)

        if has_unknown_object:
            state.add_unknown("[Unsupported embedded DOCX object]")

    # ── table processing ────────────────────────────────────────────

    def _process_table(
        self, tbl_el, docx: DocxDocument, state: "_DocxParseState"
    ) -> None:
        """Process a w:tbl element (table)."""
        rows_data: list[list[str]] = []
        headers: list[str] = []
        vertical_merges: dict[int, str] = {}

        for i, tr in enumerate(tbl_el.findall(qn("w:tr"))):
            cells: list[str] = []
            col_idx = 0
            for tc in tr.findall(qn("w:tc")):
                cell_text = ""
                for node in tc.iter():
                    if node.tag == qn("w:t") and node.text:
                        cell_text += node.text
                cell_text = cell_text.strip()

                span = 1
                vmerge_val = None
                tcPr = tc.find(qn("w:tcPr"))
                if tcPr is not None:
                    grid_span = tcPr.find(qn("w:gridSpan"))
                    if grid_span is not None:
                        try:
                            span = max(1, int(grid_span.get(qn("w:val"), "1")))
                        except ValueError:
                            span = 1
                    vmerge = tcPr.find(qn("w:vMerge"))
                    if vmerge is not None:
                        vmerge_val = vmerge.get(qn("w:val")) or "continue"

                if vmerge_val == "continue":
                    cell_text = vertical_merges.get(col_idx, cell_text)
                elif vmerge_val == "restart":
                    for offset in range(span):
                        vertical_merges[col_idx + offset] = cell_text

                for offset in range(span):
                    if vmerge_val == "continue":
                        cells.append(vertical_merges.get(col_idx + offset, cell_text))
                    else:
                        cells.append(cell_text)
                col_idx += span

            if i == 0:
                headers = cells
            else:
                rows_data.append(cells)

        if not rows_data:
            return

        structured = {
            "table": {
                "caption": "",
                "headers": headers,
                "rows": [
                    {
                        "cells": [
                            {"text": cell, "asset_ids": []}
                            for cell in row
                        ]
                    }
                    for row in rows_data
                ],
            }
        }

        # Build flat text representation
        flat_parts = []
        if headers:
            flat_parts.append(" | ".join(headers))
        for row in rows_data:
            flat_parts.append(" | ".join(row))

        el = ParsedElement(
            doc_id=state.doc_id,
            doc_version=state.doc_version,
            parent_element_id=None,
            sequence_order=state._next_seq(),
            element_type=ElementType.table,
            text="\n".join(flat_parts),
            structured_data=structured,
            source_location=SourceLocation(section_path=list(state._section_path)),
        )
        state.elements.append(el)

    # ── image extraction ────────────────────────────────────────────

    def _extract_images(
        self,
        doc: Document,
        image_counter: int,
        elements: list[ParsedElement],
    ) -> list[Asset]:
        """Extract images from the docx zip's word/media/ directory."""
        assets: list[Asset] = []
        raw = doc.metadata.get("raw_content", "")
        zip_source: bytes | Path | None = None
        if raw:
            zip_source = raw.encode("utf-8") if isinstance(raw, str) else raw
        elif doc.source_uri.startswith("file://"):
            filepath = resolve_file_uri(doc.source_uri)
            if filepath.exists():
                zip_source = filepath

        if zip_source is None:
            return assets

        try:
            with zipfile.ZipFile(
                io.BytesIO(zip_source) if isinstance(zip_source, bytes) else zip_source
            ) as zf:
                media_files = [
                    name for name in zf.namelist()
                    if name.startswith("word/media/") and not name.endswith("/")
                ]
                for idx, name in enumerate(media_files):
                    data = zf.read(name)
                    content_hash = hashlib.sha256(data).hexdigest()
                    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "bin"
                    mimetype_map = {
                        "png": "image/png", "jpg": "image/jpeg",
                        "jpeg": "image/jpeg", "gif": "image/gif",
                        "webp": "image/webp", "bmp": "image/bmp",
                        "svg": "image/svg+xml",
                    }

                    asset = Asset(
                        doc_id=doc.doc_id,
                        source_element_id="",
                        asset_type=AssetType.image,
                        original_uri=f"docx://{doc.doc_id}/media/image{idx+1}.{ext}",
                        mime_type=mimetype_map.get(ext, "application/octet-stream"),
                        content_hash=f"sha256:{content_hash}",
                        status=AssetStatus.ready,
                        storage_uri=None,
                        extracted_text=None,
                        metadata={"width": None, "height": None},
                    )
                    object.__setattr__(asset, "_data", data)
                    # Create an image ParsedElement for each image
                    el = ParsedElement(
                        doc_id=doc.doc_id,
                        doc_version=doc.version,
                        parent_element_id=None,
                        sequence_order=max(
                            (item.sequence_order for item in elements),
                            default=image_counter,
                        ) + idx + 1,
                        element_type=ElementType.image,
                        text=f"[图片: {name.split('/')[-1]}]",
                        asset_ids=[asset.asset_id],
                        source_location=SourceLocation(),
                    )
                    asset.source_element_id = el.element_id
                    assets.append(asset)
                    elements.append(el)
        except (zipfile.BadZipFile, KeyError) as exc:
            logger.warning("Failed to extract images from docx: %s", exc)

        return assets

    def _extract_videos(
        self,
        doc: Document,
        elements: list[ParsedElement],
    ) -> list[Asset]:
        """从段落文本中识别视频链接并创建 ready Asset。"""
        assets: list[Asset] = []
        seen: set[str] = set()
        for el in list(elements):
            for match in self.VIDEO_URL_RE.finditer(el.text or ""):
                url = match.group(0)
                if url in seen:
                    continue
                seen.add(url)
                ext = url.lower().split("?", 1)[0].rsplit(".", 1)[-1]
                mime = {
                    "mp4": "video/mp4",
                    "webm": "video/webm",
                    "mov": "video/quicktime",
                    "m4v": "video/mp4",
                }.get(ext, "video/*")
                asset = Asset(
                    doc_id=doc.doc_id,
                    source_element_id=el.element_id,
                    asset_type=AssetType.video,
                    original_uri=url,
                    storage_uri=None,
                    mime_type=mime,
                    extracted_text=None,
                    metadata={"source": "video_link"},
                )
                video_el = ParsedElement(
                    doc_id=doc.doc_id,
                    doc_version=doc.version,
                    sequence_order=max(
                        (item.sequence_order for item in elements),
                        default=0,
                    ) + 1,
                    element_type=ElementType.video,
                    text=f"[视频: {url}]",
                    asset_ids=[asset.asset_id],
                    source_location=el.source_location,
                )
                elements.append(video_el)
                assets.append(asset)
        return assets

    def _has_unsupported_object(self, p_el) -> bool:
        unsupported_tags = {"object", "oleobject", "control"}
        for node in p_el.iter():
            local = node.tag.split("}")[-1].lower() if "}" in node.tag else node.tag.lower()
            if local in unsupported_tags:
                return True
        return False


# ── internal parse state ──────────────────────────────────────────


class _DocxParseState:
    """Mutable state for building elements during DOCX traversal."""

    def __init__(self, doc_id: str, doc_version: int):
        self.doc_id = doc_id
        self.doc_version = doc_version
        self.elements: list[ParsedElement] = []
        self._seq = 0
        self._section_path: list[str] = []
        self._image_counter = 0
        self._current_list_id: str | None = None

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def flush_elements(self) -> list[ParsedElement]:
        return self.elements

    def add_title(self, text: str, level: int) -> None:
        if not text:
            return
        self._current_list_id = None
        while len(self._section_path) >= level:
            self._section_path.pop()
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

    def add_paragraph(self, text: str) -> None:
        self._current_list_id = None
        self.elements.append(
            ParsedElement(
                doc_id=self.doc_id,
                doc_version=self.doc_version,
                sequence_order=self._next_seq(),
                element_type=ElementType.paragraph,
                text=text,
                source_location=SourceLocation(section_path=list(self._section_path)),
            )
        )

    def add_list_item(self, text: str) -> None:
        if self._current_list_id is None:
            list_el = ParsedElement(
                doc_id=self.doc_id,
                doc_version=self.doc_version,
                sequence_order=self._next_seq(),
                element_type=ElementType.list,
                text="",
                source_location=SourceLocation(section_path=list(self._section_path)),
            )
            self.elements.append(list_el)
            self._current_list_id = list_el.element_id

        self.elements.append(
            ParsedElement(
                doc_id=self.doc_id,
                doc_version=self.doc_version,
                parent_element_id=self._current_list_id,
                sequence_order=self._next_seq(),
                element_type=ElementType.paragraph,
                text=text,
                source_location=SourceLocation(section_path=list(self._section_path)),
            )
        )

    def add_unknown(self, text: str) -> None:
        self.elements.append(
            ParsedElement(
                doc_id=self.doc_id,
                doc_version=self.doc_version,
                sequence_order=self._next_seq(),
                element_type=ElementType.unknown,
                text=text,
                source_location=SourceLocation(section_path=list(self._section_path)),
            )
        )
