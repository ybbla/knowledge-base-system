import json

from app.core.models import Document, ElementType
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
        result = self.parser.parse(doc)

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
        result = self.parser.parse(doc)

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
        result = self.parser.parse(doc)

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
        result = self.parser.parse(doc)

        lists = [e for e in result.elements if e.element_type == ElementType.list]
        assert len(lists) >= 1

    def test_all_elements_have_sequence_order(self):
        doc = Document(
            title="Test",
            source_type="markdown",
            source_uri="memory://test",
        )
        doc.metadata["raw_content"] = SAMPLE_MARKDOWN
        result = self.parser.parse(doc)

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
        result = self.parser.parse(doc)

        assert result.doc.source_hash
        assert result.doc.source_hash.startswith("sha256:")
