"""HTML 文档解析器。

使用 BeautifulSoup 将静态 HTML 文档解析为统一的 ParsedElement 和 Asset，
支持标题、段落、列表、代码块、表格以及图片、视频、附件等内嵌资源的提取。
"""

import re
from dataclasses import dataclass, field
from html import unescape
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

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
    """内部 Asset 记录，保存 Asset 对象及原始 URL。"""
    asset: Asset
    original_url: str


@dataclass
class _HtmlParseState:
    """HTML 解析过程中的可变状态。"""
    doc_id: str
    doc_version: int
    elements: list[ParsedElement] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    assets_by_key: dict[tuple[str, AssetType], _AssetRecord] = field(default_factory=dict)
    section_path: list[str] = field(default_factory=list)
    seq: int = 0

    def next_seq(self) -> int:
        """生成递增的序号。"""
        self.seq += 1
        return self.seq


class HtmlParser(DocumentParser):
    """将静态 HTML 文档解析为统一的 ParsedElement 和 Asset。

    支持的 source_type：html、htm。
    """

    SUPPORTED_TYPES = {"html", "htm"}
    SKIP_TAGS = {"script", "style", "noscript", "template", "meta", "link"}
    BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "body",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "form",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
    RESOURCE_TAGS = {"img", "video", "source", "iframe", "embed", "object", "a"}
    VIDEO_URL_RE = re.compile(
        r"https?://[^\s\])<\"']*(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov|\.m4v)[^\s\])<\"']*",
        re.IGNORECASE,
    )
    HTTP_URL_RE = re.compile(r"https?://[^\s\])<\"']+", re.IGNORECASE)
    ATTACHMENT_EXTENSIONS = {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".zip",
        ".rar",
        ".7z",
        ".csv",
        ".txt",
        ".md",
    }

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    CONTENT_IS_TEXT = True

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """主解析入口：将 HTML 文档解析为结构化元素和资源列表。"""
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        if not content.strip():
            raise ValueError("HTML 解析失败：文档内容为空")

        soup = BeautifulSoup(content, "html.parser")
        for tag in soup.find_all(self.SKIP_TAGS):
            tag.decompose()

        root = self._content_root(soup)
        state = _HtmlParseState(doc.doc_id, doc.version)
        base_url = self._base_url(soup, doc)

        self._walk_children(root, state, doc, base_url)
        doc.source_hash = compute_hash(content)

        if not state.elements:
            raise ValueError("HTML 解析失败：未提取到有效内容")
        return ParseResult(doc=doc, elements=state.elements, assets=state.assets)

    @staticmethod
    def _content_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
        """定位 HTML 文档的主要内容根节点。

        优先使用 <main>，其次 <body>，再次 <article>。
        """
        for selector in ("main", "body"):
            found = soup.find(selector)
            if isinstance(found, Tag):
                return found
        articles = soup.find_all("article", recursive=False)
        if len(articles) == 1 and isinstance(articles[0], Tag):
            return articles[0]
        return soup

    @staticmethod
    def _base_url(soup: BeautifulSoup, doc: Document) -> str:
        """提取文档的基 URL（优先 <base> 标签，其次文档 source_uri）。"""
        base = soup.find("base", href=True)
        if isinstance(base, Tag):
            return str(base.get("href") or "")
        return doc.source_uri

    def _walk_children(
        self,
        parent: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """递归遍历父节点的子元素，跳过纯文本节点。"""
        for child in parent.children:
            if isinstance(child, NavigableString):
                continue
            if not isinstance(child, Tag):
                continue
            self._process_tag(child, state, doc, base_url)

    def _process_tag(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """根据标签类型分发到对应的处理方法。"""
        name = (tag.name or "").lower()
        if name in self.SKIP_TAGS:
            return
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._add_title(tag, state)
            self._walk_children(tag, state, doc, base_url)
            return
        if name in {"p", "blockquote"}:
            self._add_paragraph(tag, state, doc, base_url)
            return
        if name in {"ul", "ol"}:
            self._add_list(tag, state, doc, base_url)
            return
        if name in {"pre", "code"}:
            self._add_code(tag, state)
            return
        if name == "table":
            self._add_table(tag, state, doc, base_url)
            return
        if name in self.RESOURCE_TAGS:
            self._add_resource_element(tag, state, doc, base_url)
            return

        self._walk_children(tag, state, doc, base_url)

    def _add_title(self, tag: Tag, state: _HtmlParseState) -> None:
        """添加标题元素（h1-h6）并按层级更新 section_path。"""
        text = self._text_without_nested_blocks(tag)
        if not text:
            return
        level = int(tag.name[1])
        while len(state.section_path) >= level:
            state.section_path.pop()
        state.section_path.append(text)
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.title,
                text=text,
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={"heading_level": level, "tag": tag.name},
            ),
        )

    def _add_paragraph(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """添加段落元素（p、blockquote），收集内嵌资源的 ID。"""
        text = self._text_without_nested_blocks(tag)
        asset_ids = self._assets_in_tag(tag, state, doc, base_url)
        if not text and not asset_ids:
            return
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
                metadata={"tag": tag.name},
            ),
        )

    def _add_list(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """添加列表元素（ul、ol），支持嵌套列表递归。"""
        items = [child for child in tag.find_all("li", recursive=False)]
        if not items:
            return

        container = ParsedElement(
            doc_id=state.doc_id,
            doc_version=state.doc_version,
            sequence_order=state.next_seq(),
            element_type=ElementType.list,
            text="",
            source_location=SourceLocation(section_path=list(state.section_path)),
            metadata={"ordered": tag.name == "ol", "tag": tag.name},
        )
        self._append_element(state, container)

        for item in items:
            nested_lists = item.find_all(["ul", "ol"], recursive=False)
            for nested in nested_lists:
                nested.extract()
            text = self._text_without_nested_blocks(item)
            asset_ids = self._assets_in_tag(item, state, doc, base_url)
            if text or asset_ids:
                self._append_element(
                    state,
                    ParsedElement(
                        doc_id=state.doc_id,
                        doc_version=state.doc_version,
                        parent_element_id=container.element_id,
                        sequence_order=state.next_seq(),
                        element_type=ElementType.paragraph,
                        text=text,
                        asset_ids=asset_ids,
                        source_location=SourceLocation(section_path=list(state.section_path)),
                        metadata={"tag": "li"},
                    ),
                )
            for nested in nested_lists:
                self._add_list(nested, state, doc, base_url)

    def _add_code(self, tag: Tag, state: _HtmlParseState) -> None:
        """添加代码块元素（pre、code），尝试从 class 属性推断编程语言。"""
        text = tag.get_text("\n", strip=False).strip("\n")
        if not text:
            return
        language = self._language_from_class(tag) or self._language_from_class(tag.find("code"))
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=ElementType.code,
                text=unescape(text),
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={"language": language, "tag": tag.name},
            ),
        )

    def _add_table(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """添加表格元素，支持嵌套表格递归、标题行检测和单元格资源提取。"""
        nested_tables = tag.find_all("table")
        for nested in nested_tables:
            nested.extract()

        caption_tag = tag.find("caption", recursive=False)
        caption = self._text(caption_tag) if caption_tag else ""
        table_rows: list[list[dict[str, Any]]] = []
        asset_ids: list[str] = []

        for tr in tag.find_all("tr"):
            cells = []
            for cell_tag in tr.find_all(["th", "td"], recursive=False):
                cell_assets = self._assets_in_tag(cell_tag, state, doc, base_url)
                asset_ids.extend(cell_assets)
                cells.append(
                    {
                        "text": self._text_without_nested_blocks(cell_tag),
                        "asset_ids": cell_assets,
                        "metadata": {
                            "tag": cell_tag.name,
                            "rowspan": self._int_attr(cell_tag, "rowspan", 1),
                            "colspan": self._int_attr(cell_tag, "colspan", 1),
                        },
                    }
                )
            if cells:
                table_rows.append(cells)

        if not table_rows:
            for nested in nested_tables:
                self._add_table(nested, state, doc, base_url)
            return

        header_index = self._header_row_index(tag, table_rows)
        headers = [cell["text"] for cell in table_rows[header_index]]
        rows = [
            {"cells": row}
            for index, row in enumerate(table_rows)
            if index != header_index
        ]
        structured = {
            "table": {
                "caption": caption,
                "headers": headers,
                "rows": rows,
                "metadata": {
                    "tag": "table",
                    "row_count": len(table_rows),
                    "header_row_index": header_index,
                },
            }
        }
        text_parts = []
        if caption:
            text_parts.append(caption)
        if headers:
            text_parts.append(" | ".join(headers))
        for row in rows:
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
                metadata={"tag": "table", "caption": caption},
            ),
        )

        for nested in nested_tables:
            self._add_table(nested, state, doc, base_url)

    def _add_resource_element(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """为 <img>、<video>、<iframe> 等资源标签创建对应的元素。"""
        asset_ids = self._assets_from_resource_tag(tag, state, doc, base_url)
        if not asset_ids:
            return
        element_type = ElementType.video if self._tag_is_video(tag) else ElementType.image
        if element_type == ElementType.image and (tag.name or "").lower() != "img":
            element_type = ElementType.paragraph
        text = self._text(tag) or self._resource_label(tag)
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state.next_seq(),
                element_type=element_type,
                text=text,
                asset_ids=asset_ids,
                source_location=SourceLocation(section_path=list(state.section_path)),
                metadata={"tag": tag.name},
            ),
        )

    def _assets_in_tag(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> list[str]:
        """收集指定标签及其子标签中所有资源标签的 Asset ID（含文本中的 URL）。"""
        asset_ids: list[str] = []
        for resource in tag.find_all(self.RESOURCE_TAGS):
            asset_ids.extend(self._assets_from_resource_tag(resource, state, doc, base_url))
        for url in self.HTTP_URL_RE.findall(self._text(tag)):
            if self._is_video_url(url):
                asset_ids.append(
                    self._asset_for_url(url, AssetType.video, state, doc, {"source": "html_text"}).asset_id
                )
        return list(dict.fromkeys(asset_ids))

    def _assets_from_resource_tag(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> list[str]:
        """从单个资源标签创建 Asset 并返回其 ID。

        支持 img、video、source、a（附件链接）、iframe、embed、object 等标签。
        """
        name = (tag.name or "").lower()
        attr = "href" if name == "a" else "data" if name == "object" else "src"
        raw_url = str(tag.get(attr) or "")
        if not raw_url:
            return []

        original_url = raw_url.strip()
        resolved_url = self._resolve_url(original_url, base_url)
        metadata = {
            "tag": name,
            "attribute": attr,
            "original_url": original_url,
            "resolved_url": resolved_url,
            "base_url": base_url,
        }
        if name == "img":
            metadata["alt"] = str(tag.get("alt") or "")
            return [
                self._asset_for_url(
                    resolved_url or original_url,
                    AssetType.image,
                    state,
                    doc,
                    metadata,
                ).asset_id
            ]
        if self._tag_is_video(tag) or self._is_video_url(resolved_url or original_url):
            return [
                self._asset_for_url(
                    resolved_url or original_url,
                    AssetType.video,
                    state,
                    doc,
                    metadata,
                ).asset_id
            ]
        if name in {"iframe", "embed", "object"} or self._is_attachment_url(resolved_url or original_url):
            return [
                self._asset_for_url(
                    resolved_url or original_url,
                    AssetType.attachment,
                    state,
                    doc,
                    metadata,
                ).asset_id
            ]
        return []

    def _asset_for_url(
        self,
        url: str,
        asset_type: AssetType,
        state: _HtmlParseState,
        doc: Document,
        metadata: dict[str, Any],
    ) -> Asset:
        """创建或查找已有 Asset（按 URL + 类型去重）。"""
        key = (url, asset_type)
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
        state.assets_by_key[key] = _AssetRecord(asset=asset, original_url=url)
        return asset

    @staticmethod
    def _append_element(state: _HtmlParseState, element: ParsedElement) -> None:
        """添加元素并回链 Asset 的 source_element_id。"""
        linked = set(element.asset_ids)
        for record in state.assets_by_key.values():
            if record.asset.asset_id in linked and not record.asset.source_element_id:
                record.asset.source_element_id = element.element_id
        state.elements.append(element)

    def _header_row_index(self, table: Tag, rows: list[list[dict[str, Any]]]) -> int:
        """检测表格的标题行索引。

        优先检查 <thead> 元素，其次检查第一行是否全为 <th> 单元格。
        """
        thead = table.find("thead")
        if thead is not None:
            first_header = thead.find("tr")
            if first_header is not None:
                table_rows = table.find_all("tr")
                try:
                    return table_rows.index(first_header)
                except ValueError:
                    return 0
        if rows and all(cell["metadata"]["tag"] == "th" for cell in rows[0]):
            return 0
        return 0

    def _text_without_nested_blocks(self, tag: Tag) -> str:
        """提取标签的文本内容，排除嵌套的块级子标签。"""
        clone = BeautifulSoup(str(tag), "html.parser")
        clone_tag = clone.find(tag.name)
        if clone_tag is None:
            return ""
        for nested in clone_tag.find_all(self.BLOCK_TAGS - {tag.name}):
            nested.decompose()
        return self._normalize_text(clone_tag.get_text(" ", strip=True))

    @staticmethod
    def _text(tag: Tag | None) -> str:
        """提取标签的纯文本内容（经空白归一化处理）。"""
        if tag is None:
            return ""
        return HtmlParser._normalize_text(tag.get_text(" ", strip=True))

    @staticmethod
    def _normalize_text(text: str) -> str:
        """将连续空白字符归一化为单个空格并去除首尾空白。"""
        return re.sub(r"\s+", " ", unescape(text)).strip()

    @staticmethod
    def _language_from_class(tag: Tag | None) -> str:
        """从标签的 class 属性中推断编程语言（language-xx 或 lang-xx）。"""
        if not isinstance(tag, Tag):
            return ""
        classes = tag.get("class") or []
        for klass in classes:
            text = str(klass)
            if text.startswith("language-"):
                return text.removeprefix("language-")
            if text.startswith("lang-"):
                return text.removeprefix("lang-")
        return ""

    @staticmethod
    def _int_attr(tag: Tag, name: str, default: int) -> int:
        """安全地获取标签的整数属性值（最小为 1）。"""
        try:
            return max(1, int(str(tag.get(name) or default)))
        except ValueError:
            return default

    @staticmethod
    def _resolve_url(url: str, base_url: str) -> str:
        """将相对 URL 解析为绝对 URL（仅在 base_url 为 http(s) 时）。"""
        if not url:
            return ""
        if urlparse(url).scheme:
            return url
        if base_url and urlparse(base_url).scheme in {"http", "https"}:
            return urljoin(base_url, url)
        return url

    def _tag_is_video(self, tag: Tag) -> bool:
        """判断标签是否为视频资源。"""
        name = (tag.name or "").lower()
        if name in {"video", "source"}:
            return True
        if name == "iframe":
            raw = str(tag.get("src") or "")
            return self._is_video_url(raw)
        return False

    def _is_video_url(self, url: str) -> bool:
        """判断 URL 是否为视频链接。"""
        return bool(self.VIDEO_URL_RE.search(url))

    def _is_attachment_url(self, url: str) -> bool:
        """判断 URL 是否指向附件文件。"""
        path = urlparse(url).path or url
        suffix = PurePosixPath(path).suffix.lower()
        return suffix in self.ATTACHMENT_EXTENSIONS

    @staticmethod
    def _guess_mime(url: str, asset_type: AssetType) -> str:
        """根据 URL 后缀和资源类型推断 MIME 类型。"""
        suffix = PurePosixPath(urlparse(url).path or url).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".m4v": "video/mp4",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        if suffix in mime_map:
            return mime_map[suffix]
        if asset_type == AssetType.image:
            return "image/*"
        if asset_type == AssetType.video:
            return "video/*"
        return "application/octet-stream"

    @staticmethod
    def _resource_label(tag: Tag) -> str:
        """为资源标签生成可读的替代文本标签。"""
        name = (tag.name or "").lower()
        attr = "href" if name == "a" else "data" if name == "object" else "src"
        url = str(tag.get(attr) or "")
        if name == "img":
            alt = str(tag.get("alt") or "")
            return f"[图片: {alt or url}]"
        if name in {"video", "source", "iframe"}:
            return f"[视频: {url}]"
        return f"[附件: {url}]"
