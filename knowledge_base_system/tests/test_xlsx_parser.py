import io
import zipfile

import pytest
from openpyxl import Workbook

from app.core.models import AssetType, Document, ElementType
from parsers.xlsx_parser import XlsxParser


def _xlsx_bytes(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _doc(raw: bytes, source_uri: str = "memory://xlsx") -> Document:
    return Document(
        title="XLSX",
        source_type="xlsx",
        source_uri=source_uri,
        metadata={"raw_content": raw},
    )


def _inject_formula_cache(raw: bytes, value: str) -> bytes:
    """向测试工作簿写入公式缓存值，用于覆盖 data_only 读取路径。"""
    input_buffer = io.BytesIO(raw)
    output_buffer = io.BytesIO()
    with zipfile.ZipFile(input_buffer, "r") as zin:
        with zipfile.ZipFile(output_buffer, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "xl/worksheets/sheet1.xml":
                    text = data.decode("utf-8")
                    text = text.replace(
                        '<c r="B2"><f>SUM(A2:A3)</f><v></v></c>',
                        f'<c r="B2"><f>SUM(A2:A3)</f><v>{value}</v></c>',
                    )
                    data = text.encode("utf-8")
                zout.writestr(item, data)
    return output_buffer.getvalue()


class TestXlsxParser:
    def setup_method(self):
        self.parser = XlsxParser()

    def test_supported_types(self):
        assert self.parser.supports("xlsx")
        assert self.parser.supports("XLSX")
        assert not self.parser.supports("xls")

    def test_parse_visible_sheets_and_skip_hidden(self):
        wb = Workbook()
        ws1 = wb.active
        ws1.title = "产品"
        ws1.append(["名称", "状态"])
        ws1.append(["知识库", "启用"])
        ws2 = wb.create_sheet("流程")
        ws2["A1"] = "步骤"
        ws2["A2"] = "上传"
        hidden = wb.create_sheet("隐藏")
        hidden.sheet_state = "hidden"
        hidden["A1"] = "不应解析"

        result = self.parser.parse(_doc(_xlsx_bytes(wb)))

        titles = [el for el in result.elements if el.element_type == ElementType.title]
        assert [title.text for title in titles] == ["产品", "流程"]
        assert all(title.source_location.section_path == [title.text] for title in titles)
        assert "隐藏" not in [el.text for el in result.elements]
        assert result.doc.source_hash.startswith("sha256:")
        assert all(el.doc_id == result.doc.doc_id for el in result.elements)

    def test_parse_simple_table_region(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "状态表"
        ws.append(["状态", "说明"])
        ws.append(["处理中", "系统正在解析文档"])
        ws.append(["成功", "文档已进入知识库"])

        result = self.parser.parse(_doc(_xlsx_bytes(wb)))
        table = next(el for el in result.elements if el.element_type == ElementType.table)
        table_data = table.structured_data["table"]

        assert table_data["headers"] == ["状态", "说明"]
        assert table_data["metadata"]["sheet_name"] == "状态表"
        assert table_data["metadata"]["range"] == "A1:B3"
        assert table_data["rows"][0]["cells"][0]["text"] == "处理中"
        assert table_data["rows"][0]["cells"][0]["metadata"]["cell"] == "A2"

    def test_split_multiple_table_regions(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "多表"
        ws["A1"] = "状态"
        ws["B1"] = "说明"
        ws["A2"] = "成功"
        ws["B2"] = "完成"
        ws["D1"] = "角色"
        ws["E1"] = "权限"
        ws["D2"] = "管理员"
        ws["E2"] = "全部"

        result = self.parser.parse(_doc(_xlsx_bytes(wb)))
        tables = [el for el in result.elements if el.element_type == ElementType.table]
        ranges = [table.structured_data["table"]["metadata"]["range"] for table in tables]

        assert ranges == ["A1:B2", "D1:E2"]

    def test_single_cell_region_becomes_paragraph(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "备注"
        ws["C3"] = "只是一条备注"

        result = self.parser.parse(_doc(_xlsx_bytes(wb)))
        paragraphs = [el for el in result.elements if el.element_type == ElementType.paragraph]

        assert len(paragraphs) == 1
        assert paragraphs[0].text == "只是一条备注"
        assert paragraphs[0].metadata["cell"] == "C3"
        assert paragraphs[0].metadata["sheet_name"] == "备注"

    def test_expand_merged_cells(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "合并"
        ws.merge_cells("A1:C1")
        ws["A1"] = "部门"
        ws["A2"] = "研发"
        ws["B2"] = "测试"
        ws["C2"] = "运维"

        result = self.parser.parse(_doc(_xlsx_bytes(wb)))
        table = next(el for el in result.elements if el.element_type == ElementType.table)
        table_data = table.structured_data["table"]

        assert table_data["headers"] == ["部门", "部门", "部门"]
        assert table_data["header_cells"][1]["metadata"]["merged_from"] == "A1"

    def test_formula_cache_and_missing_cache_metadata(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "公式"
        ws["A1"] = "值"
        ws["B1"] = "合计"
        ws["A2"] = 1
        ws["A3"] = 2
        ws["B2"] = "=SUM(A2:A3)"

        cached_result = self.parser.parse(_doc(_inject_formula_cache(_xlsx_bytes(wb), "3")))
        cached_table = next(el for el in cached_result.elements if el.element_type == ElementType.table)
        cached_cell = cached_table.structured_data["table"]["rows"][0]["cells"][1]
        assert cached_cell["text"] == "3"
        assert cached_cell["metadata"]["formula"] == "=SUM(A2:A3)"
        assert cached_cell["metadata"]["formula_value_missing"] is False

        missing_result = self.parser.parse(_doc(_xlsx_bytes(wb)))
        missing_table = next(el for el in missing_result.elements if el.element_type == ElementType.table)
        missing_cell = missing_table.structured_data["table"]["rows"][0]["cells"][1]
        assert missing_cell["text"] == "=SUM(A2:A3)"
        assert missing_cell["metadata"]["formula_value_missing"] is True

    def test_video_and_attachment_links_create_assets(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "链接"
        ws["A1"] = "类型"
        ws["B1"] = "地址"
        ws["A2"] = "视频"
        ws["B2"] = "https://example.com/demo.mp4"
        ws["A3"] = "附件"
        ws["B3"] = "说明书"
        ws["B3"].hyperlink = "https://example.com/manual.pdf"

        result = self.parser.parse(_doc(_xlsx_bytes(wb)))
        table = next(el for el in result.elements if el.element_type == ElementType.table)
        asset_types = {asset.original_uri: asset.asset_type for asset in result.assets}

        assert asset_types["https://example.com/demo.mp4"] == AssetType.video
        assert asset_types["https://example.com/manual.pdf"] == AssetType.attachment
        assert len(table.asset_ids) == 2
        assert all(asset.source_element_id == table.element_id for asset in result.assets)

    def test_read_from_file_uri(self, tmp_path):
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "备注"
        ws["A2"] = "来自文件"
        path = tmp_path / "sample.xlsx"
        path.write_bytes(_xlsx_bytes(wb))

        doc = Document(
            title="File",
            source_type="xlsx",
            source_uri=f"file://{path}",
        )
        result = self.parser.parse(doc)

        assert result.doc.source_hash.startswith("sha256:")
        assert any(el.text == "来自文件" for el in result.elements)

    def test_invalid_workbook_raises_clear_error(self):
        doc = _doc(b"not a workbook")
        with pytest.raises(ValueError, match="XLSX 解析失败"):
            self.parser.parse(doc)
