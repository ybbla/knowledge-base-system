import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

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
from app.core.paths import resolve_file_uri
from parsers.base import DocumentParser, ParseResult


@dataclass
class _AssetRecord:
    asset: Asset
    key: tuple[str, str]


@dataclass
class _ShapeRecord:
    shape: Any
    index: int
    left: int
    top: int
    width: int
    height: int


@dataclass
class _PptxParseState:
    doc_id: str
    doc_version: int
    elements: list[ParsedElement] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    assets_by_key: dict[tuple[str, str], _AssetRecord] = field(default_factory=dict)
    seq: int = 0
    section_path: list[str] = field(default_factory=list)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


class PptxParser(DocumentParser):
    """将 PPTX 演示文稿解析为统一的 ParsedElement 和 Asset。"""

    SUPPORTED_TYPES = {"pptx"}
    VIDEO_URL_RE = re.compile(
        r"https?://[^\s\])<\"']*(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov|\.m4v)[^\s\])<\"']*",
        re.IGNORECASE,
    )
    AUDIO_URL_RE = re.compile(
        r"https?://[^\s\])<\"']*(?:\.mp3|\.wav|\.m4a|\.aac|\.ogg|\.flac)[^\s\])<\"']*",
        re.IGNORECASE,
    )
    HTTP_URL_RE = re.compile(r"https?://[^\s\])<\"']+", re.IGNORECASE)
    TITLE_PLACEHOLDER_TYPES = {"TITLE", "CENTER_TITLE"}
    BODY_PLACEHOLDER_TYPES = {"BODY", "OBJECT", "CONTENT"}
    UNSUPPORTED_SHAPE_TYPES = {
        "CHART",
        "EMBEDDED_OLE_OBJECT",
        "GROUP",
        "LINKED_OLE_OBJECT",
        "MEDIA",
    }

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc: Document) -> ParseResult:
        raw = self._read_content(doc)
        if not raw:
            raise ValueError("PPTX 解析失败：文档内容为空")

        try:
            from pptx import Presentation
        except ImportError as exc:
            raise RuntimeError("PPTX 解析失败：缺少 python-pptx 依赖") from exc

        try:
            presentation = Presentation(io.BytesIO(raw))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            raise ValueError(f"PPTX 解析失败：{exc}") from exc
        except Exception as exc:
            raise ValueError(f"PPTX 解析失败：{exc}") from exc

        if len(presentation.slides) == 0:
            raise ValueError("PPTX 解析失败：未包含可解析幻灯片")

        state = _PptxParseState(doc.doc_id, doc.version)
        for slide_index, slide in enumerate(presentation.slides, start=1):
            self._process_slide(slide, slide_index, state, doc)

        if not state.elements:
            raise ValueError("PPTX 解析失败：未提取到有效内容")

        doc.source_hash = compute_hash(raw)
        return ParseResult(doc=doc, elements=state.elements, assets=state.assets)

    def _read_content(self, doc: Document) -> bytes:
        raw = doc.metadata.get("raw_content", b"")
        if raw:
            return raw.encode("utf-8") if isinstance(raw, str) else raw

        if doc.source_uri.startswith("file://"):
            filepath = resolve_file_uri(doc.source_uri)
            if filepath.exists():
                return filepath.read_bytes()

        return b""

    def _process_slide(
        self,
        slide: Any,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> None:
        shape_records = self._shape_records(slide)
        title_record = self._find_title_shape(shape_records)
        title_text = (
            self._shape_text(title_record.shape)
            if title_record is not None
            else ""
        ) or f"幻灯片 {slide_index}"

        state.section_path = [title_text]
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.title,
                text=title_text,
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={
                    **self._slide_metadata(slide_index),
                    **(
                        self._shape_metadata(title_record)
                        if title_record is not None
                        else {}
                    ),
                    "heading_level": 1,
                    "fallback_title": title_record is None,
                },
            ),
        )

        for record in shape_records:
            if title_record is not None and record.shape is title_record.shape:
                continue
            if self._shape_has_table(record.shape):
                self._add_table(record, slide_index, state, doc)
            elif self._is_picture(record.shape):
                self._add_image(record, slide_index, state, doc)
            elif self._shape_has_text(record.shape):
                self._add_text_shape(record, slide_index, state, doc)
            elif self._is_unsupported_shape(record.shape):
                self._add_unknown(record, slide_index, state)

    def _shape_records(self, slide: Any) -> list[_ShapeRecord]:
        records: list[_ShapeRecord] = []
        for index, shape in enumerate(slide.shapes):
            records.append(
                _ShapeRecord(
                    shape=shape,
                    index=index,
                    left=self._coord(shape, "left"),
                    top=self._coord(shape, "top"),
                    width=self._coord(shape, "width"),
                    height=self._coord(shape, "height"),
                )
            )
        return sorted(records, key=lambda item: (item.top, item.left, item.index))

    def _find_title_shape(self, records: list[_ShapeRecord]) -> _ShapeRecord | None:
        for record in records:
            if not self._shape_has_text(record.shape):
                continue
            if self._placeholder_type_name(record.shape) in self.TITLE_PLACEHOLDER_TYPES:
                if self._shape_text(record.shape):
                    return record

        for record in records:
            if self._shape_has_text(record.shape) and self._shape_text(record.shape):
                return record
        return None

    def _add_text_shape(
        self,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> None:
        paragraphs = self._paragraphs(record.shape)
        if not paragraphs:
            return

        if self._is_list_shape(record.shape, paragraphs):
            container = ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.list,
                text="",
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={
                    **self._slide_metadata(slide_index),
                    **self._shape_metadata(record),
                    "ordered": False,
                },
            )
            self._append_element(state, container)
            for paragraph in paragraphs:
                asset_ids = self._asset_ids_for_text(
                    paragraph["text"],
                    record,
                    slide_index,
                    state,
                    doc,
                )
                self._append_element(
                    state,
                    ParsedElement(
                        doc_id=state.doc_id,
                        doc_version=state.doc_version,
                        parent_element_id=container.element_id,
                        sequence_order=state.next_seq(),
                        element_type=ElementType.paragraph,
                        text=paragraph["text"],
                        asset_ids=asset_ids,
                        source_location=SourceLocation(section_path=list(state.section_path)),
                        metadata={
                            **self._slide_metadata(slide_index),
                            **self._shape_metadata(record),
                            "level": paragraph["level"],
                        },
                    ),
                )
            return

        text = "\n".join(item["text"] for item in paragraphs)
        asset_ids = list(
            dict.fromkeys(
                self._asset_ids_for_text(text, record, slide_index, state, doc)
                + self._asset_ids_for_shape_hyperlinks(record, slide_index, state, doc)
            )
        )
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.paragraph,
                text=text,
                asset_ids=asset_ids,
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={
                    **self._slide_metadata(slide_index),
                    **self._shape_metadata(record),
                },
            ),
        )

    def _add_table(
        self,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> None:
        table = record.shape.table
        rows: list[list[dict[str, Any]]] = []
        asset_ids: list[str] = []
        for row_index, row in enumerate(table.rows, start=1):
            cells = []
            for col_index, cell in enumerate(row.cells, start=1):
                text = self._normalize_text(cell.text)
                cell_asset_ids = self._asset_ids_for_text(
                    text,
                    record,
                    slide_index,
                    state,
                    doc,
                )
                asset_ids.extend(cell_asset_ids)
                cells.append(
                    {
                        "text": text,
                        "asset_ids": cell_asset_ids,
                        "metadata": {
                            "row": row_index,
                            "column": col_index,
                            "slide_index": slide_index,
                            "slide_number": slide_index,
                        },
                    }
                )
            rows.append(cells)

        if not rows:
            return

        headers = [cell["text"] for cell in rows[0]]
        data_rows = [{"cells": row} for row in rows[1:]]
        structured = {
            "table": {
                "caption": "",
                "headers": headers,
                "rows": data_rows,
                "metadata": {
                    **self._slide_metadata(slide_index),
                    **self._shape_metadata(record),
                    "row_count": len(rows),
                    "column_count": len(rows[0]) if rows else 0,
                },
            }
        }
        text_parts = []
        if headers:
            text_parts.append(" | ".join(headers))
        for row in data_rows:
            text_parts.append(" | ".join(cell["text"] for cell in row["cells"]))

        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.table,
                text="\n".join(part for part in text_parts if part.strip()),
                structured_data=structured,
                asset_ids=list(dict.fromkeys(asset_ids)),
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={
                    **self._slide_metadata(slide_index),
                    **self._shape_metadata(record),
                },
            ),
        )

    def _add_image(
        self,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> None:
        image = record.shape.image
        data = image.blob
        content_hash = f"sha256:{hashlib.sha256(data).hexdigest()}"
        filename = image.filename or f"image-{slide_index}-{record.index + 1}.{image.ext}"
        key = ("image", content_hash)
        record_asset = state.assets_by_key.get(key)
        if record_asset is None:
            asset = Asset(
                doc_id=doc.doc_id,
                asset_type=AssetType.image,
                original_uri=f"pptx://{doc.doc_id}/slide/{slide_index}/media/{filename}",
                storage_uri=None,
                mime_type=image.content_type or self._guess_mime(filename, AssetType.image),
                content_hash=content_hash,
                status=AssetStatus.ready,
                extracted_text=None,
                metadata={
                    **self._slide_metadata(slide_index),
                    **self._shape_metadata(record),
                    "file_name": filename,
                    "source": "pptx_image",
                },
            )
            object.__setattr__(asset, "_data", data)
            state.assets.append(asset)
            state.assets_by_key[key] = _AssetRecord(asset=asset, key=key)
        else:
            asset = record_asset.asset

        element_asset_ids = list(
            dict.fromkeys(
                [asset.asset_id]
                + self._asset_ids_for_shape_hyperlinks(record, slide_index, state, doc)
            )
        )
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.image,
                text=f"[图片: {filename}]",
                asset_ids=element_asset_ids,
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={
                    **self._slide_metadata(slide_index),
                    **self._shape_metadata(record),
                    "file_name": filename,
                },
            ),
        )

    def _add_unknown(
        self,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
    ) -> None:
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.unknown,
                text=f"[Unsupported PPTX object: {self._shape_type_name(record.shape)}]",
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={
                    **self._slide_metadata(slide_index),
                    **self._shape_metadata(record),
                },
            ),
        )

    def _asset_ids_for_text(
        self,
        text: str,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> list[str]:
        urls = [match.group(0) for match in self.HTTP_URL_RE.finditer(text or "")]
        return self._asset_ids_for_urls(urls, record, slide_index, state, doc, "pptx_text")

    def _asset_ids_for_shape_hyperlinks(
        self,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> list[str]:
        urls: list[str] = []
        try:
            address = record.shape.click_action.hyperlink.address
            if address:
                urls.append(address)
        except Exception:
            pass

        if self._shape_has_text(record.shape):
            for paragraph in record.shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    try:
                        address = run.hyperlink.address
                    except Exception:
                        address = None
                    if address:
                        urls.append(address)

        return self._asset_ids_for_urls(
            urls,
            record,
            slide_index,
            state,
            doc,
            "pptx_hyperlink",
        )

    def _asset_ids_for_urls(
        self,
        urls: list[str],
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
        source: str,
    ) -> list[str]:
        asset_ids: list[str] = []
        for url in dict.fromkeys(urls):
            asset_type = self._asset_type_for_url(url)
            asset = self._asset_for_url(
                url,
                asset_type,
                state,
                doc,
                {
                    **self._slide_metadata(slide_index),
                    **self._shape_metadata(record),
                    "source": source,
                },
            )
            asset_ids.append(asset.asset_id)
        return asset_ids

    def _asset_for_url(
        self,
        url: str,
        asset_type: AssetType,
        state: _PptxParseState,
        doc: Document,
        metadata: dict[str, Any],
    ) -> Asset:
        key = (asset_type.value, url)
        existing = state.assets_by_key.get(key)
        if existing is not None:
            return existing.asset

        asset = Asset(
            doc_id=doc.doc_id,
            asset_type=asset_type,
            original_uri=url,
            storage_uri=None,
            mime_type=self._guess_mime(url, asset_type),
            status=AssetStatus.ready,
            extracted_text=None,
            metadata=metadata,
        )
        state.assets.append(asset)
        state.assets_by_key[key] = _AssetRecord(asset=asset, key=key)
        return asset

    @staticmethod
    def _append_element(state: _PptxParseState, element: ParsedElement) -> None:
        linked = set(element.asset_ids)
        for record in state.assets_by_key.values():
            if record.asset.asset_id in linked and not record.asset.source_element_id:
                record.asset.source_element_id = element.element_id
        state.elements.append(element)

    def _paragraphs(self, shape: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for paragraph in shape.text_frame.paragraphs:
            text = self._normalize_text(paragraph.text)
            if text:
                items.append({"text": text, "level": getattr(paragraph, "level", 0)})
        return items

    def _is_list_shape(self, shape: Any, paragraphs: list[dict[str, Any]]) -> bool:
        if len(paragraphs) <= 1:
            return False
        if any(item["level"] > 0 for item in paragraphs):
            return True
        return self._placeholder_type_name(shape) in self.BODY_PLACEHOLDER_TYPES

    @staticmethod
    def _shape_has_text(shape: Any) -> bool:
        return bool(getattr(shape, "has_text_frame", False))

    @staticmethod
    def _shape_has_table(shape: Any) -> bool:
        return bool(getattr(shape, "has_table", False))

    def _shape_text(self, shape: Any) -> str:
        if not self._shape_has_text(shape):
            return ""
        return self._normalize_text(shape.text)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"[ \t\r\f\v]+", " ", text or "").strip()

    def _is_picture(self, shape: Any) -> bool:
        if hasattr(shape, "image"):
            return True
        return self._shape_type_name(shape) == "PICTURE"

    def _is_unsupported_shape(self, shape: Any) -> bool:
        return self._shape_type_name(shape) in self.UNSUPPORTED_SHAPE_TYPES

    @staticmethod
    def _shape_type_name(shape: Any) -> str:
        value = getattr(shape, "shape_type", "")
        return getattr(value, "name", str(value)).upper()

    @staticmethod
    def _placeholder_type_name(shape: Any) -> str:
        if not getattr(shape, "is_placeholder", False):
            return ""
        try:
            value = shape.placeholder_format.type
        except Exception:
            return ""
        return getattr(value, "name", str(value)).upper()

    @staticmethod
    def _coord(shape: Any, attr: str) -> int:
        value = getattr(shape, attr, 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _slide_metadata(slide_index: int) -> dict[str, Any]:
        return {"slide_index": slide_index, "slide_number": slide_index}

    def _shape_metadata(self, record: _ShapeRecord) -> dict[str, Any]:
        shape = record.shape
        return {
            "shape_id": getattr(shape, "shape_id", None),
            "shape_name": getattr(shape, "name", ""),
            "shape_type": self._shape_type_name(shape),
            "placeholder_type": self._placeholder_type_name(shape),
            "shape_index": record.index,
            "left": record.left,
            "top": record.top,
            "width": record.width,
            "height": record.height,
        }

    def _is_video_url(self, url: str) -> bool:
        return bool(self.VIDEO_URL_RE.search(url or ""))

    def _is_audio_url(self, url: str) -> bool:
        return bool(self.AUDIO_URL_RE.search(url or ""))

    def _asset_type_for_url(self, url: str) -> AssetType:
        if self._is_video_url(url):
            return AssetType.video
        if self._is_audio_url(url):
            return AssetType.audio
        return AssetType.attachment

    @staticmethod
    def _guess_mime(url: str, asset_type: AssetType) -> str:
        suffix = PurePosixPath(url.split("?", 1)[0]).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".m4v": "video/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".zip": "application/zip",
        }
        if suffix in mime_map:
            return mime_map[suffix]
        if asset_type == AssetType.image:
            return "image/*"
        if asset_type == AssetType.video:
            return "video/*"
        if asset_type == AssetType.audio:
            return "audio/*"
        return "application/octet-stream"
