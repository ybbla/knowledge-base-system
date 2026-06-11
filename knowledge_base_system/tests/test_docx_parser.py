import io
import base64
import os
import tempfile

import pytest
from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.core.models import Document, ElementType
from parsers.docx_parser import DocxParser


def _make_test_docx() -> bytes:
    """Create a minimal DOCX with heading, paragraph, and table."""
    doc = DocxDocument()

    doc.add_heading("测试文档", level=1)
    doc.add_paragraph("这是一个测试段落，用于验证 DOCX 解析器。")

    # Add a table
    table = doc.add_table(rows=3, cols=2)
    table.style = "Table Grid"
    # Header row
    table.cell(0, 0).text = "状态"
    table.cell(0, 1).text = "说明"
    # Data rows
    table.cell(1, 0).text = "处理中"
    table.cell(1, 1).text = "系统正在解析文档"
    table.cell(2, 0).text = "成功"
    table.cell(2, 1).text = "文档已进入知识库"

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestDocxParser:
    def setup_method(self):
        self.parser = DocxParser()

    def test_supported_types(self):
        assert self.parser.supports("docx")
        assert self.parser.SUPPORTED_TYPES == {"docx"}
        assert not self.parser.supports("pdf")

    def test_parse_headings_and_paragraphs(self):
        content = _make_test_docx()
        doc = Document(
            title="Test",
            source_type="docx",
            source_uri="memory://test",
            metadata={"raw_content": content},
        )
        result = self.parser.parse(doc)

        titles = [e for e in result.elements if e.element_type == ElementType.title]
        paragraphs = [e for e in result.elements if e.element_type == ElementType.paragraph]

        assert len(titles) >= 1
        assert titles[0].text == "测试文档"
        assert titles[0].metadata.get("heading_level") == 1
        assert len(paragraphs) >= 1

    def test_parse_table(self):
        content = _make_test_docx()
        doc = Document(
            title="Test",
            source_type="docx",
            source_uri="memory://test",
            metadata={"raw_content": content},
        )
        result = self.parser.parse(doc)

        tables = [e for e in result.elements if e.element_type == ElementType.table]
        assert len(tables) >= 1

        table = tables[0]
        assert table.structured_data is not None
        table_data = table.structured_data["table"]
        assert table_data["headers"] == ["状态", "说明"]
        assert len(table_data["rows"]) == 2

    def test_document_hash_set(self):
        content = _make_test_docx()
        doc = Document(
            title="Test",
            source_type="docx",
            source_uri="memory://test",
            metadata={"raw_content": content},
        )
        result = self.parser.parse(doc)
        assert result.doc.source_hash
        assert result.doc.source_hash.startswith("sha256:")

    def test_all_elements_have_sequence_order(self):
        content = _make_test_docx()
        doc = Document(
            title="Test",
            source_type="docx",
            source_uri="memory://test",
            metadata={"raw_content": content},
        )
        result = self.parser.parse(doc)

        orders = [e.sequence_order for e in result.elements]
        assert all(o > 0 for o in orders)
        assert len(set(orders)) == len(orders)

    def test_returns_parse_result(self):
        content = _make_test_docx()
        doc = Document(
            title="Test",
            source_type="docx",
            source_uri="memory://test",
            metadata={"raw_content": content},
        )
        result = self.parser.parse(doc)
        assert result.doc == doc
        assert len(result.elements) > 0
        for el in result.elements:
            assert el.doc_id == doc.doc_id

    def test_parse_list_items(self):
        docx = DocxDocument()
        docx.add_paragraph("First item", style="List Bullet")
        docx.add_paragraph("Second item", style="List Bullet")
        buf = io.BytesIO()
        docx.save(buf)

        doc = Document(
            title="List",
            source_type="docx",
            source_uri="memory://list",
            metadata={"raw_content": buf.getvalue()},
        )
        result = self.parser.parse(doc)

        lists = [e for e in result.elements if e.element_type == ElementType.list]
        items = [
            e for e in result.elements
            if e.element_type == ElementType.paragraph and e.parent_element_id
        ]
        assert len(lists) == 1
        assert [item.text for item in items] == ["First item", "Second item"]
        assert all(item.parent_element_id == lists[0].element_id for item in items)

    def test_parse_merged_table_cells_are_expanded(self):
        docx = DocxDocument()
        table = docx.add_table(rows=2, cols=3)
        table.cell(0, 0).text = "A"
        table.cell(0, 1).text = "B"
        table.cell(0, 2).text = "C"
        table.cell(1, 0).text = "Merged"
        table.cell(1, 0).merge(table.cell(1, 1))
        table.cell(1, 2).text = "Tail"
        buf = io.BytesIO()
        docx.save(buf)

        doc = Document(
            title="Merged",
            source_type="docx",
            source_uri="memory://merged",
            metadata={"raw_content": buf.getvalue()},
        )
        result = self.parser.parse(doc)
        table_el = next(e for e in result.elements if e.element_type == ElementType.table)
        row = table_el.structured_data["table"]["rows"][0]["cells"]
        assert [cell["text"] for cell in row] == ["Merged", "Merged", "Tail"]

    def test_extract_embedded_image_from_raw_content(self):
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )
        docx = DocxDocument()
        image_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            image_file.write(png_bytes)
            image_file.close()
            docx.add_picture(image_file.name)
            buf = io.BytesIO()
            docx.save(buf)
        finally:
            os.unlink(image_file.name)

        doc = Document(
            title="Image",
            source_type="docx",
            source_uri="memory://image",
            metadata={"raw_content": buf.getvalue()},
        )
        result = self.parser.parse(doc)

        assert len(result.assets) == 1
        assert result.assets[0].content_hash.startswith("sha256:")
        images = [e for e in result.elements if e.element_type == ElementType.image]
        assert len(images) == 1
        assert result.assets[0].source_element_id == images[0].element_id
        assert images[0].asset_ids == [result.assets[0].asset_id]

    def test_unsupported_embedded_object_degrades_to_unknown(self):
        docx = DocxDocument()
        paragraph = docx.add_paragraph()
        paragraph._p.append(OxmlElement("w:object"))
        buf = io.BytesIO()
        docx.save(buf)

        doc = Document(
            title="Unknown",
            source_type="docx",
            source_uri="memory://unknown",
            metadata={"raw_content": buf.getvalue()},
        )
        result = self.parser.parse(doc)

        unknowns = [e for e in result.elements if e.element_type == ElementType.unknown]
        assert len(unknowns) == 1
        assert "Unsupported embedded DOCX object" in unknowns[0].text
