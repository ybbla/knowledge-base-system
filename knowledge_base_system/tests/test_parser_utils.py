"""测试 parsers/utils.py 公共工具模块。"""

import pytest

from app.core.models import Asset, AssetStatus, AssetType
from parsers.utils import (
    ATTACHMENT_EXTENSIONS,
    AssetRecord,
    HTTP_URL_RE,
    MIME_MAP,
    VIDEO_URL_RE,
    guess_mime,
    is_attachment_url,
    is_video_url,
    normalize_text,
)


class TestGuessMime:
    """MIME 类型推断测试。"""

    def test_image_extensions(self):
        """常见图片扩展名返回对应 MIME。"""
        assert guess_mime("image.png", AssetType.image) == "image/png"
        assert guess_mime("photo.jpg", AssetType.image) == "image/jpeg"
        assert guess_mime("photo.jpeg", AssetType.image) == "image/jpeg"
        assert guess_mime("icon.gif", AssetType.image) == "image/gif"
        assert guess_mime("logo.webp", AssetType.image) == "image/webp"
        assert guess_mime("diagram.bmp", AssetType.image) == "image/bmp"
        assert guess_mime("icon.svg", AssetType.image) == "image/svg+xml"
        assert guess_mime("scan.tiff", AssetType.image) == "image/tiff"
        assert guess_mime("scan.tif", AssetType.image) == "image/tiff"

    def test_video_extensions(self):
        """常见视频扩展名返回对应 MIME。"""
        assert guess_mime("demo.mp4", AssetType.video_link) == "video/mp4"
        assert guess_mime("demo.webm", AssetType.video_link) == "video/webm"
        assert guess_mime("demo.mov", AssetType.video_link) == "video/quicktime"
        assert guess_mime("demo.m4v", AssetType.video_link) == "video/mp4"

    def test_audio_extensions(self):
        """常见音频扩展名返回对应 MIME（归入 video_link 处理）。"""
        assert guess_mime("song.mp3", AssetType.video_link) == "audio/mpeg"
        assert guess_mime("sound.wav", AssetType.video_link) == "audio/wav"
        assert guess_mime("audio.m4a", AssetType.video_link) == "audio/mp4"
        assert guess_mime("audio.aac", AssetType.video_link) == "audio/aac"
        assert guess_mime("audio.ogg", AssetType.video_link) == "audio/ogg"
        assert guess_mime("audio.flac", AssetType.video_link) == "audio/flac"

    def test_document_extensions(self):
        """文档/附件扩展名返回对应 MIME。"""
        assert guess_mime("doc.pdf", AssetType.document_link) == "application/pdf"
        assert guess_mime("doc.docx", AssetType.document_link).startswith("application/vnd.openxmlformats-officedocument")
        assert guess_mime("doc.xlsx", AssetType.document_link).startswith("application/vnd.openxmlformats-officedocument")
        assert guess_mime("doc.pptx", AssetType.document_link).startswith("application/vnd.openxmlformats-officedocument")
        assert guess_mime("archive.zip", AssetType.document_link) == "application/zip"

    def test_url_with_query_params(self):
        """URL 带查询参数时正确提取扩展名。"""
        assert guess_mime("https://example.com/image.png?w=100", AssetType.image) == "image/png"

    def test_unknown_extension_fallback(self):
        """未知扩展名按 asset_type 回退到通配 MIME。"""
        assert guess_mime("file.xyz", AssetType.image) == "image/*"
        assert guess_mime("file.xyz", AssetType.image_link) == "image/*"
        assert guess_mime("file.xyz", AssetType.video_link) == "video/*"
        assert guess_mime("file.xyz", AssetType.document_link) == "application/octet-stream"


class TestUrlRegex:
    """URL 正则匹配测试。"""

    def test_video_url_direct_mp4(self):
        """直接 .mp4 链接被识别为视频。"""
        assert VIDEO_URL_RE.search("https://example.com/video.mp4") is not None

    def test_video_url_webm(self):
        """.webm 链接被识别为视频。"""
        assert VIDEO_URL_RE.search("https://example.com/video.webm") is not None

    def test_video_url_youtube(self):
        """YouTube 链接被识别为视频。"""
        assert VIDEO_URL_RE.search("https://www.youtube.com/watch?v=abc123") is not None

    def test_video_url_vimeo(self):
        """Vimeo 链接被识别为视频。"""
        assert VIDEO_URL_RE.search("https://vimeo.com/12345") is not None

    def test_http_url_generic(self):
        """通用 HTTP URL 被识别。"""
        assert HTTP_URL_RE.search("visit https://example.com/page") is not None
        assert HTTP_URL_RE.search("http://example.com") is not None

    def test_is_video_url_helper(self):
        """is_video_url 辅助函数正确判断。"""
        assert is_video_url("https://example.com/demo.mp4") is True
        assert is_video_url("https://example.com/doc.pdf") is False

    def test_is_attachment_url_helper(self):
        """is_attachment_url 辅助函数正确判断。"""
        assert is_attachment_url("https://example.com/doc.pdf") is True
        assert is_attachment_url("https://example.com/doc.docx") is True
        assert is_attachment_url("https://example.com/page") is False


class TestNormalizeText:
    """文本规范化测试。"""

    def test_compress_whitespace(self):
        """连续空白字符归一化为单个空格。"""
        assert normalize_text("hello   world") == "hello world"
        assert normalize_text("hello\nworld") == "hello world"
        assert normalize_text("hello\tworld") == "hello world"
        assert normalize_text("hello\rworld") == "hello world"

    def test_strip_leading_trailing(self):
        """去除首尾空白。"""
        assert normalize_text("  hello  ") == "hello"

    def test_html_entity_decode(self):
        """HTML 实体解码。"""
        assert normalize_text("a&amp;b &lt; c") == "a&b < c"
        assert normalize_text("&quot;hello&quot;") == '"hello"'

    def test_empty_string(self):
        """空字符串返回空字符串。"""
        assert normalize_text("") == ""

    def test_complex_input(self):
        """混合场景：多空白 + HTML 实体。"""
        result = normalize_text("  hello&amp;goodbye\n\t extra  ")
        assert result == "hello&goodbye extra"


class TestAssetRecord:
    """AssetRecord 测试。"""

    def test_creation(self):
        """创建 AssetRecord 并访问字段。"""
        asset = Asset(
            doc_id="d1",
            asset_type=AssetType.image,
            original_uri="https://example.com/img.png",
        )
        record = AssetRecord(asset=asset, key=("image", "sha256:abc123"))
        assert record.asset is asset
        assert record.key == ("image", "sha256:abc123")
