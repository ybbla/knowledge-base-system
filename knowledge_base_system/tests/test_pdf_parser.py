"""PdfParser 单元测试。

使用 fitz 在测试中动态生成 PDF 文件，无需外部 fixture 文件。
"""

import io
import struct
import zlib

import fitz
import pytest

from app.core.models import AssetType, Document, ElementType
from parsers.pdf_parser import PdfParser


# ── 测试辅助函数 ──────────────────────────────────────────────────────

def _make_pdf_bytes(*, pages: int = 1, encryption: str | None = None) -> bytes:
    """创建简单 PDF 字节流。

    Args:
        pages: 页面数量。
        encryption: 加密密码，不传则生成无加密 PDF。
    """
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    buf = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256 if encryption else 0,
        owner_pw="owner",
        user_pw=encryption or "",
    )
    doc.close()
    return buf


def _make_text_pdf(text_blocks: list[dict], *, toc: list[tuple[int, str, int]] | None = None) -> bytes:
    """创建含文本块的 PDF。

    Args:
        text_blocks: [{"page": int, "text": str, "y": float, "font_size": float, "bold": bool}, ...]
        toc: 可选的 TOC 列表 [(level, title, page), ...]
    """
    doc = fitz.open()
    pages: dict[int, fitz.Page] = {}

    for block in text_blocks:
        page_num = block.get("page", 1)
        if page_num not in pages:
            pages[page_num] = doc.new_page()
        page = pages[page_num]

        text = block["text"]
        y = block.get("y", 72)
        x = block.get("x", 72)
        font_size = block.get("font_size", 12)
        bold = block.get("bold", False)
        fontname = "hebo" if bold else "helv"

        rect = fitz.Rect(x, y, page.rect.width - x, y + font_size * 2)
        page.insert_textbox(rect, text, fontname=fontname, fontsize=font_size)

    # 补充空页面
    for p in range(1, (max(pages) if pages else 1) + 1):
        if p not in pages:
            pages[p] = doc.new_page()

    if toc:
        doc.set_toc(toc)

    buf = doc.tobytes()
    doc.close()
    return buf


def _make_pdf_with_table(headers: list[str], rows: list[list[str]]) -> bytes:
    """创建含简单表格的 PDF。

    使用 fitz 绘制表格边框和文本，确保 find_tables() 能检测到。
    """
    doc = fitz.open()
    page = doc.new_page()

    num_cols = len(headers)
    num_rows = len(rows) + 1
    cell_w = 120
    cell_h = 24
    x0, y0 = 72, 72

    # 绘制所有单元格（含表头）
    for r in range(num_rows):
        for c in range(num_cols):
            rect = fitz.Rect(
                x0 + c * cell_w, y0 + r * cell_h,
                x0 + (c + 1) * cell_w, y0 + (r + 1) * cell_h,
            )
            page.draw_rect(rect, color=(0, 0, 0), width=0.5)
            text = headers[c] if r == 0 else rows[r - 1][c] if c < len(rows[r - 1]) else ""
            page.insert_textbox(
                fitz.Rect(rect.x0 + 2, rect.y0 + 2, rect.x1 - 2, rect.y1 - 2),
                text, fontname="helv", fontsize=10,
            )

    buf = doc.tobytes()
    doc.close()
    return buf


def _make_pdf_with_image() -> bytes:
    """创建含嵌入图片和文本的 PDF。"""
    doc = fitz.open()
    page = doc.new_page()

    # 添加文本
    text_rect = fitz.Rect(72, 36, page.rect.width - 72, 60)
    page.insert_textbox(text_rect, "Document with image", fontname="helv", fontsize=12)

    # 生成最小 PNG 并嵌入
    png_bytes = _make_minimal_png()
    rect = fitz.Rect(72, 72, 272, 272)
    page.insert_image(rect, stream=png_bytes)

    buf = doc.tobytes()
    doc.close()
    return buf


def _make_minimal_png() -> bytes:
    """生成合法的最小 PNG 图片字节（1x1 蓝色像素）。"""
    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = zlib.compress(b"\x00\x00\x00\xff")
    idat = chunk(b"IDAT", raw)
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _make_encrypted_pdf() -> bytes:
    """创建加密 PDF。"""
    return _make_pdf_bytes(pages=1, encryption="user123")


def _doc(content: bytes, source_uri: str = "memory://sample.pdf") -> Document:
    """创建测试用 Document，raw_content 为 PDF 字节。"""
    return Document(
        title="测试 PDF",
        source_type="pdf",
        source_uri=source_uri,
        metadata={"raw_content": content},
    )


# ── 测试类 ────────────────────────────────────────────────────────────

class TestPdfParser:
    def setup_method(self):
        self.parser = PdfParser()

    # 4.2 ──────────────────────────────────────────────────────────

    def test_supports(self):
        assert self.parser.supports("pdf")
        assert self.parser.supports("PDF")
        assert self.parser.supports("Pdf")
        assert not self.parser.supports("docx")
        assert not self.parser.supports("epub")
        assert not self.parser.supports("")

    # 4.3 ──────────────────────────────────────────────────────────

    def test_parse_basic_text(self):
        """验证基础文本解析：标题、段落、页码、顺序。"""
        pdf_bytes = _make_text_pdf([
            {"page": 1, "text": "Chapter 1 Overview", "y": 72, "font_size": 18},
            {"page": 1, "text": "This is the first paragraph of body text.", "y": 120, "font_size": 12},
            {"page": 2, "text": "Chapter 2 Configuration", "y": 72, "font_size": 18},
            {"page": 2, "text": "This is the second paragraph of body text.", "y": 120, "font_size": 12},
        ])

        result = self.parser.parse(_doc(pdf_bytes))

        titles = [el for el in result.elements if el.element_type == ElementType.title]
        paragraphs = [el for el in result.elements if el.element_type == ElementType.paragraph]

        assert len(titles) >= 2  # 大字体应被识别为标题
        assert len(paragraphs) >= 2
        assert result.doc.source_hash.startswith("sha256:")
        assert all(el.doc_id == result.doc.doc_id for el in result.elements)

    def test_page_numbers_in_elements(self):
        """验证每个元素关联正确页码。"""
        pdf_bytes = _make_text_pdf([
            {"page": 1, "text": "Page one content.", "y": 100, "font_size": 12},
            {"page": 2, "text": "Page two content.", "y": 100, "font_size": 12},
        ])

        result = self.parser.parse(_doc(pdf_bytes))

        pages = {el.source_location.page for el in result.elements if el.source_location.page is not None}
        assert 1 in pages
        assert 2 in pages

    # 4.4 ──────────────────────────────────────────────────────────

    def test_toc_and_section_path(self):
        """验证 TOC 映射为 title 元素且 section_path 正确传播。"""
        pdf_bytes = _make_text_pdf(
            [
                {"page": 1, "text": "Product Overview", "y": 72, "font_size": 18},
                {"page": 1, "text": "This product supports multi-format document ingestion.", "y": 130, "font_size": 12},
                {"page": 1, "text": "Features", "y": 200, "font_size": 16},
                {"page": 1, "text": "The system supports document parsing and retrieval.", "y": 260, "font_size": 12},
            ],
            toc=[
                (1, "Product Overview", 1),
                (2, "Features", 1),
            ],
        )

        result = self.parser.parse(_doc(pdf_bytes))

        toc_titles = [
            el for el in result.elements
            if el.element_type == ElementType.title and el.metadata.get("source") == "toc"
        ]
        assert len(toc_titles) == 2
        assert toc_titles[0].text == "Product Overview"
        assert toc_titles[0].metadata["heading_level"] == 1
        assert toc_titles[1].text == "Features"
        assert toc_titles[1].metadata["heading_level"] == 2

    # 4.5 ──────────────────────────────────────────────────────────

    def test_bold_title_detection(self):
        """验证粗体 12-13pt 短文本被识别为子标题。"""
        pdf_bytes = _make_text_pdf([
            {"page": 1, "text": "2.3 Data Model Design", "y": 72, "font_size": 12, "bold": True},
            {"page": 1, "text": "The data model includes core entities described below.", "y": 120, "font_size": 12, "bold": False},
        ])

        result = self.parser.parse(_doc(pdf_bytes))

        bold_titles = [
            el for el in result.elements
            if el.element_type == ElementType.title and el.metadata.get("is_bold")
        ]
        assert len(bold_titles) >= 1
        assert "Data Model" in bold_titles[0].text
        assert bold_titles[0].metadata["heading_level"] == 3

    # 4.6 ──────────────────────────────────────────────────────────

    def test_table_detection(self):
        """验证表格被解析为 table 元素。"""
        pdf_bytes = _make_pdf_with_table(
            headers=["Status", "Description", "Action"],
            rows=[["Processing", "Parsing document", "Wait"], ["Success", "Ingested", "Search"]],
        )

        result = self.parser.parse(_doc(pdf_bytes))

        tables = [el for el in result.elements if el.element_type == ElementType.table]
        assert len(tables) >= 1
        table_data = tables[0].structured_data["table"]
        assert "Status" in table_data["headers"]
        assert len(table_data["rows"]) >= 1

    # 4.7 ──────────────────────────────────────────────────────────

    def test_image_extraction(self):
        """验证内嵌图片创建 image Asset。"""
        pdf_bytes = _make_pdf_with_image()

        result = self.parser.parse(_doc(pdf_bytes))

        image_assets = [a for a in result.assets if a.asset_type == AssetType.image]
        assert len(image_assets) >= 1
        asset = image_assets[0]
        assert asset.content_hash.startswith("sha256:")
        assert asset.status.value == "pending"
        assert hasattr(asset, "_data")

        image_elements = [el for el in result.elements if el.element_type == ElementType.image]
        assert len(image_elements) >= 1
        assert image_assets[0].asset_id in image_elements[0].asset_ids

    # 4.8 ──────────────────────────────────────────────────────────

    def test_image_dedup(self):
        """验证相同图片不重复创建 Asset。"""
        pdf_bytes = _make_pdf_with_image()

        result = self.parser.parse(_doc(pdf_bytes))

        image_assets = [a for a in result.assets if a.asset_type == AssetType.image]
        hashes = {a.content_hash for a in image_assets}
        assert len(image_assets) == len(hashes)  # 每个 hash 只有一个 Asset

    # 4.9 ──────────────────────────────────────────────────────────

    def test_hyperlink_detection(self):
        """验证 URL 被识别为 Asset。"""
        pdf_bytes = _make_text_pdf([
            {"page": 1, "text": "Watch video https://example.com/demo.mp4", "y": 72, "font_size": 12},
            {"page": 1, "text": "Download doc https://files.example.com/report.pdf", "y": 120, "font_size": 12},
        ])

        result = self.parser.parse(_doc(pdf_bytes))

        video_assets = [a for a in result.assets if a.asset_type == AssetType.video]
        attachment_assets = [a for a in result.assets if a.asset_type == AssetType.attachment]

        assert any("demo.mp4" in a.original_uri for a in video_assets)
        assert any("report.pdf" in a.original_uri for a in attachment_assets)

    # 4.10 ─────────────────────────────────────────────────────────

    def test_header_footer_filtering(self):
        """验证多页 PDF 中重复出现的页眉页脚被过滤。"""
        pdf_bytes = _make_text_pdf([
            {"page": 1, "text": "Product Manual v2.0", "y": 30, "font_size": 9},
            {"page": 1, "text": "Chapter 1 main content goes here.", "y": 100, "font_size": 12},
            {"page": 2, "text": "Product Manual v2.0", "y": 30, "font_size": 9},
            {"page": 2, "text": "Chapter 2 main content goes here.", "y": 100, "font_size": 12},
            {"page": 3, "text": "Product Manual v2.0", "y": 30, "font_size": 9},
            {"page": 3, "text": "Chapter 3 main content goes here.", "y": 100, "font_size": 12},
            {"page": 4, "text": "Product Manual v2.0", "y": 30, "font_size": 9},
            {"page": 4, "text": "Chapter 4 main content goes here.", "y": 100, "font_size": 12},
        ])

        result = self.parser.parse(_doc(pdf_bytes))

        # 页眉 "Product Manual v2.0" 不应出现在 elements 中
        all_text = [el.text for el in result.elements]
        header_count = sum(1 for t in all_text if t == "Product Manual v2.0")
        assert header_count == 0, f"页眉未被过滤，出现了 {header_count} 次"

        # 正文应存在
        assert any("Chapter 1" in t for t in all_text)

    # 4.11 ─────────────────────────────────────────────────────────

    def test_block_merge_spacing(self):
        """验证垂直间距大时即使字体相同也分段。"""
        pdf_bytes = _make_text_pdf([
            {"page": 1, "text": "First paragraph text.", "y": 72, "font_size": 12},
            {"page": 1, "text": "Second paragraph text.", "y": 200, "font_size": 12},
        ])

        result = self.parser.parse(_doc(pdf_bytes))

        paragraphs = [el for el in result.elements if el.element_type == ElementType.paragraph]
        # 两个大间距的文本块应该保持为独立段落
        assert len(paragraphs) >= 2

    # 4.12 ────────────────────────────────────────────────────────

    def test_empty_pdf_raises_error(self):
        """空内容抛出 ValueError。"""
        with pytest.raises(ValueError, match="PDF 解析失败"):
            self.parser.parse(_doc(b""))

    def test_invalid_pdf_raises_error(self):
        """无效 PDF 抛出 ValueError。"""
        with pytest.raises(ValueError, match="PDF 解析失败"):
            self.parser.parse(_doc(b"not a pdf file"))

    def test_encrypted_pdf_raises_error(self):
        """加密 PDF 抛出明确错误。"""
        encrypted = _make_encrypted_pdf()
        with pytest.raises(ValueError, match="加密"):
            self.parser.parse(_doc(encrypted))

    def test_image_only_pdf_raises_clear_error(self):
        """扫描件 PDF（仅图片无文本层）抛出明确错误。"""
        doc = fitz.open()
        page = doc.new_page()
        png_bytes = _make_minimal_png()
        page.insert_image(fitz.Rect(72, 72, 272, 272), stream=png_bytes)
        buf = doc.tobytes()
        doc.close()

        with pytest.raises(ValueError, match="扫描件|无可提取"):
            self.parser.parse(_doc(buf))

    # 4.13 ────────────────────────────────────────────────────────

    def test_file_uri_reading(self, tmp_path):
        """验证从 file:// URI 读取 PDF。"""
        pdf_bytes = _make_text_pdf([
            {"page": 1, "text": "Content from a file-based PDF.", "y": 72, "font_size": 12},
        ])
        path = tmp_path / "document.pdf"
        path.write_bytes(pdf_bytes)

        doc = Document(
            title="File PDF",
            source_type="pdf",
            source_uri=f"file://{path}",
        )
        result = self.parser.parse(doc)

        assert result.doc.source_hash.startswith("sha256:")
        assert any("Content from a file-based PDF" in el.text for el in result.elements)
