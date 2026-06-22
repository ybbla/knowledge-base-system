"""DOCX 文档解析器。

使用 python-docx 将 .docx 文件解析为统一的 ParsedElement 和 Asset，
支持标题、段落、列表、表格、内联图片、超链接和嵌入资源的提取。
"""

import hashlib
import io
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

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
from parsers.base import DocumentParser, ParseResult, _BaseParseState
from parsers.utils import (
    ATTACHMENT_EXTENSIONS,
    VIDEO_URL_RE,
    classify_link,
    guess_mime,
    is_attachment_url,
    is_video_url,
)

logger = logging.getLogger(__name__)

# 已知图片扩展名（用于链接 URL 分类，与 MarkdownParser 保持一致）
_IMAGE_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".tif",
}


class DocxParser(DocumentParser):
    """将 DOCX 文档解析为 ParsedElement 和 Asset。

    支持的 source_type：docx。
    处理 Word 段落、标题、列表、表格、内联图片、超链接和嵌入资源。
    """

    SUPPORTED_TYPES = {"docx"}

    # 多语言标题样式名关键词集合（覆盖中/英/法/德/西/葡/意/日 8 种语言）
    HEADING_KEYWORDS = {
        "heading", "head",          # 英文
        "标题",                      # 中文
        "titre", "title",           # 法文 / 英文变体
        "uberschrift", "überschrift",  # 德文
        "titulo", "título",         # 西班牙文 / 葡萄牙文
        "intestazione",             # 意大利文
        "見出し",                   # 日文
    }

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    # ── 主解析入口 ──────────────────────────────────────────────

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """主解析入口：解析 DOCX 文档的结构化内容。

        新流程：预提取图片 → 遍历 body → flush → 提取视频 → 回填关联 → 计算哈希。
        """
        if isinstance(content, str):
            content = content.encode("utf-8")
        docx = DocxDocument(io.BytesIO(content))
        state = _DocxParseState(doc.doc_id, doc.version)

        # 1. 预提取所有嵌入图片到 asset map
        self._build_image_asset_map(doc, state)

        # 2. 按文档顺序遍历所有 body 元素（只含正文，不含页眉页脚）
        for child in docx.element.body:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "p":
                self._process_paragraph(child, docx, state)
            elif tag == "tbl":
                self._process_table(child, docx, state)

        # 3. 完成解析，获取所有元素
        elements = state.flush_elements()

        # 4. 从元素文本中提取视频链接
        self._extract_videos(doc, elements, state)

        # 5. 回填 Asset.source_element_id 关联
        self._link_assets_to_elements(elements, state.assets)

        # 6. 计算文档内容哈希
        doc.source_hash = compute_hash(content)

        return ParseResult(doc=doc, elements=elements, assets=state.assets)

    # ── 标题检测 ────────────────────────────────────────────────

    @classmethod
    def _detect_heading_level(cls, style_name: str, docx: DocxDocument) -> int | None:
        """从样式名中检测标题层级。

        匹配逻辑：样式名小写后检查是否包含任一多语言关键词 → 提取尾部数字作为 level。
        无数字时通过 docx.styles 二次确认是否为标题样式。

        Args:
            style_name: w:pStyle 的 w:val 属性值。
            docx: python-docx Document 对象，用于二次样式确认。

        Returns:
            标题层级（1-9），非标题样式返回 None。
        """
        if not style_name:
            return None

        name_lower = style_name.lower()

        # 检查是否包含任一标题关键词
        matched_keyword = None
        for kw in cls.HEADING_KEYWORDS:
            if kw in name_lower:
                matched_keyword = kw
                break

        if matched_keyword is None:
            return None

        # 去掉关键词后提取尾部数字
        remaining = name_lower.replace(matched_keyword, "").strip()
        # 提取尾部连续数字
        digits = ""
        for ch in reversed(remaining):
            if ch.isdigit():
                digits = ch + digits
            else:
                break

        if digits:
            return int(digits)

        # 无数字时通过 docx 样式表二次确认
        try:
            for style in docx.styles:
                if style.style_id == style_name and style.type == WD_STYLE_TYPE.PARAGRAPH:
                    if style.name:
                        s_lower = style.name.lower()
                        for kw in cls.HEADING_KEYWORDS:
                            if kw in s_lower:
                                # 从样式 name 中提取数字
                                remain = s_lower.replace(kw, "").strip()
                                d = ""
                                for ch in reversed(remain):
                                    if ch.isdigit():
                                        d = ch + d
                                    else:
                                        break
                                if d:
                                    return int(d)
                                return 1  # 有关键词但无数字，默认 level 1
                    break
        except Exception:
            pass

        return None

    # ── 段落处理 ────────────────────────────────────────────────

    def _process_paragraph(
        self, p_el, docx: DocxDocument, state: "_DocxParseState"
    ) -> None:
        """处理一个 w:p 元素（段落）。

        按 w:p 的直接子元素（w:r 和 w:hyperlink）顺序遍历，
        提取内联图片、超链接和文本，保持原文顺序。
        """
        # 获取样式名称和列表标记
        style_name = ""
        is_list = False
        pPr = p_el.find(qn("w:pPr"))
        if pPr is not None:
            pStyle = pPr.find(qn("w:pStyle"))
            if pStyle is not None:
                style_name = pStyle.get(qn("w:val"), "")
                is_list = style_name.lower().startswith("list")
            is_list = is_list or pPr.find(qn("w:numPr")) is not None

        # 按直接子元素顺序遍历，提取文本和资源
        text_parts: list[str] = []
        has_content = False  # 是否有实际内容（文本、图片或链接）

        for child in p_el:
            child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if child_tag == "r":
                # ── 文本运行（w:r）──
                # 先检查内联图片（w:drawing → a:blip → r:embed）
                drawing_rIds = self._extract_drawing_rIds(child)
                for rId in drawing_rIds:
                    asset = self._resolve_image_asset(rId, docx, state)
                    if asset is not None:
                        state.track_asset(asset.asset_id)
                        # 从 asset 的 original_uri 提取文件名作为占位文本
                        filename = asset.original_uri.rsplit("/", 1)[-1] if "/" in asset.original_uri else asset.original_uri
                        text_parts.append(f"[图片: {filename}]")
                        has_content = True

                # 再提取文本（w:t 节点）
                for t_node in child.iter(qn("w:t")):
                    if t_node.text:
                        text_parts.append(t_node.text)
                        has_content = True

            elif child_tag == "hyperlink":
                # ── 超链接（w:hyperlink）──
                link_text, url = self._extract_hyperlink(child, docx)
                if link_text:
                    text_parts.append(link_text)
                    has_content = True

                if url:
                    asset_type = self._classify_link_url(url)
                    if asset_type is not None:
                        # 文件/视频/图片链接 → 创建 Asset 并关联
                        asset = Asset(
                            doc_id=state.doc_id,
                            asset_type=asset_type,
                            original_uri=url,
                            mime_type=guess_mime(url, asset_type),
                            status=AssetStatus.ready,
                        )
                        state.assets.append(asset)
                        state.track_asset(asset.asset_id)
                    else:
                        # 普通网页链接 → URL 记录到 link_urls
                        state.track_link_url(url)

        text = "".join(text_parts).strip()

        # 检查不受支持的嵌入对象
        has_unknown_object = self._has_unsupported_object(p_el)

        # 空段落（无文本、无图片、无链接）跳过
        if not text and not has_content:
            if has_unknown_object:
                state.add_unknown("[不支持的嵌入 DOCX 对象]")
            return

        # 根据样式判断元素类型
        # is_list 时强制不识别为标题（防止 List 样式误判）
        heading_match = None if is_list else self._detect_heading_level(style_name, docx)

        if heading_match is not None:
            state.add_title(text, heading_match)
        elif is_list:
            state.add_list_item(text)
        else:
            state.add_paragraph(text)

        if has_unknown_object:
            state.add_unknown("[不支持的嵌入 DOCX 对象]")

    # ── 超链接提取 ──────────────────────────────────────────────

    def _extract_hyperlink(self, hyperlink_el, docx: DocxDocument) -> tuple[str, str]:
        """从 w:hyperlink 元素中提取显示文字和目标 URL。

        Args:
            hyperlink_el: w:hyperlink XML 元素。
            docx: python-docx Document 对象。

        Returns:
            (显示文字, 目标URL) 元组，不存在时为空字符串。
        """
        # 提取显示文字：遍历内部所有 w:t 节点
        texts = []
        for t_node in hyperlink_el.iter(qn("w:t")):
            if t_node.text:
                texts.append(t_node.text)
        display_text = "".join(texts)

        # 提取目标 URL：通过 r:id → docx.part.rels → rel.target_ref
        rId = hyperlink_el.get(qn("r:id"))
        url = ""
        if rId:
            try:
                rel = docx.part.rels[rId]
                url = rel.target_ref
            except (KeyError, AttributeError):
                pass

        return display_text, url

    # ── 链接分类 ────────────────────────────────────────────────

    @staticmethod
    def _classify_link_url(url: str) -> AssetType | None:
        """判断链接 URL 的资源类型（与 MarkdownParser 相同逻辑）。

        优先级：视频 > 图片 > 附件 > 普通网页。
        普通网页返回 None。
        """
        if is_video_url(url):
            return AssetType.video
        suffix = PurePosixPath(url.split("?", 1)[0]).suffix.lower()
        if suffix in _IMAGE_EXTENSIONS:
            return AssetType.image
        if is_attachment_url(url):
            return AssetType.attachment
        return None

    # ── 内联图片处理 ────────────────────────────────────────────

    @staticmethod
    def _extract_drawing_rIds(r_el) -> list[str]:
        """从 w:r 元素中提取所有内联图片的 r:embed rId。

        遍历 w:drawing → a:blip → 提取 r:embed 属性。

        Args:
            r_el: w:r XML 元素。

        Returns:
            r:embed 属性值列表。
        """
        rIds: list[str] = []
        for drawing in r_el.iter(qn("w:drawing")):
            for blip in drawing.iter():
                blip_tag = blip.tag.split("}")[-1] if "}" in blip.tag else blip.tag
                if blip_tag == "blip":
                    embed = blip.get(qn("r:embed"))
                    if embed:
                        rIds.append(embed)
        return rIds

    def _resolve_image_asset(
        self, rId: str, docx: DocxDocument, state: "_DocxParseState"
    ) -> Asset | None:
        """通过 rId 在 asset map 中查找对应的图片 Asset。

        Args:
            rId: w:drawing → a:blip → r:embed 的值。
            docx: python-docx Document 对象。
            state: 当前解析状态（含 _image_asset_map）。

        Returns:
            匹配的 Asset，未找到时返回 None。
        """
        try:
            rel = docx.part.rels[rId]
            target = rel.target_ref  # 格式: media/image1.png（无 word/ 前缀）
            return state._image_asset_map.get(target)
        except (KeyError, AttributeError):
            return None

    # ── 表格处理 ────────────────────────────────────────────────

    def _process_table(
        self, tbl_el, docx: DocxDocument, state: "_DocxParseState"
    ) -> None:
        """处理一个 w:tbl 元素（表格）。

        提取行列结构，处理合并单元格（含垂直合并），
        同时提取单元格内的图片和超链接资源。
        """
        # 每格存 (text, asset_ids) 元组
        rows_data: list[list[tuple[str, list[str]]]] = []
        headers: list[tuple[str, list[str]]] = []
        vertical_merges: dict[int, tuple[str, list[str]]] = {}
        table_link_urls: list[str] = []
        table_links: list[dict[str, str]] = []

        for i, tr in enumerate(tbl_el.findall(qn("w:tr"))):
            cells: list[tuple[str, list[str]]] = []
            col_idx = 0
            for tc in tr.findall(qn("w:tc")):
                # 提取单元格的文本和资源
                cell_text_parts: list[str] = []
                cell_asset_ids: list[str] = []

                # w:tc 的直接子元素是 w:p（段落），遍历每个 w:p
                for tc_child in tc:
                    tc_tag = tc_child.tag.split("}")[-1] if "}" in tc_child.tag else tc_child.tag
                    if tc_tag != "p":
                        continue

                    # 复用段落子元素遍历模式
                    para_text_parts: list[str] = []
                    for p_child in tc_child:
                        p_tag = p_child.tag.split("}")[-1] if "}" in p_child.tag else p_child.tag

                        if p_tag == "r":
                            # 内联图片
                            drawing_rIds = self._extract_drawing_rIds(p_child)
                            for rId in drawing_rIds:
                                asset = self._resolve_image_asset(rId, docx, state)
                                if asset is not None:
                                    cell_asset_ids.append(asset.asset_id)
                            # 文本
                            for t_node in p_child.iter(qn("w:t")):
                                if t_node.text:
                                    para_text_parts.append(t_node.text)

                        elif p_tag == "hyperlink":
                            link_text, url = self._extract_hyperlink(p_child, docx)
                            if link_text:
                                para_text_parts.append(link_text)
                            if url:
                                asset_type = self._classify_link_url(url)
                                if asset_type is not None:
                                    asset = Asset(
                                        doc_id=state.doc_id,
                                        asset_type=asset_type,
                                        original_uri=url,
                                        mime_type=guess_mime(url, asset_type),
                                        status=AssetStatus.ready,
                                    )
                                    state.assets.append(asset)
                                    cell_asset_ids.append(asset.asset_id)
                                else:
                                    # 普通网页链接记录到 link_urls
                                    table_link_urls.append(url)
                                # 记录链接信息用于 structured_data.links
                                table_links.append({
                                    "text": link_text or "",
                                    "url": url,
                                    "link_type": classify_link(url),
                                })

                    if para_text_parts:
                        cell_text_parts.append("".join(para_text_parts))

                # 多个 w:p 之间用换行符分隔
                cell_text = "\n".join(cell_text_parts) if cell_text_parts else ""

                # 获取合并单元格属性
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

                # 处理垂直合并单元格（含 asset_ids 传递）
                if vmerge_val == "continue":
                    merged = vertical_merges.get(col_idx, ("", []))
                    cell_text = merged[0] or cell_text
                    cell_asset_ids = merged[1] or cell_asset_ids
                elif vmerge_val == "restart":
                    for offset in range(span):
                        vertical_merges[col_idx + offset] = (cell_text, list(cell_asset_ids))

                for offset in range(span):
                    if vmerge_val == "continue":
                        merged = vertical_merges.get(col_idx + offset, ("", []))
                        cells.append((merged[0] or cell_text, list(merged[1] or cell_asset_ids)))
                    else:
                        cells.append((cell_text, list(cell_asset_ids)))
                col_idx += span

            if i == 0:
                headers = cells
            else:
                rows_data.append(cells)

        if not rows_data:
            return

        # 构建 structured_data
        all_asset_ids: list[str] = []
        structured: dict[str, Any] = {
            "table": {
                "caption": "",
                "headers": [
                    {"text": h[0], "asset_ids": h[1]}
                    for h in headers
                ],
                "rows": [
                    {
                        "cells": [
                            {"text": cell[0], "asset_ids": cell[1]}
                            for cell in row
                        ]
                    }
                    for row in rows_data
                ],
            }
        }
        if table_links:
            structured["links"] = table_links

        # 表格级 asset_ids 汇总（去重）
        seen_ids: set[str] = set()
        for h in headers:
            for aid in h[1]:
                if aid not in seen_ids:
                    seen_ids.add(aid)
                    all_asset_ids.append(aid)
        for row in rows_data:
            for cell in row:
                for aid in cell[1]:
                    if aid not in seen_ids:
                        seen_ids.add(aid)
                        all_asset_ids.append(aid)

        # 构建纯文本表示（仅使用文本部分）
        flat_parts = []
        if headers:
            flat_parts.append(" | ".join(h[0] for h in headers))
        for row in rows_data:
            flat_parts.append(" | ".join(cell[0] for cell in row))

        element_kwargs: dict[str, Any] = {
            "doc_id": state.doc_id,
            "doc_version": state.doc_version,
            "parent_element_id": None,
            "sequence_order": state._next_seq(),
            "element_type": ElementType.table,
            "text": "\n".join(flat_parts),
            "structured_data": structured,
            "asset_ids": all_asset_ids,
            "source_location": SourceLocation(section_path=list(state._section_path)),
        }
        if table_link_urls:
            element_kwargs["metadata"] = {"link_urls": table_link_urls}
        el = ParsedElement(**element_kwargs)
        state.elements.append(el)

    # ── 图片预提取 ──────────────────────────────────────────────

    def _build_image_asset_map(
        self, doc: Document, state: "_DocxParseState"
    ) -> None:
        """从 docx 归档的 word/media/ 目录预提取所有嵌入图片。

        图片存入 state._image_asset_map（双 key）和 state.assets，
        不再创建独立的 image 类型 ParsedElement。

        Args:
            doc: 文档对象（含 raw_content 或 source_uri）。
            state: 当前解析状态。
        """
        raw = doc.metadata.get("raw_content", "")
        zip_source: bytes | Path | None = None
        if raw:
            zip_source = raw.encode("utf-8") if isinstance(raw, str) else raw
        elif doc.source_uri.startswith("file://"):
            filepath = resolve_file_uri(doc.source_uri)
            if filepath.exists():
                zip_source = filepath

        if zip_source is None:
            return

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
                    filename = name.split("/")[-1]

                    # 双 key：zip 完整路径 + rels 短路径
                    short_path = name.replace("word/", "", 1)  # media/image1.png

                    asset = Asset(
                        doc_id=state.doc_id,
                        source_element_id="",
                        asset_type=AssetType.image,
                        original_uri=f"docx://{state.doc_id}/media/{filename}",
                        mime_type=guess_mime(f".{ext}", AssetType.image),
                        content_hash=f"sha256:{content_hash}",
                        status=AssetStatus.ready,
                        storage_uri=None,
                        extracted_text=None,
                        metadata={"width": None, "height": None},
                    )
                    object.__setattr__(asset, "_data", data)

                    # 双 key 存储
                    state._image_asset_map[name] = asset       # word/media/image1.png
                    state._image_asset_map[short_path] = asset  # media/image1.png
                    state.assets.append(asset)

        except (zipfile.BadZipFile, KeyError) as exc:
            logger.warning("从 docx 提取图片失败: %s", exc)

    # ── 视频提取 ────────────────────────────────────────────────

    def _extract_videos(
        self,
        doc: Document,
        elements: list[ParsedElement],
        state: "_DocxParseState",
    ) -> None:
        """从元素文本中识别视频链接并创建 Asset。

        使用公共 VIDEO_URL_RE 和 guess_mime，Asset 存入 state.assets，
        不再创建独立的 video 类型 ParsedElement。

        Args:
            doc: 文档对象。
            elements: 已解析的元素列表。
            state: 当前解析状态。
        """
        seen: set[str] = {a.original_uri for a in state.assets if a.asset_type == AssetType.video}
        for el in elements:
            for match in VIDEO_URL_RE.finditer(el.text or ""):
                url = match.group(0)
                if url in seen:
                    continue
                seen.add(url)
                asset = Asset(
                    doc_id=state.doc_id,
                    source_element_id=el.element_id,
                    asset_type=AssetType.video,
                    original_uri=url,
                    storage_uri=None,
                    mime_type=guess_mime(url, AssetType.video),
                    extracted_text=None,
                    metadata={"source": "video_link"},
                )
                state.assets.append(asset)

    # ── 资源关联回填 ────────────────────────────────────────────

    @staticmethod
    def _link_assets_to_elements(
        elements: list[ParsedElement],
        assets: list[Asset],
    ) -> None:
        """在元素获得生成的 ID 后，回填 Asset 的 source_element_id 关联。

        与 MarkdownParser._link_assets_to_elements 相同模式。
        """
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

    # ── 不支持对象检测 ──────────────────────────────────────────

    def _has_unsupported_object(self, p_el) -> bool:
        """检查段落中是否包含不受支持的嵌入对象（OLE 等）。"""
        unsupported_tags = {"object", "oleobject", "control"}
        for node in p_el.iter():
            local = node.tag.split("}")[-1].lower() if "}" in node.tag else node.tag.lower()
            if local in unsupported_tags:
                return True
        return False


# ── 内部解析状态 ────────────────────────────────────────────────


@dataclass
class _DocxParseState(_BaseParseState):
    """DOCX 解析过程中的可变状态，在遍历 body 元素时逐步构建元素。

    继承 _BaseParseState 的 doc_id、doc_version、elements、_seq、_section_path
    和 _next_seq() 方法。
    扩展资源跟踪字段，支持内联图片和超链接的关联。
    """

    _current_list_id: str | None = None
    _tracked_assets: list[str] = field(default_factory=list)
    _link_urls: list[str] = field(default_factory=list)
    _image_asset_map: dict[str, Asset] = field(default_factory=dict)
    assets: list[Asset] = field(default_factory=list)

    # ── 资源跟踪 ────────────────────────────────────────────────

    def track_asset(self, asset_id: str) -> None:
        """记录当前上下文关联的资源 ID，在 add_paragraph 时消费。"""
        self._tracked_assets.append(asset_id)

    def track_link_url(self, url: str) -> None:
        """记录当前段落的链接 URL，在 add_paragraph 时消费。"""
        self._link_urls.append(url)

    def consume_tracked_assets(self) -> list[str]:
        """消费并清空资源跟踪列表。"""
        result = list(self._tracked_assets)
        self._tracked_assets = []
        return result

    def consume_link_urls(self) -> list[str]:
        """消费并清空链接 URL 列表。"""
        result = list(self._link_urls)
        self._link_urls = []
        return result

    # ── 元素累积 ────────────────────────────────────────────────

    def flush_elements(self) -> list[ParsedElement]:
        """完成解析，返回所有累积的元素。"""
        return self.elements

    def add_title(self, text: str, level: int) -> None:
        """添加标题元素并按层级更新 section_path。

        标题出现时清空资源跟踪（资源不关联到标题）。
        """
        if not text:
            return
        self._current_list_id = None
        self.consume_tracked_assets()  # 丢弃
        self.consume_link_urls()       # 丢弃
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
        """添加普通段落元素，消费跟踪的资源和链接 URL。"""
        self._current_list_id = None
        asset_ids = self.consume_tracked_assets()
        link_urls = self.consume_link_urls()
        element = ParsedElement(
            doc_id=self.doc_id,
            doc_version=self.doc_version,
            sequence_order=self._next_seq(),
            element_type=ElementType.paragraph,
            text=text,
            asset_ids=asset_ids,
            source_location=SourceLocation(section_path=list(self._section_path)),
        )
        if link_urls:
            element.metadata["link_urls"] = link_urls
        self.elements.append(element)

    def add_list_item(self, text: str) -> None:
        """添加列表项，自动创建列表容器元素（如果尚未创建）。

        列表项出现时清空资源跟踪（资源不关联到列表项）。
        """
        self.consume_tracked_assets()  # 丢弃
        self.consume_link_urls()       # 丢弃
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
        """添加未知类型元素（如不支持的内嵌对象）。"""
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
