import json

from app.core.models import AssetType, Document, ElementType
from parsers.markdown_parser import MarkdownParser


SAMPLE_MARKDOWN = """\
# 产品使用手册

## 上传知识文档

用户可以在知识库页面上传文档，支持 Markdown 和 TXT 格式。

上传后系统会显示解析状态：

| 状态 | 说明 |
|------|------|
| 处理中 | 系统正在解析文档 |
| 成功 | 文档已经进入知识库 |
| 失败 | 需要查看失败原因并重新上传 |

### 注意事项

- 单文件不超过 10 MB
- 支持批量上传

界面截图如下：

![上传状态截图](https://example.com/upload-status.png)

详细信息请参考 [API 文档](https://example.com/api-doc.md)。
"""


class TestMarkdownParser:
    def setup_method(self):
        self.parser = MarkdownParser()

    def test_supported_types(self):
        assert self.parser.supports("markdown")
        assert self.parser.supports("md")
        assert self.parser.supports("txt")
        assert not self.parser.supports("pdf")

    def test_parse_headings(self):
        doc = Document(
            title="Test",
            source_type="markdown",
            source_uri="memory://test",
        )
        doc.metadata["raw_content"] = SAMPLE_MARKDOWN
        result = self.parser.parse(doc, doc.metadata["raw_content"])

        titles = [e for e in result.elements if e.element_type == ElementType.title]
        assert len(titles) >= 3  # h1, h2, h3

        # h1 should be first title
        h1_titles = [t for t in titles if t.metadata.get("heading_level") == 1]
        assert len(h1_titles) == 1
        assert h1_titles[0].text == "产品使用手册"

    def test_parse_table(self):
        doc = Document(
            title="Test",
            source_type="markdown",
            source_uri="memory://test",
        )
        doc.metadata["raw_content"] = SAMPLE_MARKDOWN
        result = self.parser.parse(doc, doc.metadata["raw_content"])

        tables = [e for e in result.elements if e.element_type == ElementType.table]
        assert len(tables) >= 1

        table = tables[0]
        assert table.structured_data is not None
        table_data = table.structured_data["table"]
        assert "headers" in table_data
        assert table_data["headers"] == ["状态", "说明"]
        assert len(table_data["rows"]) == 3

    def test_parse_image(self):
        doc = Document(
            title="Test",
            source_type="markdown",
            source_uri="memory://test",
        )
        doc.metadata["raw_content"] = SAMPLE_MARKDOWN
        result = self.parser.parse(doc, doc.metadata["raw_content"])

        # Should have at least one image asset
        assert len(result.assets) >= 1
        image_asset = result.assets[0]
        assert image_asset.asset_type == "image"
        assert "upload-status.png" in image_asset.original_uri

    def test_parse_list(self):
        doc = Document(
            title="Test",
            source_type="markdown",
            source_uri="memory://test",
        )
        doc.metadata["raw_content"] = SAMPLE_MARKDOWN
        result = self.parser.parse(doc, doc.metadata["raw_content"])

        lists = [e for e in result.elements if e.element_type == ElementType.list]
        assert len(lists) >= 1

    def test_all_elements_have_sequence_order(self):
        doc = Document(
            title="Test",
            source_type="markdown",
            source_uri="memory://test",
        )
        doc.metadata["raw_content"] = SAMPLE_MARKDOWN
        result = self.parser.parse(doc, doc.metadata["raw_content"])

        orders = [e.sequence_order for e in result.elements]
        assert all(o > 0 for o in orders)  # all positive
        assert len(set(orders)) == len(orders)  # unique

    def test_document_hash_set(self):
        doc = Document(
            title="Test",
            source_type="markdown",
            source_uri="memory://test",
        )
        doc.metadata["raw_content"] = SAMPLE_MARKDOWN
        result = self.parser.parse(doc, doc.metadata["raw_content"])

        assert result.doc.source_hash
        assert result.doc.source_hash.startswith("sha256:")


class TestBlockquotePreservation:
    """测试 blockquote 引用块语义保留。"""

    BLOCKQUOTE_MD = "> 这是引用的文本\n> 第二行引用内容\n\n普通段落。"

    def setup_method(self):
        self.parser = MarkdownParser()

    def _parse(self, content: str) -> list:
        doc = Document(title="Test", source_type="markdown", source_uri="memory://test")
        doc.metadata["raw_content"] = content
        return self.parser.parse(doc, doc.metadata["raw_content"]).elements

    def test_blockquote_paragraph_marked(self):
        """引用块内段落标记 metadata.blockquote=True。"""
        elements = self._parse(self.BLOCKQUOTE_MD)
        paragraphs = [e for e in elements if e.element_type == ElementType.paragraph]

        # 引用块的段落应包含 blockquote 标记
        quoted = [p for p in paragraphs if p.metadata.get("blockquote") is True]
        assert len(quoted) >= 1
        assert "这是引用的文本" in quoted[0].text

    def test_regular_paragraph_not_marked(self):
        """非引用段落不应有 blockquote 标记。"""
        elements = self._parse(self.BLOCKQUOTE_MD)
        paragraphs = [e for e in elements if e.element_type == ElementType.paragraph]

        regular = [
            p for p in paragraphs
            if p.metadata.get("blockquote") is not True
            and p.text.strip()
        ]
        assert len(regular) >= 1
        assert "普通段落" in regular[0].text

    def test_nested_blockquote(self):
        """嵌套引用块（多层 >）也能正确标记。"""
        md = "> > 嵌套引用内容"
        elements = self._parse(md)
        paragraphs = [e for e in elements if e.element_type == ElementType.paragraph]

        quoted = [p for p in paragraphs if p.metadata.get("blockquote") is True]
        assert len(quoted) >= 1
        assert "嵌套引用内容" in quoted[0].text


class TestLinkUrlExtraction:
    """测试段落内 Markdown 链接 [text](url) 的 URL 提取和分类。"""

    def setup_method(self):
        self.parser = MarkdownParser()

    def _parse(self, content: str):
        doc = Document(title="Test", source_type="markdown", source_uri="memory://test")
        doc.metadata["raw_content"] = content
        return self.parser.parse(doc, doc.metadata["raw_content"])

    def test_attachment_link_creates_asset(self):
        """附件链接 [下载手册](*.pdf) 创建 attachment 类型 Asset。"""
        result = self._parse("请 [下载手册](https://example.com/manual.pdf) 查阅。")
        attachment_assets = [a for a in result.assets if a.asset_type == AssetType.attachment]
        assert len(attachment_assets) >= 1
        assert "manual.pdf" in attachment_assets[0].original_uri

        # 确认对应段落关联了该 Asset
        para = [e for e in result.elements if e.element_type == ElementType.paragraph][0]
        assert attachment_assets[0].asset_id in para.asset_ids

    def test_video_link_creates_asset(self):
        """视频链接 [演示视频](*.mp4) 创建 video 类型 Asset。"""
        result = self._parse("观看 [演示视频](https://example.com/demo.mp4)。")
        video_assets = [a for a in result.assets if a.asset_type == AssetType.video]
        assert len(video_assets) >= 1
        assert "demo.mp4" in video_assets[0].original_uri

    def test_youtube_link_creates_video_asset(self):
        """YouTube 链接创建 video 类型 Asset。"""
        result = self._parse("请看 [教程](https://www.youtube.com/watch?v=abc123)。")
        video_assets = [a for a in result.assets if a.asset_type == AssetType.video]
        assert len(video_assets) >= 1
        assert "youtube.com" in video_assets[0].original_uri

    def test_image_link_creates_asset(self):
        """指向图片的链接 [截图](*.png) 创建 image 类型 Asset。"""
        result = self._parse("查看 [截图](https://example.com/screenshot.png)。")
        image_assets = [a for a in result.assets if a.asset_type == AssetType.image]
        assert len(image_assets) >= 1
        assert "screenshot.png" in image_assets[0].original_uri

    def test_regular_web_link_preserved_in_metadata(self):
        """普通网页链接保留在 metadata.link_urls 中。"""
        result = self._parse("请访问 [Google](https://www.google.com) 搜索。")
        para = [e for e in result.elements if e.element_type == ElementType.paragraph][0]
        assert "link_urls" in para.metadata
        assert "https://www.google.com" in para.metadata["link_urls"]

    def test_mixed_links_same_paragraph(self):
        """同一段落中混合附件和普通链接，分别处理。"""
        result = self._parse(
            "下载 [手册](https://example.com/manual.pdf) "
            "或访问 [官网](https://example.com/about)。"
        )
        para = [e for e in result.elements if e.element_type == ElementType.paragraph][0]

        # 应有一个附件 Asset
        attachment_assets = [a for a in result.assets if a.asset_type == AssetType.attachment]
        assert len(attachment_assets) >= 1

        # 应有普通链接
        assert "link_urls" in para.metadata
        assert "https://example.com/about" in para.metadata["link_urls"]

    def test_link_text_preserved_in_paragraph_text(self):
        """链接文本保留在段落文本中，URL 不出现。"""
        result = self._parse("参考 [API 文档](https://example.com/api-doc.md) 说明。")
        para = [e for e in result.elements if e.element_type == ElementType.paragraph][0]
        assert "API 文档" in para.text
        assert "example.com" not in para.text


class TestTableCellResourceAssociation:
    """测试表格单元格内图片和链接的资源关联。"""

    def setup_method(self):
        self.parser = MarkdownParser()

    def _parse(self, content: str):
        doc = Document(title="Test", source_type="markdown", source_uri="memory://test")
        doc.metadata["raw_content"] = content
        return self.parser.parse(doc, doc.metadata["raw_content"])

    def test_image_in_table_cell_creates_asset(self):
        """表格单元格内的图片创建 Asset 并关联到单元格。"""
        md = """\
| 方案 | 架构图 |
|------|--------|
| A   | ![方案A](https://example.com/a.png) |
| B   | ![方案B](https://example.com/b.png) |
"""
        result = self._parse(md)
        table = [e for e in result.elements if e.element_type == ElementType.table][0]

        image_assets = [a for a in result.assets if a.asset_type == AssetType.image]
        assert len(image_assets) >= 2

        # 单元格 asset_ids 应引用对应图片
        rows = table.structured_data["table"]["rows"]
        assert len(rows) == 2

        cell_a_assets = rows[0]["cells"][1]["asset_ids"]
        cell_b_assets = rows[1]["cells"][1]["asset_ids"]
        assert len(cell_a_assets) == 1
        assert len(cell_b_assets) == 1
        assert "a.png" in image_assets[0].original_uri or "a.png" in image_assets[1].original_uri
        assert "b.png" in image_assets[0].original_uri or "b.png" in image_assets[1].original_uri

    def test_link_in_table_cell_creates_asset(self):
        """表格单元格内的文档链接创建 attachment Asset 并关联到单元格。"""
        md = """\
| 名称 | 说明文档 |
|------|----------|
| 模块1 | [文档](https://example.com/doc1.pdf) |
| 模块2 | [文档](https://example.com/doc2.docx) |
"""
        result = self._parse(md)
        table = [e for e in result.elements if e.element_type == ElementType.table][0]

        attachment_assets = [a for a in result.assets if a.asset_type == AssetType.attachment]
        assert len(attachment_assets) >= 2

        rows = table.structured_data["table"]["rows"]
        for row in rows:
            doc_cell = row["cells"][1]
            assert len(doc_cell["asset_ids"]) == 1

    def test_table_level_asset_ids_aggregation(self):
        """表格级 asset_ids 汇总所有单元格的资源。"""
        md = """\
| 名称 | 图示 |
|------|------|
| A   | ![a](https://example.com/a.png) |
| B   | ![b](https://example.com/b.png) |
"""
        result = self._parse(md)
        table = [e for e in result.elements if e.element_type == ElementType.table][0]

        # 表格级 asset_ids 应包含两个单元格的全部图片
        assert len(table.asset_ids) == 2

    def test_regular_link_in_table_cell_not_asset(self):
        """表格单元格中的普通网页链接不创建 Asset（保留在 metadata 中时不适用，仅段落有此功能）。

        验证普通链接不产生 Asset。
        """
        md = """\
| 名称 | 链接 |
|------|------|
| 参考 | [Google](https://www.google.com) |
"""
        result = self._parse(md)
        # 不应创建 Asset（因为这是普通网页链接）
        non_image_assets = [a for a in result.assets if a.asset_type != AssetType.image]
        assert len(non_image_assets) == 0

    def test_cell_text_preserved_with_image(self):
        """表格单元格中图片旁的文字也被正确保留。"""
        md = """\
| 说明 |
|------|
| 如图 ![架构](https://example.com/arch.png) 所示 |
"""
        result = self._parse(md)
        table = [e for e in result.elements if e.element_type == ElementType.table][0]

        cell_text = table.structured_data["table"]["rows"][0]["cells"][0]["text"]
        assert "如图" in cell_text or "架构" in cell_text
