import base64
import io
import os
import tempfile

import pytest
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches

from app.core.models import AssetType, Document, ElementType
from parsers.pptx_parser import PptxParser


def _pptx_bytes(presentation: Presentation) -> bytes:
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _doc(raw: bytes, source_uri: str = "memory://slides.pptx") -> Document:
    return Document(
        title="PPTX",
        source_type="pptx",
        source_uri=source_uri,
        metadata={"raw_content": raw},
    )


def _blank_slide(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


class TestPptxParser:
    def setup_method(self):
        self.parser = PptxParser()

    def test_supported_types(self):
        assert self.parser.supports("pptx")
        assert self.parser.supports("PPTX")
        assert not self.parser.supports("ppt")

    def test_parse_title_paragraph_list_and_hash(self):
        prs = Presentation()
        slide = _blank_slide(prs)
        title = slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(6), Inches(0.5))
        title.text = "上传流程"
        body = slide.shapes.add_textbox(Inches(0.5), Inches(1.0), Inches(6), Inches(1.5))
        body.text_frame.text = "准备文件"
        item = body.text_frame.add_paragraph()
        item.text = "上传文件"
        item.level = 1

        result = self.parser.parse(_doc(_pptx_bytes(prs)))

        assert result.doc.source_hash.startswith("sha256:")
        assert [el.element_type for el in result.elements] == [
            ElementType.title,
            ElementType.list,
            ElementType.paragraph,
            ElementType.paragraph,
        ]
        assert result.elements[0].text == "上传流程"
        assert result.elements[0].source_location.section_path == ["上传流程"]
        list_el = result.elements[1]
        assert all(el.parent_element_id == list_el.element_id for el in result.elements[2:])
        assert [el.text for el in result.elements[2:]] == ["准备文件", "上传文件"]
        assert result.elements[2].metadata["slide_index"] == 1
        assert result.elements[3].metadata["level"] == 1

    def test_parse_table(self):
        prs = Presentation()
        slide = _blank_slide(prs)
        slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(6), Inches(0.5)).text = "状态表"
        table_shape = slide.shapes.add_table(
            3,
            2,
            Inches(0.5),
            Inches(1.0),
            Inches(6),
            Inches(1.5),
        )
        table = table_shape.table
        table.cell(0, 0).text = "状态"
        table.cell(0, 1).text = "说明"
        table.cell(1, 0).text = "处理中"
        table.cell(1, 1).text = "系统正在解析文档"
        table.cell(2, 0).text = "成功"
        table.cell(2, 1).text = "文档已经进入知识库"

        result = self.parser.parse(_doc(_pptx_bytes(prs)))
        table_el = next(el for el in result.elements if el.element_type == ElementType.table)
        table_data = table_el.structured_data["table"]

        assert table_data["headers"] == ["状态", "说明"]
        assert table_data["rows"][0]["cells"][0]["text"] == "处理中"
        assert table_data["rows"][0]["cells"][0]["metadata"]["row"] == 2
        assert table_data["metadata"]["slide_index"] == 1
        assert table_el.source_location.section_path == ["状态表"]

    def test_extract_image_asset(self):
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )
        image_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            image_file.write(png_bytes)
            image_file.close()
            prs = Presentation()
            slide = _blank_slide(prs)
            slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(6), Inches(0.5)).text = "截图"
            slide.shapes.add_picture(image_file.name, Inches(0.5), Inches(1.0))
            result = self.parser.parse(_doc(_pptx_bytes(prs)))
        finally:
            os.unlink(image_file.name)

        assert len(result.assets) == 1
        assert result.assets[0].asset_type == AssetType.image
        assert result.assets[0].content_hash.startswith("sha256:")
        assert getattr(result.assets[0], "_data") == png_bytes
        image_el = next(el for el in result.elements if el.element_type == ElementType.image)
        assert image_el.asset_ids == [result.assets[0].asset_id]
        assert result.assets[0].source_element_id == image_el.element_id

    def test_video_audio_attachment_links_and_dedup(self):
        prs = Presentation()
        slide = _blank_slide(prs)
        slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(6), Inches(0.5)).text = "链接"
        textbox = slide.shapes.add_textbox(Inches(0.5), Inches(1.0), Inches(6), Inches(1.0))
        textbox.text = (
            "演示视频 https://example.com/demo.mp4 "
            "音频 https://example.com/audio.mp3 "
            "附件 https://example.com/manual.pdf "
            "重复 https://example.com/demo.mp4"
        )

        result = self.parser.parse(_doc(_pptx_bytes(prs)))
        assets = {asset.original_uri: asset for asset in result.assets}

        assert assets["https://example.com/demo.mp4"].asset_type == AssetType.video
        assert assets["https://example.com/audio.mp3"].asset_type == AssetType.audio
        assert assets["https://example.com/manual.pdf"].asset_type == AssetType.attachment
        assert len(result.assets) == 3
        paragraph = next(
            el
            for el in result.elements
            if el.element_type == ElementType.paragraph and "演示视频" in el.text
        )
        assert len(paragraph.asset_ids) == 3
        assert all(asset.source_element_id == paragraph.element_id for asset in result.assets)

    def test_unsupported_chart_becomes_unknown_element(self):
        prs = Presentation()
        slide = _blank_slide(prs)
        slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(6), Inches(0.5)).text = "图表页"
        chart_data = ChartData()
        chart_data.categories = ["一月", "二月"]
        chart_data.add_series("数量", (1, 2))
        slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED,
            Inches(0.5),
            Inches(1.0),
            Inches(6),
            Inches(3),
            chart_data,
        )

        result = self.parser.parse(_doc(_pptx_bytes(prs)))
        unknown = next(el for el in result.elements if el.element_type == ElementType.unknown)

        assert "Unsupported PPTX object" in unknown.text
        assert unknown.metadata["shape_type"] == "CHART"

    def test_blank_slide_gets_fallback_title(self):
        prs = Presentation()
        _blank_slide(prs)

        result = self.parser.parse(_doc(_pptx_bytes(prs)))

        assert len(result.elements) == 1
        assert result.elements[0].element_type == ElementType.title
        assert result.elements[0].text == "幻灯片 1"
        assert result.elements[0].metadata["fallback_title"] is True

    def test_read_from_file_uri(self, tmp_path):
        prs = Presentation()
        slide = _blank_slide(prs)
        slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(6), Inches(0.5)).text = "文件来源"
        path = tmp_path / "sample.pptx"
        path.write_bytes(_pptx_bytes(prs))

        doc = Document(title="File", source_type="pptx", source_uri=f"file://{path}")
        result = self.parser.parse(doc)

        assert result.doc.source_hash.startswith("sha256:")
        assert result.elements[0].text == "文件来源"

    def test_invalid_pptx_raises_clear_error(self):
        with pytest.raises(ValueError, match="PPTX 解析失败"):
            self.parser.parse(_doc(b"not a pptx"))

    def test_empty_presentation_raises_clear_error(self):
        prs = Presentation()
        with pytest.raises(ValueError, match="PPTX 解析失败"):
            self.parser.parse(_doc(_pptx_bytes(prs)))
