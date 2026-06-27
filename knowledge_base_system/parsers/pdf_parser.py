"""PDF 文档解析器
使用 PyMuPDF (fitz) PDF 文件解析为统一ParseResult（ParsedElement + Asset），
与现MarkdownParser、DocxParser、XlsxParser、HtmlParser、PptxParser 的下游契约保持一致"""

import hashlib
import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import fitz

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
from app.core.paths import resolve_file_uri
from parsers.base import DocumentParser, ParseResult
from parsers.utils import classify_link

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────

TITLE_FONT_SIZE_THRESHOLD = 14.0        # >= 此字号的短文本识别为标题
BOLD_TITLE_MIN_SIZE = 12.0              # 粗体标题字号下限
BOLD_TITLE_MAX_SIZE = 13.0              # 粗体标题字号上限
MAX_TITLE_CHARS = 80                    # 标题最大字符数
HEADER_FOOTER_FONT_MAX = 10.0           # 页眉页脚最大字号
HEADER_FOOTER_Y_MARGIN = 0.15           # 页面顶部和底部的比例阈值
HEADER_FOOTER_MIN_REPEAT_PAGES = 3      # 页眉页脚最小重复页数
HEADER_FOOTER_MAX_CHARS = 100           # 页眉页脚最大字符数
PARAGRAPH_GAP_RATIO = 1.5               # 段落间距倍数（相对行高）

# 页码正则模式
PAGE_NUMBER_PATTERNS = [
    re.compile(r"^\d+$"),                        # 纯数 "42"
    re.compile(r"^[ivxlcdm]+$", re.IGNORECASE),  # 罗马数字: "iv"
    re.compile(r"^\d+\s*/\s*\d+$"),              # "3/20"
    re.compile(r"^-\s*\d+\s*-$"),                # "- 42 -"
    re.compile(r"^第\s*\d+\s*页?$"),          # 中文页码
]

# 视频 URL 正则（与其他解析器保持一致）
VIDEO_URL_RE = re.compile(
    r"https?://[^\s\])<\"']*(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov|\.m4v)[^\s\])<\"']*",
    re.IGNORECASE,
)

# 附件扩展名
ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".csv", ".txt", ".md",
}

# 远程图片 URL 扩展名（用于识别指向图片文件的链接）
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
}


# ── 内部数据结构 ──────────────────────────────────────────────────────

@dataclass
class _TextBlock:
    """页面文本块，包含字体、位置和 span 边界信息。"""
    page: int
    y0: float
    y1: float
    x0: float
    x1: float
    text: str
    font_size: float
    is_bold: bool
    bbox: tuple[float, float, float, float]
    # 每个 span (文本, bbox四元，用于与 page.get_links() link rect 做交叉匹配确定锚文本
    span_bboxes: list[tuple[str, tuple[float, float, float, float]]] = field(default_factory=list)


@dataclass
class _AssetRecord:
    """内部资源记录，包含 Asset 和去重键。"""
    asset: Asset
    key: tuple[str, str]


@dataclass
class _PdfParseState:
    """PDF 解析过程中的可变状态。"""
    doc_id: str
    doc_version: int
    elements: list[ParsedElement] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    assets_by_key: dict[tuple[str, str], _AssetRecord] = field(default_factory=dict)
    section_path: list[str] = field(default_factory=list)
    seq: int = 0
    _counters: dict[str, int] = field(default_factory=dict)

    def next_seq(self) -> int:
        """生成递增的元素序号。"""
        self.seq += 1
        return self.seq

    _PH_MAP = {"image": "image", "video": "video", "image_link": "image",
               "video_link": "video", "document_link": "doc", "web_link": "web"}

    def next_ph(self, asset_type: str) -> str:
        """生成递增占位符 {{type:n}}。"""
        prefix = self._PH_MAP.get(asset_type, "res")
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{{{{{prefix}:{self._counters[prefix]}}}}}"


# ── PdfParser ──────────────────────────────────────────────────────

class PdfParser(DocumentParser):
    """将 PDF 文档解析为统一的 ParsedElement 和 Asset。

    使用字体启发式与目录双重策略检测标题，并过滤页眉、页脚和页码。
    """

    SUPPORTED_TYPES = {"pdf"}

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """将 PDF 解析为结构化元素和资源列表。"""
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not content:
            raise ValueError("PDF 解析失败：文档内容为空")

        try:
            pdf = fitz.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"PDF 解析失败：{exc}") from exc

        if pdf.is_encrypted:
            pdf.close()
            raise ValueError("PDF 解析失败：文档已加密，暂不支持加PDF")

        if pdf.page_count == 0:
            pdf.close()
            raise ValueError("PDF 解析失败：文档无页面")

        state = _PdfParseState(doc.doc_id, doc.version)

        try:
            # 获取目录并构建页码到标题的映射。
            toc_entries = self._build_toc_map(pdf)

            # 第一遍：收集所有页面文本块
            all_blocks: list[_TextBlock] = []
            for page_num in range(pdf.page_count):
                page = pdf[page_num]
                page_blocks = self._extract_blocks(page, page_num + 1)
                all_blocks.extend(page_blocks)

            # 检测并标记页眉页脚
            header_footer_keys = self._detect_header_footer_blocks(
                all_blocks, pdf.page_count
            )

            # 第二遍：逐页生成元素
            for page_num in range(pdf.page_count):
                page = pdf[page_num]
                page_number = page_num + 1
                page_height = page.rect.height

                # 该页TOC 标题
                page_titles = toc_entries.get(page_number, [])

                # 该页的文本块（过滤页眉页脚）
                page_blocks = [
                    b for b in all_blocks
                    if b.page == page_number and not self._is_header_footer(
                        b, header_footer_keys, page_height
                    )
                ]

                # 合并相邻块为段落
                merged_blocks = self._merge_adjacent_blocks(page_blocks)

                # 生成元素
                self._process_page(
                    page, page_number, merged_blocks, page_titles,
                    state, doc, pdf,
                )

            # 检查是否提取到有效文本，unknown 元素不计入。
            text_elements = [
                el for el in state.elements
                if el.element_type != ElementType.unknown
            ]
            if not text_elements:
                has_images = bool(state.assets)
                if has_images:
                    raise ValueError(
                        "PDF 解析失败：文档可能为扫描件，无可提取文本层，"
                        "建议使用 OCR 预处理后再入库"
                    )
                raise ValueError("PDF 解析失败：无可提取的文本内容")

            doc.source_hash = compute_hash(content)
            return ParseResult(doc=doc, elements=state.elements, assets=state.assets)

        except ValueError:
            # 重新抛出已知错误，确保在 finally 之前处理
            raise
        finally:
            try:
                pdf.close()
            except Exception:
                pass  # 忽略重复关闭错误

    # ── TOC 处理 ─────────────────────────────────────────────────

    @staticmethod
    def _build_toc_map(pdf: fitz.Document) -> dict[int, list[tuple[int, str]]]:
        """构建页码TOC 标题列表的映射
        Returns:
            dict: {page_number: [(level, title), ...]}  level 升序排列        """
        toc_map: dict[int, list[tuple[int, str]]] = {}
        try:
            toc = pdf.get_toc(simple=True)
        except Exception:
            logger.debug("PDF 目录提取失败，将仅依赖字体启发式检测标题")
            return toc_map

        for entry in toc:
            if len(entry) != 3:
                continue
            level, title, page_num = entry
            title = title.strip()
            if not title:
                continue
            toc_map.setdefault(int(page_num), []).append((int(level), title))

        # 每页level 排序
        for page_num in toc_map:
            toc_map[page_num].sort(key=lambda item: item[0])

        return toc_map

    # ── 文本块提────────────────────────────────────────────────

    @staticmethod
    def _extract_blocks(page: fitz.Page, page_number: int) -> list[_TextBlock]:
        """从页面提取全部文本块，并保留字体与位置信息。"""
        blocks: list[_TextBlock] = []
        try:
            text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        except Exception:
            logger.debug("页面 %d 文本提取失败，已跳过", page_number)
            return blocks

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                # 图片等非文本块由资源处理分支负责。
                continue

            bbox = block["bbox"]
            y0, y1 = bbox[1], bbox[3]
            x0, x1 = bbox[0], bbox[2]

            # 收集该块所span 的文本和字体信息
            all_text_parts: list[str] = []
            font_sizes: list[float] = []
            font_flags: list[int] = []
            font_names: list[str] = []
            span_bboxes: list[tuple[str, tuple[float, float, float, float]]] = []

            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                    font_sizes.append(span.get("size", 0))
                    font_flags.append(span.get("flags", 0))
                    font_names.append(span.get("font", ""))
                    # 收集每个 span 的文本和 bbox，用于后续与 link rect 交叉匹配
                    span_bboxes.append((span.get("text", ""), tuple(span.get("bbox", (0, 0, 0, 0)))))
                all_text_parts.append(line_text)

            combined_text = " ".join(
                part for part in all_text_parts if part
            ).strip()
            if not combined_text:
                continue

            avg_font_size = statistics.mean(font_sizes) if font_sizes else 0.0

            # 粗体判断：flags bit 4 (16) 或字体名"bold"
            has_bold_flag = any(f & 16 for f in font_flags)
            has_bold_name = any("bold" in fn.lower() for fn in font_names)
            is_bold = has_bold_flag or has_bold_name

            blocks.append(_TextBlock(
                page=page_number,
                y0=y0,
                y1=y1,
                x0=x0,
                x1=x1,
                text=combined_text,
                font_size=avg_font_size,
                is_bold=is_bold,
                bbox=tuple(bbox),
                span_bboxes=span_bboxes,
            ))

        # (y0, x0) 排序模拟阅读顺序
        blocks.sort(key=lambda b: (b.y0, b.x0))
        return blocks

    # ── 页眉页脚过滤 ──────────────────────────────────────────────

    def _detect_header_footer_blocks(
        self,
        all_blocks: list[_TextBlock],
        page_count: int,
    ) -> set[tuple[int, str]]:
        """检测页眉页脚块，返回应过滤(y_bucket, normalized_text) 集合
        使用两种策略        1. 重复文本检测：相同文本3 个页面相y 区间出现
        2. y 坐标位置过滤：极端位+ 小字号的文本
        """
        if page_count < HEADER_FOOTER_MIN_REPEAT_PAGES:
            return set()

        # 策略 1：构(y_bucket, text) set of pages 的映        repeat_map: dict[tuple[int, str], set[int]] = {}
        for block in all_blocks:
            text = block.text.strip()
            if not text:
                continue
            # 10pt 为粒度分y 坐标
            y_bucket = int(block.y0 / 10) * 10
            key = (y_bucket, text)
            repeat_map.setdefault(key, set()).add(block.page)

        # 3 个页面出现的标记为页眉页        header_footer_keys: set[tuple[int, str]] = set()
        for key, pages in repeat_map.items():
            if len(pages) >= HEADER_FOOTER_MIN_REPEAT_PAGES:
                header_footer_keys.add(key)

        return header_footer_keys

    @staticmethod
    def _is_header_footer(
        block: _TextBlock,
        header_footer_keys: set[tuple[int, str]],
        page_height: float,
    ) -> bool:
        """判断单个文本块是否属于页眉或页脚。"""
        text = block.text.strip()
        if not text:
            return True

        # 策略一：命中跨页重复文本。
        y_bucket = int(block.y0 / 10) * 10
        if (y_bucket, text) in header_footer_keys:
            return True

        # 策略二：页面边缘的小字号短文本。
        if block.y0 < page_height * HEADER_FOOTER_Y_MARGIN:
            if block.font_size <= HEADER_FOOTER_FONT_MAX and len(text) <= HEADER_FOOTER_MAX_CHARS:
                return True
        if block.y1 > page_height * (1 - HEADER_FOOTER_Y_MARGIN):
            if block.font_size <= HEADER_FOOTER_FONT_MAX and len(text) <= HEADER_FOOTER_MAX_CHARS:
                # 检查是否为页码模式
                if any(pat.search(text) for pat in PAGE_NUMBER_PATTERNS):
                    return True
                return True

        return False

    # ── 块合────────────────────────────────────────────────────

    @staticmethod
    def _merge_adjacent_blocks(
        blocks: list[_TextBlock],
    ) -> list[_TextBlock]:
        """合并字体一致、垂直间距小的相邻文本块
        当间> 1.5 倍行高时视为新段落        """
        if not blocks:
            return []

        merged: list[_TextBlock] = []
        current = blocks[0]

        for next_block in blocks[1:]:
            # 字体特征一致时允许合并。
            same_font = (
                abs(current.font_size - next_block.font_size) < 0.5
                and current.is_bold == next_block.is_bold
            )

            # 垂直间距
            gap = next_block.y0 - current.y1
            if current.font_size > 0:
                threshold = current.font_size * PARAGRAPH_GAP_RATIO
            else:
                threshold = 12.0

            if same_font and gap <= max(threshold, 2.0):
                # 合并文本
                combined = f"{current.text} {next_block.text}".strip()
                # 合并 span_bboxes，保持原span 顺序
                merged_span_bboxes = current.span_bboxes + next_block.span_bboxes
                # 更新合并后的文本块信息。
                current = _TextBlock(
                    page=current.page,
                    y0=current.y0,
                    y1=next_block.y1,
                    x0=min(current.x0, next_block.x0),
                    x1=max(current.x1, next_block.x1),
                    text=combined,
                    font_size=current.font_size,
                    is_bold=current.is_bold,
                    bbox=(
                        min(current.bbox[0], next_block.bbox[0]),
                        min(current.bbox[1], next_block.bbox[1]),
                        max(current.bbox[2], next_block.bbox[2]),
                        max(current.bbox[3], next_block.bbox[3]),
                    ),
                    span_bboxes=merged_span_bboxes,
                )
            else:
                merged.append(current)
                current = next_block

        merged.append(current)
        return merged

    # ── 页面处理 ──────────────────────────────────────────────────

    def _process_page(
        self,
        page: fitz.Page,
        page_number: int,
        blocks: list[_TextBlock],
        toc_titles: list[tuple[int, str]],
        state: _PdfParseState,
        doc: Document,
        pdf: fitz.Document,
    ) -> None:
        """处理单页：先插入目录标题，再处理文本、表格和图片。"""

        # 1. 插入 TOC 标题
        for level, title in toc_titles:
            self._add_title(state, title, level, page_number)

        # 2. 处理表格
        table_regions = self._detect_tables(page)
        table_y_ranges: list[tuple[float, float]] = []
        for table_data in table_regions:
            table_block = self._add_table(table_data, page_number, state, page, doc)
            if table_block is not None:
                table_y_ranges.append((table_block.y0, table_block.y1))

        # 3. 处理文本块（排除表格覆盖的区域），建block→element 映射
        block_to_element: dict[int, int] = {}
        for bi, block in enumerate(blocks):
            if self._in_table_region(block, table_y_ranges):
                continue
            self._add_text_block(block, state, page_number, doc)
            # 记录当前 block 索引 最新追加的元素索引
            block_to_element[bi] = len(state.elements) - 1

        # 3.5 链接交叉匹配：link rect span bbox 锚文精确关联到元        self._match_links_to_blocks(page, blocks, block_to_element, state, doc, page_number)

        # 4. 提取图片（过滤页眉页脚区域）
        self._extract_page_images(page, page_number, state, doc, pdf)

        # 5. 处理孤立页面超链接（兜底 + 页眉页脚过滤        self._asset_ids_for_page_links(page, state, doc, page_number)

    # ── 链接匹配 ──────────────────────────────────────────────────

    def _match_links_to_blocks(
        self,
        page: fitz.Page,
        blocks: list[_TextBlock],
        block_to_element: dict[int, int],
        state: _PdfParseState,
        doc: Document,
        page_number: int,
    ) -> None:
        """将页面超链接通过 link rect span bbox 交叉匹配精确关联到所属元素
        page.get_links() 返回的每个链接，使用from 矩形与所有块        span_bboxes 做交集判断（阈0.1），匹配到的 span 文本作为锚文本，
        资源链接创建 Asset 并写asset_data，普通网页链接写metadata["link_urls"]        未匹配到的链接不在此处理，由 _asset_ids_for_page_links() 兜底        """
        try:
            links = page.get_links()
        except Exception:
            return

        page_height = page.rect.height
        matched_uris: set[str] = set()

        for link in links:
            uri = link.get("uri", "")
            if not uri or not uri.startswith(("http://", "https://")):
                continue

            link_rect = link.get("from")
            if link_rect is None:
                continue

            # 过滤页眉和页脚区域的链接。
            lr = fitz.Rect(link_rect)
            if lr.y0 < page_height * HEADER_FOOTER_Y_MARGIN:
                continue
            if lr.y1 > page_height * (1 - HEADER_FOOTER_Y_MARGIN):
                continue

            # 与所有文本块的 span 边界做交叉匹配。
            best_match: tuple[int, str, float] | None = None  # 块序号、锚文本、重叠比例
            for bi, block in enumerate(blocks):
                if bi not in block_to_element:
                    continue
                for span_text, span_bbox in block.span_bboxes:
                    sr = fitz.Rect(span_bbox)
                    if sr.intersects(lr):
                        ratio = (sr & lr).get_area() / max(sr.get_area(), 1.0)
                        if ratio >= 0.1:
                            if best_match is None or ratio > best_match[2]:
                                best_match = (bi, span_text, ratio)

            if best_match is not None:
                bi, anchor_text, _ratio = best_match
                ei = block_to_element[bi]
                element = state.elements[ei]
                # 资源链接创建 Asset，与段落规则一致
                asset_type = self._asset_type_for_url(uri)
                if asset_type is not None:
                    display_text = anchor_text if anchor_text and anchor_text != uri else ""
                    asset = self._asset_for_url(uri, asset_type, state, doc, {}, display_text=display_text)
                    if not any(ad.asset_id == asset.asset_id for ad in element.asset_data):
                        ph = state.next_ph(asset_type.value)
                        element.asset_data.append(AssetData(placeholder=ph, asset_id=asset.asset_id))
                    if not asset.element_id:
                        asset.element_id = element.element_id
                matched_uris.add(uri)

    # ── 标题 ──────────────────────────────────────────────────────

    def _add_title(
        self,
        state: _PdfParseState,
        text: str,
        level: int,
        page_number: int,
    ) -> None:
        """添加标题元素并更新 section_path。"""
        # 弹出 >= 当前层级的旧标题
        while len(state.section_path) >= level:
            state.section_path.pop()
        state.section_path.append(text)

        self._append_element(state, ParsedElement(
            doc_id=state.doc_id,
            doc_version=state.doc_version,
            sequence_order=state.next_seq(),
            element_type=ElementType.title,
            text=text,
            source_location=SourceLocation(
                page=page_number,
                section_path=list(state.section_path),
            ),
            metadata={"heading_level": level},
        ))

    # ── 文本ParsedElement ─────────────────────────────────────

    def _add_text_block(
        self,
        block: _TextBlock,
        state: _PdfParseState,
        page_number: int,
        doc: Document,
    ) -> None:
        """将文本块转换为标题或段落元素。"""
        text = block.text.strip()
        if not text:
            return

        # 判断是否为标题（字体启发式）
        is_heading = False
        heading_level = 1

        if block.font_size >= TITLE_FONT_SIZE_THRESHOLD and len(text) <= MAX_TITLE_CHARS:
            # 大字号短文本 标题
            is_heading = True
            if block.font_size >= 18:
                heading_level = 1
            elif block.font_size >= 16:
                heading_level = 2
            else:
                heading_level = 3

        elif (
            BOLD_TITLE_MIN_SIZE <= block.font_size <= BOLD_TITLE_MAX_SIZE
            and block.is_bold
            and len(text) <= MAX_TITLE_CHARS
        ):
            # 粗体短文本按子标题处理。
            is_heading = True
            heading_level = 3

        if is_heading:
            # 更新 section_path
            while len(state.section_path) >= heading_level:
                state.section_path.pop()
            state.section_path.append(text)

            element_type = ElementType.title
            metadata: dict[str, Any] = {"heading_level": heading_level}
        else:
            element_type = ElementType.paragraph
            metadata: dict[str, Any] = {}

        self._append_element(state, ParsedElement(
            doc_id=state.doc_id,
            doc_version=state.doc_version,
            sequence_order=state.next_seq(),
            element_type=element_type,
            text=text,
            source_location=SourceLocation(
                page=page_number,
                section_path=list(state.section_path),
            ),
            metadata=metadata,
        ))

    # ── 表格检──────────────────────────────────────────────────

    @staticmethod
    def _detect_tables(page: fitz.Page) -> list[dict[str, Any]]:
        """检测页面表格，并提供防御性降级。"""
        if not hasattr(page, "find_tables"):
            logger.debug("当前 PyMuPDF 版本不支持 find_tables，跳过表格检测")
            return []

        try:
            tables = page.find_tables()
        except Exception:
            logger.debug("页面表格检测异常，降级为文本处理")
            return []

        if tables is None:
            return []

        result: list[dict[str, Any]] = []
        for table in tables:
            try:
                extracted = table.extract()
                if not extracted or len(extracted) < 2:
                    continue
                ncols = len(extracted[0]) if extracted else 0
                result.append({
                    "headers": [{"text": str(cell or "")} for cell in extracted[0]],
                    "rows": extracted[1:],
                    "bbox": getattr(table, "bbox", None),
                    "cells_bbox": getattr(table, "cells", None),
                    "ncols": ncols,
                })
            except Exception:
                logger.debug("表格数据提取失败，跳过该表格")
                continue

        return result

    def _add_table(
        self,
        table_data: dict[str, Any],
        page_number: int,
        state: _PdfParseState,
        page: fitz.Page | None = None,
        doc: Document | None = None,
    ) -> _TextBlock | None:
        """将检测到的表格转换为 table 类型 ParsedElement
        同时匹配页面链接到表格单元格（按坐标交叉匹配），
        资源链接创建 Asset，规则与段落元素一致。"""
        headers = table_data["headers"]
        raw_rows = table_data["rows"]
        if not raw_rows:
            return None

        # ── 按坐标匹配链接到单元格（资源链接创建 Asset，与段落规则一致）──
        table_asset_ids: list[Asset] = []
        cell_bboxes = table_data.get("cells_bbox")
        ncols = table_data.get("ncols", 0)
        links = page.get_links() if page is not None else []

        if cell_bboxes and ncols and links:
            for cell_idx, cell_bbox in enumerate(cell_bboxes):
                for link in links:
                    lr = fitz.Rect(link.get("from", (0, 0, 0, 0)))
                    if fitz.Rect(cell_bbox).intersects(lr):
                        uri = link.get("uri", "")
                        if not uri:
                            continue
                        asset_type = self._asset_type_for_url(uri)
                        if asset_type is not None:
                            if doc is not None:
                                asset = self._asset_for_url(uri, asset_type, state, doc, {})
                                table_asset_ids.append(asset)
                        break  # 一个单元格最多一个链接
        rows: list[dict[str, Any]] = []
        for row in raw_rows:
            rows.append({
                "cells": [{"text": str(cell or "")} for cell in row],
            })

        structured: dict[str, Any] = {
            "table": {
                "caption": "",
                "headers": headers,
                "rows": rows,
            },
        }

        text_parts: list[str] = []
        if headers:
            text_parts.append(" | ".join(h["text"] for h in headers))
        for row in rows:
            text_parts.append(" | ".join(cell["text"] for cell in row["cells"]))

        table_asset_data: list[AssetData] = []
        for a in {a.asset_id: a for a in table_asset_ids}.values():
            ph = state.next_ph(a.asset_type.value)
            table_asset_data.append(AssetData(placeholder=ph, asset_id=a.asset_id))

        self._append_element(state, ParsedElement(
            doc_id=state.doc_id,
            doc_version=state.doc_version,
            sequence_order=state.next_seq(),
            element_type=ElementType.table,
            text="\n".join(part for part in text_parts if part.strip()),
            structured_data=structured,
            asset_data=table_asset_data,
            source_location=SourceLocation(
                page=page_number,
                section_path=list(state.section_path),
            ),
            metadata={},
        ))

        bbox = table_data.get("bbox")
        if bbox:
            return _TextBlock(
                page=page_number,
                y0=bbox[1],
                y1=bbox[3],
                x0=bbox[0],
                x1=bbox[2],
                text="",
                font_size=0,
                is_bold=False,
                bbox=tuple(bbox),
            )
        return None

    @staticmethod
    def _in_table_region(
        block: _TextBlock,
        table_y_ranges: list[tuple[float, float]],
    ) -> bool:
        """判断文本块是否落在已识别的表格区域内。"""
        for y0, y1 in table_y_ranges:
            # 只要纵向范围重叠，就视为表格区域。
            if not (block.y1 < y0 or block.y0 > y1):
                return True
        return False

    # ── 图片提取 ──────────────────────────────────────────────────

    def _extract_page_images(
        self,
        page: fitz.Page,
        page_number: int,
        state: _PdfParseState,
        doc: Document,
        pdf: fitz.Document,
    ) -> None:
        """提取页面内嵌图片，创image Asset image 类型 ParsedElement
        过滤页眉页脚区域的图片（Y 坐标在页面顶15% 以内或底15% 以内）        """
        image_list = page.get_images(full=True)
        if not image_list:
            return

        page_height = page.rect.height

        # 获取图片位置信息，用于过滤页眉页脚图        image_bboxes: dict[int, tuple[float, float, float, float]] = {}
        try:
            for info in page.get_image_info():
                idx = info.get("number")
                bbox = info.get("bbox")
                if idx is not None and bbox is not None:
                    image_bboxes[idx] = tuple(bbox)
        except Exception:
            pass  # get_image_info 失败时不过滤图片位置

        for idx, img in enumerate(image_list):
            xref = img[0]

            # 过滤页眉和页脚区域中的图片。
            if idx in image_bboxes:
                _by0, _by1 = image_bboxes[idx][1], image_bboxes[idx][3]
                if _by0 < page_height * HEADER_FOOTER_Y_MARGIN:
                    continue
                if _by1 > page_height * (1 - HEADER_FOOTER_Y_MARGIN):
                    continue

            try:
                base_image = pdf.extract_image(xref)
            except Exception:
                logger.debug("页面 %d 图片 xref=%d 提取失败", page_number, xref)
                continue

            image_bytes = base_image.get("image")
            if not image_bytes:
                continue

            content_hash_val = f"sha256:{hashlib.sha256(image_bytes).hexdigest()}"
            key = ("image", content_hash_val)

            # 去重
            existing = state.assets_by_key.get(key)
            if existing is not None:
                asset = existing.asset
            else:
                ext = base_image.get("ext", "png")
                filename = f"pdf-image-p{page_number}-{xref}.{ext}"
                asset = Asset(
                    doc_id=doc.doc_id,
                    asset_type=AssetType.image,
                    original_uri="",                # 嵌入类型无外部来源
                    storage_uri=None,
                    content_hash=content_hash_val,
                    status=AssetStatus.ready,
                    extracted_text=None,
                    metadata={
                        "page": page_number,
                        "xref": xref,
                        "file_name": filename,
                        "source": "pdf_image",
                        "width": base_image.get("width"),
                        "height": base_image.get("height"),
                    },
                )
                object.__setattr__(asset, "_data", image_bytes)
                state.assets.append(asset)
                state.assets_by_key[key] = _AssetRecord(asset=asset, key=key)

            # 图片作为附属资源，由段落元素承载位置和引用信息。
            ph = state.next_ph("image")
            self._append_element(
                state,
                ParsedElement(
                    doc_id=state.doc_id,
                    doc_version=state.doc_version,
                    sequence_order=state.next_seq(),
                    element_type=ElementType.paragraph,
                    text=ph,
                    asset_data=[AssetData(placeholder=ph, asset_id=asset.asset_id)],
                    source_location=SourceLocation(
                        page=page_number,
                        section_path=list(state.section_path),
                    ),
                    metadata={
                        "page": page_number,
                        "xref": xref,
                        "file_name": filename,
                    },
                ),
            )

    # ── 超链/ URL 资源 ─────────────────────────────────────────

    def _asset_ids_for_page_links(
        self,
        page: fitz.Page,
        state: _PdfParseState,
        doc: Document,
        page_number: int,
    ) -> None:
        """处理 _match_links_to_blocks 未匹配到的孤立页面超链接（兜底逻辑）
        对未span 匹配的页面超链接创建 Asset 并关联到当前页最后一个非 image 元素        过滤页眉页脚区域链接        """
        try:
            links = page.get_links()
        except Exception:
            return

        page_height = page.rect.height

        for link in links:
            uri = link.get("uri", "")
            if not uri or not uri.startswith(("http://", "https://")):
                continue

            # 过滤页眉页脚区域的链接（_match_links_to_blocks 保持一致）
            link_rect = link.get("from")
            if link_rect is not None:
                lr = fitz.Rect(link_rect)
                if lr.y0 < page_height * HEADER_FOOTER_Y_MARGIN:
                    continue
                if lr.y1 > page_height * (1 - HEADER_FOOTER_Y_MARGIN):
                    continue

            # 跳过已在 _match_links_to_blocks 中匹配的链接
            asset_type = self._asset_type_for_url(uri)
            if asset_type is not None:
                if (asset_type.value, uri) in state.assets_by_key:
                    continue

            # 资源链接创建 Asset，与段落规则一致
            if asset_type is not None:
                asset = self._asset_for_url(uri, asset_type, state, doc, {})
                # 兜底关联到当前页最后一个元素
                for el in reversed(state.elements):
                    if not any(ad.asset_id == asset.asset_id for ad in el.asset_data):
                        ph = state.next_ph(asset_type.value)
                        el.asset_data.append(AssetData(placeholder=ph, asset_id=asset.asset_id))
                    if not asset.element_id:
                        asset.element_id = el.element_id
                    break

    def _asset_for_url(
        self,
        url: str,
        asset_type: AssetType,
        state: _PdfParseState,
        doc: Document,
        metadata: dict[str, Any],
        display_text: str = "",
    ) -> Asset:
        """创建或复用 Asset，按 URL 和资源类型去重。"""
        key = (asset_type.value, url)
        existing = state.assets_by_key.get(key)
        if existing is not None:
            return existing.asset

        asset = Asset(
            doc_id=doc.doc_id,
            asset_type=asset_type,
            original_uri=url,
            display_text=display_text,
            storage_uri=None,
            status=AssetStatus.ready,
            extracted_text=None,
            metadata={
                **metadata,
            },
        )
        state.assets.append(asset)
        state.assets_by_key[key] = _AssetRecord(asset=asset, key=key)
        return asset

    def _asset_type_for_url(self, url: str) -> AssetType | None:
        """根据 URL 模式判断资源类型：视图片 附件 None（普通网页链接）
        普通网页链接（无特殊后缀且非视频/图片）返None        不创Asset，仅作为 link_anchor 记录 URL 和锚文本        """
        if self._is_video_url(url):
            return AssetType.video_link
        if self._is_image_url(url):
            return AssetType.image_link
        if self._is_attachment_url(url):
            return AssetType.document_link
        return None

    def _is_video_url(self, url: str) -> bool:
        """判断 URL 是否为视频链接。"""
        return bool(VIDEO_URL_RE.search(url or ""))

    @staticmethod
    def _is_attachment_url(url: str) -> bool:
        """判断 URL 是否指向附件文件。"""
        path = url.split("?", 1)[0]
        suffix = PurePosixPath(path).suffix.lower()
        if suffix:
            return suffix in ATTACHMENT_EXTENSIONS
        return False

    @staticmethod
    def _is_image_url(url: str) -> bool:
        """按后缀判断 URL 是否指向远程图片。"""
        path = url.split("?", 1)[0]
        suffix = PurePosixPath(path).suffix.lower()
        return suffix in IMAGE_EXTENSIONS if suffix else False

    # ── 资源输出 ──────────────────────────────────────────────────

    @staticmethod
    def _append_element(state: _PdfParseState, element: ParsedElement) -> None:
        """添加元素，并通过 asset_id 回填 Asset.element_id。"""
        asset_ids = {ad.asset_id for ad in element.asset_data}
        for record in state.assets_by_key.values():
            if record.asset.asset_id in asset_ids and not record.asset.element_id:
                record.asset.element_id = element.element_id
        state.elements.append(element)

