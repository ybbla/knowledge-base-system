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
    asset: Asset
    original_url: str


@dataclass
class _HtmlParseState:
    doc_id: str
    doc_version: int
    elements: list[ParsedElement] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    assets_by_key: dict[tuple[str, AssetType], _AssetRecord] = field(default_factory=dict)
    section_path: list[str] = field(default_factory=list)
    seq: int = 0

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


class HtmlParser(DocumentParser):
    """将静态 HTML 文档解析为统一的 ParsedElement 和 Asset。"""

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

    def parse(self, doc: Document) -> ParseResult:
        content = self._read_content(doc)
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

    def _read_content(self, doc: Document) -> str:
        raw = doc.metadata.get("raw_content", "")
        if raw:
            return self._decode(raw)

        if doc.source_uri.startswith("file://"):
            filepath = resolve_file_uri(doc.source_uri)
            if filepath.exists():
                return self._decode(filepath.read_bytes())

        return ""

    @staticmethod
    def _decode(raw: str | bytes) -> str:
        if isinstance(raw, str):
            return raw
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _content_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
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
            status=AssetStatus.pending,
            extracted_text=None,
            metadata=metadata,
        )
        state.assets.append(asset)
        state.assets_by_key[key] = _AssetRecord(asset=asset, original_url=url)
        return asset

    @staticmethod
    def _append_element(state: _HtmlParseState, element: ParsedElement) -> None:
        linked = set(element.asset_ids)
        for record in state.assets_by_key.values():
            if record.asset.asset_id in linked and not record.asset.source_element_id:
                record.asset.source_element_id = element.element_id
        state.elements.append(element)

    def _header_row_index(self, table: Tag, rows: list[list[dict[str, Any]]]) -> int:
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
        clone = BeautifulSoup(str(tag), "html.parser")
        clone_tag = clone.find(tag.name)
        if clone_tag is None:
            return ""
        for nested in clone_tag.find_all(self.BLOCK_TAGS - {tag.name}):
            nested.decompose()
        return self._normalize_text(clone_tag.get_text(" ", strip=True))

    @staticmethod
    def _text(tag: Tag | None) -> str:
        if tag is None:
            return ""
        return HtmlParser._normalize_text(tag.get_text(" ", strip=True))

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", unescape(text)).strip()

    @staticmethod
    def _language_from_class(tag: Tag | None) -> str:
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
        try:
            return max(1, int(str(tag.get(name) or default)))
        except ValueError:
            return default

    @staticmethod
    def _resolve_url(url: str, base_url: str) -> str:
        if not url:
            return ""
        if urlparse(url).scheme:
            return url
        if base_url and urlparse(base_url).scheme in {"http", "https"}:
            return urljoin(base_url, url)
        return url

    def _tag_is_video(self, tag: Tag) -> bool:
        name = (tag.name or "").lower()
        if name in {"video", "source"}:
            return True
        if name == "iframe":
            raw = str(tag.get("src") or "")
            return self._is_video_url(raw)
        return False

    def _is_video_url(self, url: str) -> bool:
        return bool(self.VIDEO_URL_RE.search(url))

    def _is_attachment_url(self, url: str) -> bool:
        path = urlparse(url).path or url
        suffix = PurePosixPath(path).suffix.lower()
        return suffix in self.ATTACHMENT_EXTENSIONS

    @staticmethod
    def _guess_mime(url: str, asset_type: AssetType) -> str:
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
        name = (tag.name or "").lower()
        attr = "href" if name == "a" else "data" if name == "object" else "src"
        url = str(tag.get(attr) or "")
        if name == "img":
            alt = str(tag.get("alt") or "")
            return f"[图片: {alt or url}]"
        if name in {"video", "source", "iframe"}:
            return f"[视频: {url}]"
        return f"[附件: {url}]"
