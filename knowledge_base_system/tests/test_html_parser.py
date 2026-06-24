import pytest

from app.core.models import AssetType, Document, ElementType
from parsers.html_parser import HtmlParser


def _doc(content: str | bytes, source_uri: str = "memory://sample.html") -> Document:
    return Document(
        title="HTML",
        source_type="html",
        source_uri=source_uri,
        metadata={"raw_content": content},
    )


class TestHtmlParser:
    def setup_method(self):
        self.parser = HtmlParser()

    def test_supported_types(self):
        assert self.parser.supports("html")
        assert self.parser.supports("htm")
        assert self.parser.supports("HTML")
        assert self.parser.supports("HTM")
        assert not self.parser.supports("xhtml")

    def test_parse_headings_paragraphs_and_skip_scripts(self):
        html = """
        <html>
          <head>
            <style>.secret { display: none; }</style>
            <script>window.secret = "不应解析";</script>
          </head>
          <body>
            <main>
              <h1>产品手册</h1>
              <p>系统支持上传文档。</p>
              <h2>入库流程</h2>
              <blockquote>上传后会进入解析队列。</blockquote>
            </main>
          </body>
        </html>
        """

        result = self.parser.parse(_doc(html))

        titles = [el for el in result.elements if el.element_type == ElementType.title]
        paragraphs = [el for el in result.elements if el.element_type == ElementType.paragraph]
        assert [title.text for title in titles] == ["产品手册", "入库流程"]
        assert titles[0].metadata["heading_level"] == 1
        assert titles[1].source_location.section_path == ["产品手册", "入库流程"]
        assert [paragraph.text for paragraph in paragraphs] == [
            "系统支持上传文档。",
            "上传后会进入解析队列。",
        ]
        assert "不应解析" not in "\n".join(el.text for el in result.elements)
        assert result.doc.source_hash.startswith("sha256:")

    def test_parse_ordered_and_unordered_lists(self):
        html = """
        <article>
          <h1>列表</h1>
          <ul><li>第一项</li><li>第二项</li></ul>
          <ol><li>步骤一</li><li>步骤二</li></ol>
        </article>
        """

        result = self.parser.parse(_doc(html))

        lists = [el for el in result.elements if el.element_type == ElementType.list]
        children = [el for el in result.elements if el.parent_element_id]
        assert [item.metadata["ordered"] for item in lists] == [False, True]
        assert [child.text for child in children] == ["第一项", "第二项", "步骤一", "步骤二"]
        assert {child.parent_element_id for child in children} == {
            lists[0].element_id,
            lists[1].element_id,
        }

    def test_parse_code_block_with_language(self):
        html = '<pre><code class="language-python">print("hi")</code></pre>'

        result = self.parser.parse(_doc(html))

        code = next(el for el in result.elements if el.element_type == ElementType.code)
        assert code.text == 'print("hi")'
        assert code.metadata["language"] == "python"

    def test_parse_standalone_code_block(self):
        html = '<article><code class="lang-python">print("solo")</code></article>'

        result = self.parser.parse(_doc(html))

        code = next(el for el in result.elements if el.element_type == ElementType.code)
        assert code.text == 'print("solo")'
        assert code.metadata["language"] == "python"

    def test_multiple_articles_without_body_are_all_parsed(self):
        html = """
        <article><h1>First</h1><p>Alpha</p></article>
        <article><h1>Second</h1><p>Beta</p></article>
        """

        result = self.parser.parse(_doc(html))

        texts = [element.text for element in result.elements]
        assert "First" in texts
        assert "Alpha" in texts
        assert "Second" in texts
        assert "Beta" in texts

    def test_parse_table_caption_headers_rows_and_spans(self):
        html = """
        <table>
          <caption>状态说明</caption>
          <thead><tr><th>状态</th><th>说明</th></tr></thead>
          <tbody>
            <tr><td rowspan="2">处理中</td><td>正在解析</td></tr>
            <tr><td colspan="1">等待完成</td></tr>
          </tbody>
        </table>
        """

        result = self.parser.parse(_doc(html))

        table = next(el for el in result.elements if el.element_type == ElementType.table)
        table_data = table.structured_data["table"]
        assert table_data["caption"] == "状态说明"
        assert table_data["headers"] == ["状态", "说明"]
        assert table_data["rows"][0]["cells"][0]["text"] == "处理中"
        assert table_data["rows"][0]["cells"][0]["metadata"]["rowspan"] == 2
        assert table_data["rows"][1]["cells"][0]["metadata"]["colspan"] == 1

    def test_nested_table_does_not_pollute_parent_cell(self):
        html = """
        <table>
          <tr><th>外层</th></tr>
          <tr>
            <td>父单元格<table><tr><th>内层</th></tr><tr><td>内层值</td></tr></table></td>
          </tr>
        </table>
        """

        result = self.parser.parse(_doc(html))

        tables = [el for el in result.elements if el.element_type == ElementType.table]
        assert len(tables) == 2
        parent_cell = tables[0].structured_data["table"]["rows"][0]["cells"][0]
        assert parent_cell["text"] == "父单元格"
        assert "内层值" not in parent_cell["text"]

    def test_images_videos_iframes_and_attachments_create_assets(self):
        html = """
        <article>
          <p>
            图片 <img src="images/a.png" alt="架构图" />
            视频 https://example.com/demo.mp4
            附件 <a href="files/manual.pdf">说明书</a>
          </p>
          <iframe src="https://www.youtube.com/embed/demo"></iframe>
          <embed src="https://example.com/report.pdf" />
          <object data="https://example.com/slides.pptx"></object>
        </article>
        """
        doc = _doc(html, source_uri="https://docs.example.com/manual/page.html")

        result = self.parser.parse(doc, doc.metadata["raw_content"])
        assets = {asset.original_uri: asset for asset in result.assets}

        image = assets["https://docs.example.com/manual/images/a.png"]
        assert image.asset_type == AssetType.image
        assert image.metadata["alt"] == "架构图"
        assert assets["https://example.com/demo.mp4"].asset_type == AssetType.video_link
        assert assets["https://www.youtube.com/embed/demo"].asset_type == AssetType.video_link
        assert assets["https://docs.example.com/manual/files/manual.pdf"].asset_type == AssetType.document_link
        assert assets["https://example.com/report.pdf"].asset_type == AssetType.document_link
        assert assets["https://example.com/slides.pptx"].asset_type == AssetType.document_link
        assert any(el.asset_data for el in result.elements)

    def test_duplicate_urls_create_single_asset(self):
        html = """
        <article>
          <img src="https://example.com/a.png" alt="a" />
          <p><img src="https://example.com/a.png" alt="a" /></p>
        </article>
        """

        result = self.parser.parse(_doc(html))

        assert [asset.original_uri for asset in result.assets] == ["https://example.com/a.png"]

    def test_parse_from_file_uri(self, tmp_path):
        path = tmp_path / "sample.html"
        path.write_bytes("<h1>文件</h1><p>来自文件。</p>".encode("utf-8"))

        doc = Document(title="File", source_type="html", source_uri=f"file://{path}")
        result = self.parser.parse(doc, doc.metadata["raw_content"])

        assert result.doc.source_hash.startswith("sha256:")
        assert any(el.text == "来自文件。" for el in result.elements)

    def test_empty_html_raises_clear_error(self):
        with pytest.raises(ValueError, match="HTML 解析失败"):
            self.parser.parse(_doc(""))

    def test_no_body_and_malformed_html_are_tolerated(self):
        html = "<h1>标题<p>缺失闭合"

        result = self.parser.parse(_doc(html))

        assert any(el.element_type == ElementType.title for el in result.elements)
        assert any(el.text == "缺失闭合" for el in result.elements)
