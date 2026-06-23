"""PPTX 演示文稿解析器。

使用 python-pptx 将 .pptx 文件解析为统一的 ParsedElement 和 Asset，
支持幻灯片标题、文本形状、列表、表格、图片和超链接资源的提取。
"""

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
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
from parsers.base import DocumentParser, ParseResult
from parsers.utils import classify_link, guess_mime


@dataclass
class _AssetRecord:
    """内部 Asset 记录，含去重用的查询键。"""
    asset: Asset
    key: tuple[str, str]


@dataclass
class _ShapeRecord:
    """形状记录，含排序用的位置和索引信息。"""
    shape: Any
    index: int
    left: int
    top: int
    width: int
    height: int


@dataclass
class _PptxParseState:
    """PPTX 解析过程中的可变状态。"""
    doc_id: str
    doc_version: int
    elements: list[ParsedElement] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    assets_by_key: dict[tuple[str, str], _AssetRecord] = field(default_factory=dict)
    seq: int = 0
    section_path: list[str] = field(default_factory=list)
    link_urls: list[str] = field(default_factory=list)  # 普通网页链接（与其他解析器一致）

    def next_seq(self) -> int:
        """生成递增的序号。"""
        self.seq += 1
        return self.seq

    def consume_link_urls(self) -> list[str]:
        """消费并清空普通网页链接列表。"""
        result = list(self.link_urls)
        self.link_urls = []
        return result


class PptxParser(DocumentParser):
    """将 PPTX 演示文稿解析为统一的 ParsedElement 和 Asset。

    支持的 source_type：pptx。
    按幻灯片顺序处理形状，识别标题占位符、列表、表格和嵌入图片。
    """

    SUPPORTED_TYPES = {"pptx"}
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

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """主解析入口：将 PPTX 文档解析为结构化元素和资源列表。"""
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not content:
            raise ValueError("PPTX 解析失败：文档内容为空")

        try:
            from pptx import Presentation
        except ImportError as exc:
            raise RuntimeError("PPTX 解析失败：缺少 python-pptx 依赖") from exc

        try:
            presentation = Presentation(io.BytesIO(content))
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

        doc.source_hash = compute_hash(content)
        return ParseResult(doc=doc, elements=state.elements, assets=state.assets)

    def _process_slide(
        self,
        slide: Any,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> None:
        """处理单个幻灯片：识别标题，然后按顺序处理其余形状。"""
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
        """按 (top, left, index) 排序收集幻灯片中的所有形状。"""
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
        """定位幻灯片的标题形状。

        优先匹配 TITLE/CENTER_TITLE 占位符类型，其次选首个有文本的形状。
        """
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
        """处理文本形状：区分列表和普通段落。"""
        paragraphs = self._paragraphs(record.shape)
        if not paragraphs:
            return

        if self._is_list_shape(record.shape, paragraphs):
            # 收集整个形状的超链接（形状级 + 运行级），关联到列表容器
            shape_links = self._collect_shape_links(record, slide_index, state, doc)
            container = ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.list,
                text="",
                structured_data={"links": shape_links} if shape_links else None,
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={
                    **self._slide_metadata(slide_index),
                    **self._shape_metadata(record),
                    "ordered": False,
                },
            )
            self._append_element(state, container)
            for paragraph in paragraphs:
                asset_ids = list(
                    dict.fromkeys(
                        self._asset_ids_for_text(
                            paragraph["text"], record, slide_index, state, doc,
                        )
                        + self._asset_ids_for_shape_hyperlinks(
                            record, slide_index, state, doc,
                        )
                    )
                )
                state.consume_link_urls()  # 列表项中的普通网页链接丢弃（与 DOCX 一致）
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
        link_urls = state.consume_link_urls()
        links = self._collect_shape_links(record, slide_index, state, doc)
        metadata = {
            **self._slide_metadata(slide_index),
            **self._shape_metadata(record),
        }
        if link_urls:
            metadata["link_urls"] = link_urls
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.paragraph,
                text=text,
                asset_ids=asset_ids,
                structured_data={"links": links} if links else None,
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata=metadata,
            ),
        )

    def _add_table(
        self,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> None:
        """处理表格形状，生成结构化表格元素。

        处理流程：
        1. 遍历单元格，通过文本正则提取 URL 并创建 Asset
        2. 收集表格形状级超链接（click_action）和各单元格运行级超链接
        3. 将普通网页链接记录到 metadata.link_urls
        4. 将链接信息写入 structured_data.links
        """
        table = record.shape.table
        rows: list[list[dict[str, Any]]] = []
        asset_ids: list[str] = []
        link_urls: list[str] = []
        table_links: list[dict[str, str]] = []

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
                # 收集本单元格产生的普通网页链接
                link_urls.extend(state.consume_link_urls())
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

        # ── 收集表格内运行级超链接 ──
        table_hyperlink_urls: list[str] = []
        for row in table.rows:
            for cell in row.cells:
                try:
                    tf = cell.text_frame
                except Exception:
                    continue
                for para in tf.paragraphs:
                    for run in para.runs:
                        try:
                            addr = run.hyperlink.address
                        except Exception:
                            addr = None
                        if addr:
                            table_hyperlink_urls.append(addr)
                            run_text = self._normalize_text(run.text)
                            if run_text:
                                table_links.append({
                                    "text": run_text,
                                    "url": addr,
                                    "link_type": classify_link(addr),
                                })

        # ── 单元格文本中内嵌的 URL（正则匹配，非超链接） ──
        seen_hyperlink_urls = set(table_hyperlink_urls)
        for row in table.rows:
            for cell in row.cells:
                text = self._normalize_text(cell.text)
                for match in self.HTTP_URL_RE.finditer(text):
                    url = match.group(0)
                    if url not in seen_hyperlink_urls:
                        seen_hyperlink_urls.add(url)
                        kind = classify_link(url)
                        if kind != "url":
                            table_hyperlink_urls.append(url)
                        table_links.append({
                            "text": url,
                            "url": url,
                            "link_type": kind,
                        })

        # ── 形状级超链接 ──
        try:
            addr = record.shape.click_action.hyperlink.address
        except Exception:
            addr = None
        if addr:
            table_hyperlink_urls.append(addr)
            table_links.append({
                "text": self._shape_text(record.shape),
                "url": addr,
                "link_type": classify_link(addr),
            })

        # 创建超链接 Asset，同时普通网页链接进入 state.link_urls
        table_asset_ids = self._asset_ids_for_urls(
            table_hyperlink_urls,
            record, slide_index, state, doc,
            "pptx_table_hyperlink",
        )
        asset_ids.extend(table_asset_ids)

        # 收尾：合并本表格产生的所有普通网页链接
        link_urls.extend(state.consume_link_urls())

        headers = [cell["text"] for cell in rows[0]]
        data_rows = [{"cells": row} for row in rows[1:]]
        structured: dict[str, Any] = {
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
        if table_links:
            structured["links"] = table_links

        text_parts = []
        if headers:
            text_parts.append(" | ".join(headers))
        for row in data_rows:
            text_parts.append(" | ".join(cell["text"] for cell in row["cells"]))

        metadata = {
            **self._slide_metadata(slide_index),
            **self._shape_metadata(record),
        }
        if link_urls:
            metadata["link_urls"] = link_urls

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
                metadata=metadata,
            ),
        )

    def _add_image(
        self,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> None:
        """处理图片形状，创建 image Asset 和对应的 ParsedElement。"""
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
                mime_type=image.content_type or guess_mime(filename, AssetType.image),
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
        links = self._collect_shape_links(
            record, slide_index, state, doc, image_filename=filename,
        )
        state.consume_link_urls()  # 图片元素不记录 link_urls（链接已在 structured_data 中）
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.image,
                text=f"[图片: {filename}]",
                asset_ids=element_asset_ids,
                structured_data={"links": links} if links else None,
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
        """为不支持的形状类型（图表、OLE 等）添加占位元素。"""
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.unknown,
                text=f"[不支持的 PPTX 对象: {self._shape_type_name(record.shape)}]",
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
        """从文本中识别 URL 并创建对应的 Asset。"""
        urls = [match.group(0) for match in self.HTTP_URL_RE.finditer(text or "")]
        return self._asset_ids_for_urls(urls, record, slide_index, state, doc, "pptx_text")

    def _asset_ids_for_shape_hyperlinks(
        self,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
    ) -> list[str]:
        """从形状和文本运行中的超链接创建 Asset。"""
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

    def _collect_shape_links(
        self,
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
        image_filename: str = "",
    ) -> list[dict[str, str]]:
        """收集形状中所有超链接的 {text, url, link_type} 信息。

        参数：
            record: 形状记录。
            slide_index: 幻灯片索引。
            state: 解析状态。
            doc: 文档对象。
            image_filename: 图片形状的文件名，用于 _shape_text() 返回空时
                           作为链接文字 fallback。

        返回：
            链接信息列表，每项包含 text、url、link_type 三个字段。
        """
        links: list[dict[str, str]] = []

        # ── 形状级超链接（click_action.hyperlink） ──
        try:
            address = record.shape.click_action.hyperlink.address
        except Exception:
            address = None
        if address:
            text = self._shape_text(record.shape) or image_filename
            if text:
                links.append({
                    "text": text,
                    "url": address,
                    "link_type": classify_link(address),
                })

        # ── 运行级超链接（run.hyperlink） ──
        if self._shape_has_text(record.shape):
            for paragraph in record.shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    try:
                        address = run.hyperlink.address
                    except Exception:
                        address = None
                    if address:
                        run_text = self._normalize_text(run.text)
                        if run_text:
                            links.append({
                                "text": run_text,
                                "url": address,
                                "link_type": classify_link(address),
                            })

        return links

    def _asset_ids_for_urls(
        self,
        urls: list[str],
        record: _ShapeRecord,
        slide_index: int,
        state: _PptxParseState,
        doc: Document,
        source: str,
    ) -> list[str]:
        """为一批 URL 创建 Asset 并返回 ID 列表。

        普通网页链接（classify_link 返回 "url"）不创建 Asset，
        但记录到 state.link_urls，与其他解析器行为一致。
        """
        asset_ids: list[str] = []
        for url in dict.fromkeys(urls):
            asset_type = self._asset_type_for_url(url)
            if asset_type is None:
                state.link_urls.append(url)
                continue
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
        """创建或查找已有 Asset（按 URL + 类型去重）。"""
        key = (asset_type.value, url)
        existing = state.assets_by_key.get(key)
        if existing is not None:
            return existing.asset

        asset = Asset(
            doc_id=doc.doc_id,
            asset_type=asset_type,
            original_uri=url,
            storage_uri=None,
            mime_type=guess_mime(url, asset_type),
            status=AssetStatus.ready,
            extracted_text=None,
            metadata=metadata,
        )
        state.assets.append(asset)
        state.assets_by_key[key] = _AssetRecord(asset=asset, key=key)
        return asset

    @staticmethod
    def _append_element(state: _PptxParseState, element: ParsedElement) -> None:
        """添加元素并回链 Asset 的 source_element_id。"""
        linked = set(element.asset_ids)
        for record in state.assets_by_key.values():
            if record.asset.asset_id in linked and not record.asset.source_element_id:
                record.asset.source_element_id = element.element_id
        state.elements.append(element)

    def _paragraphs(self, shape: Any) -> list[dict[str, Any]]:
        """提取形状中的段落文本及缩进级别。"""
        items: list[dict[str, Any]] = []
        for paragraph in shape.text_frame.paragraphs:
            text = self._normalize_text(paragraph.text)
            if text:
                items.append({"text": text, "level": getattr(paragraph, "level", 0)})
        return items

    def _is_list_shape(self, shape: Any, paragraphs: list[dict[str, Any]]) -> bool:
        """判断形状内容是否为列表格式。

        依据：多段落 + 有缩进层级，或占位符类型为 BODY。
        """
        if len(paragraphs) <= 1:
            return False
        if any(item["level"] > 0 for item in paragraphs):
            return True
        return self._placeholder_type_name(shape) in self.BODY_PLACEHOLDER_TYPES

    @staticmethod
    def _shape_has_text(shape: Any) -> bool:
        """判断形状是否包含文本框。"""
        return bool(getattr(shape, "has_text_frame", False))

    @staticmethod
    def _shape_has_table(shape: Any) -> bool:
        """判断形状是否包含表格。"""
        return bool(getattr(shape, "has_table", False))

    def _shape_text(self, shape: Any) -> str:
        """获取形状的纯文本内容（经空白归一化）。"""
        if not self._shape_has_text(shape):
            return ""
        return self._normalize_text(shape.text)

    @staticmethod
    def _normalize_text(text: str) -> str:
        """将连续空白字符归一化为单个空格并去除首尾空白。"""
        return re.sub(r"[ \t\r\f\v]+", " ", text or "").strip()

    def _is_picture(self, shape: Any) -> bool:
        """判断形状是否为图片。"""
        if hasattr(shape, "image"):
            return True
        return self._shape_type_name(shape) == "PICTURE"

    def _is_unsupported_shape(self, shape: Any) -> bool:
        """判断形状是否为不支持的类型（图表、OLE 等）。"""
        return self._shape_type_name(shape) in self.UNSUPPORTED_SHAPE_TYPES

    @staticmethod
    def _shape_type_name(shape: Any) -> str:
        """获取形状类型名称（大写字符串）。"""
        value = getattr(shape, "shape_type", "")
        return getattr(value, "name", str(value)).upper()

    @staticmethod
    def _placeholder_type_name(shape: Any) -> str:
        """获取占位符类型名称（大写字符串）。"""
        if not getattr(shape, "is_placeholder", False):
            return ""
        try:
            value = shape.placeholder_format.type
        except Exception:
            return ""
        return getattr(value, "name", str(value)).upper()

    @staticmethod
    def _coord(shape: Any, attr: str) -> int:
        """安全获取形状的 EMU 坐标整数值。"""
        value = getattr(shape, attr, 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _slide_metadata(slide_index: int) -> dict[str, Any]:
        """生成幻灯片元数据字典。"""
        return {"slide_index": slide_index, "slide_number": slide_index}

    def _shape_metadata(self, record: _ShapeRecord) -> dict[str, Any]:
        """生成形状元数据字典（ID、名称、类型、位置等）。"""
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

    def _asset_type_for_url(self, url: str) -> AssetType | None:
        """根据 URL 模式判断资源类型（使用公共 classify_link 分类）。

        返回 AssetType 用于创建 Asset；普通网页链接返回 None，不创建 Asset。
        """
        kind = classify_link(url)
        return {
            "image": AssetType.image_link,
            "video": AssetType.video_link,
            "audio": AssetType.video_link,
            "document": AssetType.document_link,
        }.get(kind)  # "url" 不在映射中 → 返回 None

