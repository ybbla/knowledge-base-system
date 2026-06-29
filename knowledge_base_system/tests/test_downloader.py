"""下载工具函数测试。"""

from unittest.mock import patch

from urllib.error import URLError

import pytest

from assets.downloader import (
    _WECHAT_DRIVE_SHARE_RE,
    _get_corp_token,
    _parse_share_page,
    download_to_bytes,
)


# ── 微信微盘 URL 检测 ────────────────────────────────────────────────

class TestWechatDriveUrlDetection:
    """微信微盘分享链接 URL 检测测试。"""

    def test_normal_share_url(self):
        url = "https://drive.weixin.qq.com/s?k=AG0A3QfYAA0cpMRNmKAf0AkgaEAG4"
        assert _WECHAT_DRIVE_SHARE_RE.match(url) is not None

    def test_http_scheme(self):
        url = "http://drive.weixin.qq.com/s?k=abc123"
        assert _WECHAT_DRIVE_SHARE_RE.match(url) is not None

    def test_non_drive_url(self):
        assert _WECHAT_DRIVE_SHARE_RE.match("https://example.com/s?k=test") is None

    def test_drive_other_path(self):
        assert _WECHAT_DRIVE_SHARE_RE.match("https://drive.weixin.qq.com/disk/index") is None


# ── 分享页解析 ────────────────────────────────────────────────────────

class TestParseSharePage:
    """微盘分享页面解析测试。"""

    def test_real_share_page(self):
        url = "https://drive.weixin.qq.com/s?k=AG0A3QfYAA0cpMRNmKAf0AkgaEAG4"
        data = _parse_share_page(url)
        assert data["object_name"] == "49b3133307731577c49a560126b81f10.mov"
        assert data["file_size"] == 19244007
        assert data["auth_type"] == 1
        assert data["file_id"]

    def test_invalid_page(self):
        with pytest.raises(ValueError):
            _parse_share_page("https://drive.weixin.qq.com/disk/index")


# ── 企业 API token ────────────────────────────────────────────────────

class TestGetCorpToken:
    """_get_corp_token 测试。"""

    def test_no_config_returns_empty(self):
        import assets.downloader as mod
        mod._access_token_cache = {"token": "", "expires_at": 0.0}
        with patch("app.core.config.get_settings") as mock_cfg:
            mock_cfg.return_value.wechat_corpid = ""
            mock_cfg.return_value.wechat_corpsecret = ""
            assert _get_corp_token() == ""

    def test_cache_reuse(self):
        import time as _time
        import assets.downloader as mod
        mod._access_token_cache = {
            "token": "cached_token",
            "expires_at": _time.time() + 3600,
        }
        with patch("app.core.config.get_settings") as mock_cfg:
            assert _get_corp_token() == "cached_token"
            mock_cfg.assert_not_called()


# ── 统一下载入口 ──────────────────────────────────────────────────────

class TestDownloadToBytes:
    """download_to_bytes 函数测试。"""

    def test_empty_url_raises_value_error(self):
        with pytest.raises(ValueError, match="不能为空"):
            download_to_bytes("")

    def test_unsupported_protocol_raises_value_error(self):
        with pytest.raises(ValueError, match="不支持的协议"):
            download_to_bytes("ftp://example.com/file.pdf")

    def test_unreachable_host_raises_urlerror(self):
        with pytest.raises((URLError, OSError)):
            download_to_bytes("https://192.0.2.1/nonexistent", timeout=2)

    def test_wechat_drive_auth_required_uses_browser(self):
        """需要认证、无企业 API 时走浏览器路径。"""
        url = "https://drive.weixin.qq.com/s?k=AG0A3QfYAA0cpMRNmKAf0AkgaEAG4"
        import assets.downloader as mod
        mod._access_token_cache = {"token": "", "expires_at": 0.0}
        with patch("app.core.config.get_settings") as mock_cfg:
            mock_cfg.return_value.wechat_corpid = ""
            mock_cfg.return_value.wechat_corpsecret = ""
            with patch.object(mod, "_browser_download") as mock_browser:
                mock_browser.return_value = b"fake_video_data"
                result = download_to_bytes(url)
                assert result == b"fake_video_data"
                mock_browser.assert_called_once()
