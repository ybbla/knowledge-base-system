"""下载工具函数测试。"""

import json
from unittest.mock import patch

from urllib.error import URLError

import httpx
import pytest

from assets.downloader import (
    _WECHAT_DRIVE_SHARE_RE,
    _call_wechat_file_download_api,
    _get_access_token,
    _js_to_json,
    _load_cookies_from_config,
    _parse_wechat_drive_page,
    download_to_bytes,
)


# ── 微信微盘 JS → JSON 转换测试 ──────────────────────────────────────

class TestJsToJson:
    """_js_to_json 转换函数测试。"""

    def test_boolean_true(self):
        """Boolean(true) 转为 JSON true。"""
        assert '"enabled": true' in _js_to_json('"enabled": Boolean(true)')

    def test_boolean_false(self):
        """Boolean(false) 转为 JSON false。"""
        assert '"enabled": false' in _js_to_json('"enabled": Boolean(false)')

    def test_boolean_empty(self):
        """Boolean() 无参调用转为 JSON false。"""
        assert '"is_valid": false' in _js_to_json('"is_valid": Boolean()')

    def test_number_literal(self):
        """Number(1) 转为 JSON 数字 1。"""
        assert '"type": 2' in _js_to_json('"type": Number(2)')

    def test_number_empty(self):
        """Number() 无参调用转为 JSON 0。"""
        assert '"status": 0' in _js_to_json('"status": Number()')

    def test_hex_escape_x26(self):
        r"""\x26 转为 & 字符。"""
        result = _js_to_json(r'"url": "https://a.com/?a=1\x26b=2"')
        assert '"url": "https://a.com/?a=1&b=2"' in result

    def test_multiple_hex_escapes(self):
        r"""多个 \xHH 转义都正确还原。"""
        result = _js_to_json(r'"url": "a\x26b\x3Dc"')
        assert '"url": "a&b=c"' in result

    def test_trailing_comma_in_object(self):
        """JS 对象末尾逗号被移除。"""
        result = _js_to_json('{"a": 1,\n  }')
        assert '"a": 1' in result
        # 解析为合法 JSON
        import json
        data = json.loads(result)
        assert data == {"a": 1}

    def test_trailing_comma_in_array(self):
        """JS 数组末尾逗号被移除。"""
        result = _js_to_json('{"items": [1, 2, ]}')
        import json
        data = json.loads(result)
        assert data == {"items": [1, 2]}

    def test_full_share_data_parsing(self):
        """模拟的完整微盘分享数据可解析为合法 JSON。"""
        js_text = """{
            "object_name": "test.mov",
            "type": 2,
            "file_size": Number(19244007),
            "auth_type": Number(1),
            "has_login": Boolean(false),
            "is_valid": Boolean(),
            "download_url": "",
            "url": "https://x.com/?a=1\\x26b=2",
        }"""
        result = _js_to_json(js_text)
        import json
        data = json.loads(result)
        assert data["object_name"] == "test.mov"
        assert data["file_size"] == 19244007
        assert data["auth_type"] == 1
        assert data["has_login"] is False
        assert data["is_valid"] is False
        assert data["download_url"] == ""
        assert data["url"] == "https://x.com/?a=1&b=2"


# ── 微信微盘 URL 检测测试 ────────────────────────────────────────────

class TestWechatDriveUrlDetection:
    """微信微盘分享链接 URL 检测测试。"""

    def test_normal_share_url(self):
        """标准微盘分享链接可被识别。"""
        url = "https://drive.weixin.qq.com/s?k=AG0A3QfYAA0cpMRNmKAf0AkgaEAG4"
        assert _WECHAT_DRIVE_SHARE_RE.match(url) is not None

    def test_http_scheme(self):
        """HTTP 协议的微盘链接也可识别。"""
        url = "http://drive.weixin.qq.com/s?k=abc123"
        assert _WECHAT_DRIVE_SHARE_RE.match(url) is not None

    def test_non_drive_url(self):
        """非微盘 URL 不被误识别。"""
        assert _WECHAT_DRIVE_SHARE_RE.match(
            "https://example.com/s?k=test"
        ) is None

    def test_drive_other_path(self):
        """微盘其他路径不被误识别为分享链接。"""
        assert _WECHAT_DRIVE_SHARE_RE.match(
            "https://drive.weixin.qq.com/disk/index"
        ) is None


# ── 微信微盘页面解析测试 ─────────────────────────────────────────────

class TestWechatDrivePageParsing:
    """微盘分享页面解析测试。"""

    def test_real_share_page(self):
        """真实微盘分享页面可成功解析。"""
        url = "https://drive.weixin.qq.com/s?k=AG0A3QfYAA0cpMRNmKAf0AkgaEAG4"
        data = _parse_wechat_drive_page(url)
        assert data["object_name"] == "49b3133307731577c49a560126b81f10.mov"
        assert data["file_size"] == 19244007
        assert data["auth_type"] == 1
        assert data["type"] == 2
        assert "file_id" in data
        assert "buff" in data

    def test_invalid_share_url(self):
        """无效的微盘页面抛出 ValueError。"""
        with pytest.raises(ValueError):
            _parse_wechat_drive_page(
                "https://drive.weixin.qq.com/disk/index"
            )


# ── Cookie 配置加载测试 ───────────────────────────────────────────────

class TestLoadCookiesFromConfig:
    """_load_cookies_from_config 函数测试。"""

    def test_empty_config_returns_empty_dict(self):
        """未配置时返回空字典。"""
        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.wechat_drive_cookies = ""
            assert _load_cookies_from_config() == {}

    def test_valid_json_returns_dict(self):
        """配置了合法 JSON 时返回 Cookie 字典。"""
        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.wechat_drive_cookies = (
                '{"wedrive_sid":"abc123","wedrive_skey":"xyz789"}'
            )
            result = _load_cookies_from_config()
            assert result == {"wedrive_sid": "abc123", "wedrive_skey": "xyz789"}

    def test_invalid_json_returns_empty_dict(self):
        """配置了非法 JSON 时返回空字典（不抛异常）。"""
        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.wechat_drive_cookies = "not-valid-json"
            assert _load_cookies_from_config() == {}

    def test_config_with_access_token(self):
        """access_token 风格的 Cookie 配置也能正确加载。"""
        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.wechat_drive_cookies = (
                '{"access_token":"tok_abc123"}'
            )
            result = _load_cookies_from_config()
            assert result == {"access_token": "tok_abc123"}


# ── access_token 获取与缓存测试 ───────────────────────────────────────

class TestGetAccessToken:
    """_get_access_token 函数测试。"""

    def test_no_config_returns_empty(self):
        """未配置 corpid/corpsecret 时返回空字符串。"""
        import assets.downloader as mod
        mod._access_token_cache = {"token": "", "expires_at": 0.0}

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.wechat_corpid = ""
            mock_settings.return_value.wechat_corpsecret = ""
            assert _get_access_token() == ""

    def test_valid_config_fetches_token(self):
        """配置了 corpid/corpsecret 时尝试获取 token。"""
        import assets.downloader as mod
        mod._access_token_cache = {"token": "", "expires_at": 0.0}

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.wechat_corpid = "test_corpid"
            mock_settings.return_value.wechat_corpsecret = "test_secret"
            with patch.object(mod.httpx.Client, "get") as mock_get:
                from unittest.mock import MagicMock
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.raise_for_status = MagicMock()
                mock_resp.json.return_value = {
                    "errcode": 0,
                    "access_token": "fake_token_123",
                    "expires_in": 7200,
                }
                mock_get.return_value = mock_resp
                result = _get_access_token()
                assert result == "fake_token_123"

    def test_api_error_returns_empty(self):
        """API 返回错误时返回空字符串。"""
        import assets.downloader as mod
        mod._access_token_cache = {"token": "", "expires_at": 0.0}

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.wechat_corpid = "bad_id"
            mock_settings.return_value.wechat_corpsecret = "bad_secret"
            with patch.object(mod.httpx.Client, "get") as mock_get:
                from unittest.mock import MagicMock
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.raise_for_status = MagicMock()
                mock_resp.json.return_value = {
                    "errcode": 40013, "errmsg": "invalid corpid"
                }
                mock_get.return_value = mock_resp
                assert _get_access_token() == ""

    def test_cache_reuse(self):
        """缓存有效时直接返回缓存的 token，不发起 HTTP 请求。"""
        import time
        import assets.downloader as mod

        mod._access_token_cache = {
            "token": "cached_token",
            "expires_at": time.time() + 3600,
        }

        with patch("app.core.config.get_settings") as mock_settings:
            result = _get_access_token()
            assert result == "cached_token"
            mock_settings.assert_not_called()


# ── 企业微信 API 调用测试 ─────────────────────────────────────────────

class TestCallWechatFileDownloadApi:
    """_call_wechat_file_download_api 函数测试。"""

    def test_success_returns_url(self):
        """成功获取下载链接。"""
        import assets.downloader as mod
        from unittest.mock import MagicMock
        with patch.object(mod.httpx.Client, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "errcode": 0,
                "errmsg": "ok",
                "download_url": "https://cdn.example.com/file",
            }
            mock_post.return_value = mock_resp
            result = _call_wechat_file_download_api("file_123", "token_abc", 30)
            assert result == "https://cdn.example.com/file"

    def test_permission_denied_returns_empty(self):
        """无权限时返回空字符串。"""
        import assets.downloader as mod
        from unittest.mock import MagicMock
        with patch.object(mod.httpx.Client, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "errcode": 48002,
                "errmsg": "no download permission",
            }
            mock_post.return_value = mock_resp
            result = _call_wechat_file_download_api("file_123", "token_abc", 30)
            assert result == ""

    def test_network_error_returns_empty(self):
        """网络异常时返回空字符串（不抛异常）。"""
        import assets.downloader as mod
        with patch.object(mod.httpx.Client, "post") as mock_post:
            mock_post.side_effect = Exception("Connection refused")
            result = _call_wechat_file_download_api("file_123", "token_abc", 30)
            assert result == ""


# ── download_to_bytes 基础功能测试 ────────────────────────────────────

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

    def test_wechat_drive_auth_required_raises_permission_error(self):
        """需要认证的微盘链接抛出 PermissionError（浏览器登录也失败时）。"""
        url = "https://drive.weixin.qq.com/s?k=AG0A3QfYAA0cpMRNmKAf0AkgaEAG4"
        # Mock _get_cookies_via_browser 避免实际弹出浏览器
        with patch("assets.downloader._get_cookies_via_browser", return_value={}):
            with pytest.raises(PermissionError, match="需要登录"):
                download_to_bytes(url)

    def test_cookies_passed_to_wechat_drive(self):
        """显式传入 cookies 时不会抛 PermissionError（前提是 cookies 非空）。"""
        url = "https://drive.weixin.qq.com/s?k=AG0A3QfYAA0cpMRNmKAf0AkgaEAG4"
        fake_cookies = {"wedrive_sid": "test_sid", "wedrive_skey": "test_skey"}
        # 有 cookie 时不应再抛 PermissionError（会在后续 API 调用失败抛其他异常）
        with pytest.raises(Exception) as exc_info:
            download_to_bytes(url, cookies=fake_cookies)
        # 不应是 PermissionError
        assert not isinstance(exc_info.value, PermissionError)

    def test_empty_cookies_still_raises_permission_error(self):
        """空 cookies 字典等同于未传，仍抛 PermissionError。"""
        url = "https://drive.weixin.qq.com/s?k=AG0A3QfYAA0cpMRNmKAf0AkgaEAG4"
        with patch("assets.downloader._get_cookies_via_browser", return_value={}):
            with pytest.raises(PermissionError, match="需要登录"):
                download_to_bytes(url, cookies={})
