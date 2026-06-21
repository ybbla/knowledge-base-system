"""Markdown 和纯文本文档解析器。

使用 markdown-it 解析 Markdown 文档，提取标题、段落、列表、表格、代码块等
结构化元素，同时识别图片和视频资源。
"""

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token

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


class MarkdownParser(DocumentParser):
    """将 Markdown 和纯文本文档解析为 ParsedElement 和 Asset。

    支持的 source_type：markdown、md、txt、text。
    """

    SUPPORTED_TYPES = {"markdown", "md", "txt", "text"}
    VIDEO_URL_RE = re.compile(
        r"https?://[^\s\])<\"']*(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov|\.m4v)[^\s\])<\"']*",
        re.IGNORECASE,
    )
    VIDEO_TAG_RE = re.compile(
        r"<video[^>]+src=[\"'](?P<src>[^\"']+)[\"'][^>]*>",
        re.IGNORECASE,
    )
    MD_VIDEO_RE = re.compile(
        r"!\[(?P<alt>[^\]]*video[^\]]*)\]\((?P<src>[^)]+)\)",
        re.IGNORECASE,
    )

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc: Document) -> ParseResult:
        """主解析入口：将 Markdown 文本解析为结构化元素和资源列表。"""
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
        self._extract_video_assets(content, state, elements, assets)
        self._link_assets_to_elements(elements, assets)

        # 更新文档内容哈希
        doc.source_hash = compute_hash(content)

        return ParseResult(doc=doc, elements=elements, assets=assets)

    def _read_content(self, doc: Document) -> str:
        """从 metadata.raw_content 或 file:// URI 读取文档文本。"""
        raw = doc.metadata.get("raw_content", "")
        if not raw and doc.source_uri.startswith("file://"):
            filepath = resolve_file_uri(doc.source_uri)
            if filepath.exists():
                raw = filepath.read_text(encoding="utf-8")
        return raw

    # ── token 遍历处理 ──────────────────────────────────────────

    def _process_token(
        self, token: Token, state: "_ParseState", assets: list[Asset]
    ) -> None:
        """根据 token 类型分发到对应的状态转换方法。"""
        ttype = token.type

        if ttype == "heading_open":
            level = int(token.tag[1])
            state.open_heading(level)

        elif ttype == "heading_close":
            heading_text = state.pop_heading_text()
            state.add_title(heading_text, state.heading_level)

        elif ttype == "paragraph_open":
            # 在表格单元格和列表项内部不启用段落模式
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
            # 收集内嵌图片资源
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
            pass  # 引用的开始，暂视为普通段落处理

        elif ttype == "blockquote_close":
            pass  # 引用的结束

    # ── 内联文本渲染 ──────────────────────────────────────────

    def _render_inline_text(self, token: Token) -> str:
        """从内联 token 中提取纯文本表示。

        对图片、链接等元素生成可读的替代文本。
        """
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
        """从 Markdown 图片 token 创建 Asset 对象。"""
        src = ""
        alt = ""
        if isinstance(token.attrs, dict):
            src = token.attrs.get("src", "")
            alt = token.attrs.get("alt", "")

        asset_type = AssetType.video if self._is_video_link(src, alt) else AssetType.image
        return Asset(
            doc_id=state.doc_id,
            asset_type=asset_type,
            original_uri=src,
            mime_type=self._guess_mime(src),
            status=AssetStatus.ready,
            metadata={"alt": alt},
        )

    def _extract_video_assets(
        self,
        content: str,
        state: "_ParseState",
        elements: list[ParsedElement],
        assets: list[Asset],
    ) -> None:
        """从原始内容中提取视频链接并创建对应的 Asset 和 image/video 类型元素。"""
        seen = {asset.original_uri for asset in assets if asset.asset_type == AssetType.video}
        candidates: list[tuple[str, str]] = []
        candidates.extend((m.group("src"), "video") for m in self.VIDEO_TAG_RE.finditer(content))
        candidates.extend((m.group("src"), m.group("alt")) for m in self.MD_VIDEO_RE.finditer(content))
        candidates.extend((m.group(0), "video") for m in self.VIDEO_URL_RE.finditer(content))

        for src, label in candidates:
            if src in seen:
                continue
            seen.add(src)
            asset = Asset(
                doc_id=state.doc_id,
                asset_type=AssetType.video,
                original_uri=src,
                storage_uri=None,
                mime_type=self._guess_mime(src),
                status=AssetStatus.ready,
                extracted_text=None,
                metadata={"alt": label},
            )
            element = ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state._next_seq(),
                element_type=ElementType.video,
                text=f"[视频: {src}]",
                asset_ids=[asset.asset_id],
                source_location=SourceLocation(),
            )
            asset.source_element_id = element.element_id
            assets.append(asset)
            elements.append(element)

    @classmethod
    def _is_video_link(cls, src: str, alt: str = "") -> bool:
        """判断链接是否为视频资源（基于 alt 文本、URL 模式或文件扩展名）。"""
        return (
            "video" in alt.lower()
            or bool(cls.VIDEO_URL_RE.search(src))
            or src.lower().split("?", 1)[0].endswith((".mp4", ".webm", ".mov", ".m4v"))
        )

    @staticmethod
    def _link_assets_to_elements(
        elements: list[ParsedElement],
        assets: list[Asset],
    ) -> None:
        """在元素获得生成的 ID 后，回填 Asset 的 source_element_id 关联。"""
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
        """根据 URI 扩展名推断 MIME 类型。"""
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


# ── 内部解析状态机 ──────────────────────────────────────────


class _ParseState:
    """Markdown 解析过程中的可变状态，在 token 遍历时逐步构建元素。

    维护当前段落、标题、列表、表格和资源的累积状态。
    """

    def __init__(self, doc_id: str, doc_version: int):
        self.doc_id = doc_id
        self.doc_version = doc_version
        self.elements: list[ParsedElement] = []
        self._seq = 0
        self._section_path: list[str] = []

        # 标题状态
        self.heading_level = 0
        self.in_heading = False
        self.heading_text_parts: list[str] = []

        # 段落状态
        self.in_paragraph = False
        self.para_text = ""

        # 列表状态
        self.in_list = False
        self.in_list_item = False
        self._pending_list_text = ""
        self._list_ordered = False
        self._list_items: list[str] = []
        self._list_seq_start = 0
        self._list_section_path: list[str] = []

        # 表格状态
        self.in_table = False
        self.in_thead = False
        self.in_tbody = False
        self.in_table_cell = False
        self.table_headers: list[str] = []
        self.table_rows: list[list[str]] = []
        self._current_row: list[str] | None = None

        # 资源跟踪
        self._tracked_assets: list[str] = []

    def _next_seq(self) -> int:
        """生成递增的序号。"""
        self._seq += 1
        return self._seq

    def flush_elements(self) -> list[ParsedElement]:
        """完成解析，返回所有累积的元素并清理未关闭的状态。"""
        return self.elements

    # ── 标题 ─────────────────────────────────────────────────

    def open_heading(self, level: int) -> None:
        """开始解析指定层级的标题。"""
        self.heading_level = level
        self.in_heading = True
        self.heading_text_parts = []
        # 更新 section_path，弹出 >= 当前层级的路径
        while len(self._section_path) >= level:
            self._section_path.pop()

    def pop_heading_text(self) -> str:
        """结束标题解析，返回标题文本。"""
        self.in_heading = False
        return "".join(self.heading_text_parts).strip()

    def add_title(self, text: str, level: int) -> None:
        """添加标题元素并按层级更新 section_path。"""
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

    # ── 段落 ─────────────────────────────────────────────────

    def add_paragraph(self, text: str) -> None:
        """添加段落元素，关联之前跟踪的资源 ID。"""
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

    # ── 列表 ─────────────────────────────────────────────────

    def open_list(self, ordered: bool) -> None:
        """开始解析列表容器。"""
        self.in_list = True
        self._list_ordered = ordered
        self._list_items = []
        self._list_seq_start = self._seq + 1
        self._list_section_path = list(self._section_path)

    def add_list_item(self, text: str) -> None:
        """向当前列表追加一项。"""
        self._list_items.append(text)

    def close_list(self) -> ParsedElement | None:
        """关闭列表容器，返回列表容器元素（子项已提前添加到 elements）。"""
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

    # ── 代码块 ──────────────────────────────────────────────

    def add_code(self, content: str, language: str) -> None:
        """添加代码块元素。"""
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

    # ── 表格 ─────────────────────────────────────────────────

    def open_table(self) -> None:
        """开始解析表格。"""
        self.in_table = True
        self.table_headers = []
        self.table_rows = []
        self._current_row = None

    def close_table(self) -> ParsedElement | None:
        """关闭表格，返回包含结构化数据和纯文本的表格元素。"""
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

    # ── 资源 ─────────────────────────────────────────────────

    def add_asset_id(self, asset_id: str) -> None:
        """记录当前段落引用的资源 ID，用于后续关联。"""
        self._tracked_assets.append(asset_id)
