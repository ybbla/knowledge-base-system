"""Markdown 和纯文本文档解析器。

使用 markdown-it 解析 Markdown 文档，提取标题、段落、表格三种结构化元素。
列表整体归入段落，代码块忽略。图片、视频、文档、网页链接统一用占位符替换，
资源信息写入元素的 asset_data 字段。
"""

import re
from pathlib import PurePosixPath

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.core.models import (
    Asset,
    AssetData,
    AssetStatus,
    AssetType,
    Document,
    ElementType,
    ParsedElement,
    SourceLocation,
    compute_hash,
)
from parsers.base import DocumentParser, ParseResult
from parsers.utils import (
    classify_link_text,
    is_attachment_url,
    is_video_url,
)

# ── 图片扩展名（用于链接 URL 分类）────────────────────────────────────

_IMAGE_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".tif",
}
_VIDEO_DOMAINS = {"youtube.com", "youtu.be", "bilibili.com", "vimeo.com"}


class MarkdownParser(DocumentParser):
    """将 Markdown 和纯文本文档解析为 ParsedElement 和 Asset。

    支持的 source_type：markdown、md、txt、text。

    输出：
    - elements：仅含 title / paragraph / table 三种元素类型。
    - 元素通过 asset_data 字段记录占位符（如 [image1]）与 URL 的映射。
    - assets：image_link / video_link / document_link 的 Asset 对象（供入库流水线下载上传）。
    """

    SUPPORTED_TYPES = {"markdown", "md", "txt", "text"}

    _VIDEO_FULL_TAG_RE = re.compile(
        r'<video[^>]+src=["\'](?P<src>[^"\']+)["\'][^>]*>.*?</video>',
        re.IGNORECASE | re.DOTALL,
    )

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    # ── 主解析入口 ──────────────────────────────────────────────────

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """主解析入口：将 Markdown 文本解析为元素和资源列表。"""
        if isinstance(content, bytes):
            content = content.decode("utf-8")

        self._init_state()
        self._doc_id = doc.doc_id
        self._doc_version = doc.version
        self._seq = 0
        self._section_path: list[str] = []
        self._elements: list[ParsedElement] = []
        self._assets: list[Asset] = []
        self._counters: dict[str, int] = {}

        content = self._pre_replace_video_tags(content)

        md = MarkdownIt("commonmark", {"breaks": True, "html": False})
        md.enable("table")
        tokens = md.parse(content)
        for token in tokens:
            self._process_token(token)

        self._flush_paragraph()

        # 后处理：将 preplaced 资源回填到包含其占位符的元素，并创建 Asset
        for el in self._elements:
            for ph, (placeholder, rtype, url) in list(self._preplaced_assets.items()):
                if ph in el.text:
                    asset = Asset(
                        doc_id=self._doc_id,
                        asset_type=AssetType(rtype),
                        original_uri=url,
                        status=AssetStatus.ready,
                        metadata={},
                    )
                    self._assets.append(asset)
                    el.asset_data.append(AssetData(placeholder=ph, asset_id=asset.asset_id))
                    # 检查结构化数据中的单元格文本
                    if el.structured_data:
                        for row in el.structured_data.get("table", {}).get("rows", []):
                            for cell in row.get("cells", []):
                                if ph in cell.get("text", ""):
                                    cell.setdefault("asset_data", []).append(
                                        {"placeholder": ph, "asset_id": asset.asset_id}
                                    )
                    del self._preplaced_assets[ph]

        doc.source_hash = compute_hash(content)

        return ParseResult(
            doc=doc,
            elements=self._elements,
            assets=self._assets,
        )

    # ── 资源占位符 ────────────────────────────────────────────────

    def _next_ph(self, rtype: str) -> str:
        """生成递增占位符，如 {{image:1}}、{{doc:2}}、{{web:3}}、{{video:4}}。"""
        self._counters[rtype] = self._counters.get(rtype, 0) + 1
        label_map = {
            "image_link": "image", "video_link": "video",
            "document_link": "doc", "web_link": "web",
            "url": "web",
        }
        return f"{{{{{label_map.get(rtype, 'res')}:{self._counters[rtype]}}}}}"

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _add_asset_data(self, placeholder: str, rtype: str, url: str, display_text: str = "") -> None:
        """记录一条资源到当前段落的 _pending_asset_data，同时创建 Asset。"""
        asset = Asset(
            doc_id=self._doc_id,
            asset_type=AssetType(rtype),
            original_uri=url,
            display_text=display_text,
            status=AssetStatus.ready,
            metadata={"mime_type": guess_mime(url, AssetType(rtype))},
        )
        self._assets.append(asset)
        self._pending_asset_data.append(AssetData(
            placeholder=placeholder, asset_id=asset.asset_id,
        ))

    # ── 预处理：<video> 标签 → 占位符 ───────────────────────────

    def _pre_replace_video_tags(self, content: str) -> str:
        def _replace(m: re.Match) -> str:
            src = m.group("src")
            ph = self._next_ph("video_link")
            # 暂存，等所有元素构建完后按文本匹配回填
            self._preplaced_assets[ph] = (ph, "video_link", src)
            return ph

        new_content = self._VIDEO_FULL_TAG_RE.sub(_replace, content)
        return re.sub(r'\n{3,}', '\n\n', new_content)

    # ── token 分发 ─────────────────────────────────────────────────

    def _process_token(self, token: Token) -> None:
        t = token.type

        if t == "heading_open":
            self._flush_paragraph()
            self._heading_level = int(token.tag[1])

        elif t == "heading_close":
            text = "".join(self._para_parts).strip()
            if text:
                while len(self._section_path) >= self._heading_level:
                    self._section_path.pop()
                self._section_path.append(text)
                self._elements.append(self._make_element(
                    ElementType.title, text,
                    metadata={"heading_level": self._heading_level},
                ))
            self._heading_level = 0
            self._para_parts = []

        elif t == "table_open":
            self._flush_paragraph()
            self._in_table = True
            self._table_headers = []
            self._table_rows = []
            self._current_row = []

        elif t == "table_close":
            self._in_table = False
            self._emit_table()

        elif t == "thead_open":
            self._in_thead = True
        elif t == "thead_close":
            if self._current_row:
                self._table_headers = self._current_row
                self._current_row = []
            self._in_thead = False
        elif t == "tbody_open":
            self._in_tbody = True
        elif t == "tbody_close":
            self._in_tbody = False

        elif t == "tr_open":
            self._current_row = []

        elif t == "tr_close":
            if self._current_row:
                if self._in_thead:
                    self._table_headers = self._current_row
                else:
                    self._table_rows.append(self._current_row)
                self._current_row = []

        elif t in ("th_open", "td_open", "th_close", "td_close"):
            pass

        elif t == "paragraph_open":
            pass

        elif t == "paragraph_close":
            if not self._heading_level and not self._in_table and not self._in_list:
                self._para_parts.append("\n")

        elif t == "inline":
            rendered = self._render_inline(token)
            if self._in_table and self._current_row is not None:
                # 拍平当前单元格的 asset_data 到 cell 里
                cell_asset_data = list(self._pending_asset_data)
                self._pending_asset_data = []
                self._current_row.append((rendered, cell_asset_data))
            elif self._in_list:
                self._list_items[-1] += rendered
            else:
                self._para_parts.append(rendered)

        elif t == "bullet_list_open":
            self._flush_paragraph()
            self._in_list = True
            self._list_items = []

        elif t == "ordered_list_open":
            self._flush_paragraph()
            self._in_list = True
            self._list_items = []

        elif t == "list_item_open":
            self._list_items.append("")

        elif t in ("bullet_list_close", "ordered_list_close"):
            self._in_list = False
            merged = "\n".join(
                f"- {item.strip()}" for item in self._list_items if item.strip()
            )
            if merged.strip():
                self._elements.append(self._make_element(
                    ElementType.paragraph, merged,
                ))
            self._list_items = []

        elif t in ("list_item_close",):
            pass

        elif t == "fence":
            pass

        elif t in ("blockquote_open", "blockquote_close"):
            pass

    # ── 内联渲染 ─────────────────────────────────────────────────

    def _render_inline(self, token: Token) -> str:
        if not token.children:
            return token.content

        parts: list[str] = []
        for child in token.children:
            ctype = child.type

            if ctype == "text":
                if self._in_link:
                    self._link_text_parts.append(child.content)
                else:
                    parts.append(child.content)

            elif ctype == "softbreak":
                (self._link_text_parts if self._in_link else parts).append(" ")

            elif ctype == "hardbreak":
                (self._link_text_parts if self._in_link else parts).append("\n")

            elif ctype == "code_inline":
                (self._link_text_parts if self._in_link else parts).append(child.content)

            elif ctype == "image":
                src = child.attrs.get("src", "") if isinstance(child.attrs, dict) else ""
                alt = child.content or ""
                # 嵌入图片：alt 为空则按文件名后缀判断
                rtype = "video" if self._is_video_link(src, alt) else "image"
                ph = self._next_ph(rtype)
                self._add_asset_data(ph, rtype, src)
                parts.append(ph)

            elif ctype == "link_open":
                self._in_link = True
                self._link_href = (
                    child.attrs.get("href", "")
                    if isinstance(child.attrs, dict) else ""
                )
                self._link_text_parts = []

            elif ctype == "link_close":
                self._in_link = False
                link_text = "".join(self._link_text_parts)
                # 按链接文字后缀分类（非 URL），兜底 web_link
                rtype = classify_link_text(link_text).value
                ph = self._next_ph(rtype)
                self._add_asset_data(ph, rtype, self._link_href, display_text=link_text)
                # 链接文字被占位符替换
                parts.append(ph)
                self._link_text_parts = []

            else:
                if self._in_link:
                    self._link_text_parts.append(child.content or "")
                elif child.content:
                    parts.append(child.content)

        return "".join(parts)

    # ── 链接分类 ────────────────────────────────────────────────

    @staticmethod
    def _classify_link_type(href: str) -> str:
        href_lower = href.lower()
        for d in _VIDEO_DOMAINS:
            if d in href_lower:
                return "video_link"
        suffix = PurePosixPath(href.split("?", 1)[0]).suffix.lower()
        if suffix in _IMAGE_EXTENSIONS:
            return "image_link"
        if suffix in {".mp4", ".webm", ".mov", ".m4v"}:
            return "video_link"
        if is_attachment_url(href):
            return "document_link"
        return "url"

    @staticmethod
    def _is_video_link(src: str, alt: str = "") -> bool:
        return (
            "video" in alt.lower()
            or is_video_url(src)
            or src.lower().split("?", 1)[0].endswith((".mp4", ".webm", ".mov", ".m4v"))
        )

    # ── 元素构造 ──────────────────────────────────────────────────

    def _make_element(
        self,
        element_type: ElementType,
        text: str,
        metadata: dict | None = None,
    ) -> ParsedElement:
        """创建一个 ParsedElement，绑定当前累积的 asset_data。"""
        el = ParsedElement(
            doc_id=self._doc_id,
            doc_version=self._doc_version,
            sequence_order=self._next_seq(),
            element_type=element_type,
            text=text,
            asset_data=list(self._pending_asset_data),
            source_location=SourceLocation(section_path=list(self._section_path)),
            metadata=metadata or {},
        )
        self._pending_asset_data = []
        return el

    def _flush_paragraph(self) -> None:
        text = "".join(self._para_parts).strip()
        self._para_parts = []
        if text:
            self._elements.append(self._make_element(ElementType.paragraph, text))

    def _emit_table(self) -> None:
        if not self._table_rows:
            return

        flat_parts: list[str] = []
        if self._table_headers:
            flat_parts.append(" | ".join(h[0] for h in self._table_headers))
        for row in self._table_rows:
            flat_parts.append(" | ".join(cell[0] for cell in row))

        cells_data = [
            {"cells": [{"text": cell_text} for cell_text, _ in row]}
            for row in self._table_rows
        ]

        # 汇总所有单元格的 asset_data 到表格级
        all_asset_data: list[AssetData] = []
        for row in self._table_rows:
            for _, cell_ads in row:
                all_asset_data.extend(cell_ads)

        self._elements.append(ParsedElement(
            doc_id=self._doc_id,
            doc_version=self._doc_version,
            sequence_order=self._next_seq(),
            element_type=ElementType.table,
            text="\n".join(flat_parts),
            structured_data={
                "table": {
                    "caption": "",
                    "headers": [h[0] for h in self._table_headers] if self._table_headers else [],
                    "rows": cells_data,
                }
            },
            asset_data=all_asset_data,
            source_location=SourceLocation(section_path=list(self._section_path)),
        ))

    # ── 解析状态初始化 ──────────────────────────────────────────

    def _init_state(self) -> None:
        self._heading_level = 0
        self._para_parts: list[str] = []
        self._pending_asset_data: list[AssetData] = []

        self._in_table = False
        self._in_thead = False
        self._in_tbody = False
        self._table_headers: list[tuple[str, list[AssetData]]] = []
        self._table_rows: list[list[tuple[str, list[AssetData]]]] = []
        self._current_row: list[tuple[str, list[AssetData]]] = []

        self._in_list = False
        self._list_items: list[str] = []

        self._in_link = False
        self._link_href = ""
        self._link_text_parts: list[str] = []
        self._preplaced_assets: dict[str, tuple[str, str, str]] = {}
