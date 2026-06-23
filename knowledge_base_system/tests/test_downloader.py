"""下载工具函数测试。"""

from urllib.error import URLError

import pytest

from assets.downloader import download_to_bytes


class TestDownloadToBytes:
    """download_to_bytes 函数测试。"""

    def test_empty_url_raises_value_error(self):
        """空 URL 抛出 ValueError。"""
        with pytest.raises(ValueError, match="不能为空"):
            download_to_bytes("")

    def test_unsupported_protocol_raises_value_error(self):
        """不支持的协议抛出 ValueError。"""
        with pytest.raises(ValueError, match="不支持的协议"):
            download_to_bytes("ftp://example.com/file.pdf")

    def test_unreachable_host_raises_urlerror(self):
        """不可达的主机抛出 URLError。"""
        with pytest.raises((URLError, OSError)):
            download_to_bytes("https://192.0.2.1/nonexistent", timeout=2)
