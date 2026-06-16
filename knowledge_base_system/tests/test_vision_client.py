"""测试 LLMClient.describe_image 和 describe_video 方法。

通过 mock Ark SDK 验证视觉理解方法正确构造请求和处理响应，
不依赖真实的 API 调用。
"""

import base64
from unittest.mock import MagicMock, patch

import pytest

from llm.volcengine_client import LLMClient, EmbeddingClient


FAKE_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00\x00\x00\x00\x00"


class TestDescribeImage:
    """describe_image 方法的单元测试。"""

    @pytest.fixture
    def client(self):
        return LLMClient()

    @pytest.fixture
    def mock_ark(self):
        """Mock Ark 客户端，返回模拟的视觉模型响应。"""
        with patch("llm.volcengine_client.Ark") as mock:
            ark_instance = MagicMock()
            ark_instance.chat.completions.create.return_value = MagicMock(
                choices=[
                    MagicMock(message=MagicMock(
                        content="图片展示了用户上传文档后的解析状态列表。"
                    ))
                ]
            )
            mock.return_value = ark_instance
            yield mock

    def test_describe_image_success(self, client, mock_ark):
        """成功调用 describe_image 应返回非空描述文本。"""
        desc = client.describe_image(FAKE_PNG, "image/png")

        assert desc is not None
        assert len(desc) > 0
        assert "图片" in desc

    def test_describe_image_base64_format(self, client, mock_ark):
        """验证 base64 编码方式正确嵌入到请求中。"""
        client.describe_image(FAKE_PNG, "image/png")

        # 提取实际传给 API 的 messages
        call_kwargs = mock_ark.return_value.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        user_content = messages[1]["content"]

        # user_content 应包含 image_url content part
        assert user_content[0]["type"] == "image_url"
        url = user_content[0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        # 验证 base64 可正确解码
        b64_part = url[len("data:image/png;base64,"):]
        decoded = base64.b64decode(b64_part)
        assert decoded == FAKE_PNG

    def test_describe_image_with_url_skips_base64(self, client, mock_ark):
        """传入 image_url 参数时应直接使用 URL，不做 base64 编码。"""
        client.describe_image(FAKE_PNG, "image/png", image_url="https://example.com/img.png")

        call_kwargs = mock_ark.return_value.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        url = messages[1]["content"][0]["image_url"]["url"]
        assert url == "https://example.com/img.png"

    def test_describe_image_failure_returns_none(self, client):
        """API 调用失败时应返回 None，不抛出异常。"""
        with patch("llm.volcengine_client.Ark") as mock:
            ark_instance = MagicMock()
            ark_instance.chat.completions.create.side_effect = Exception("API Error")
            mock.return_value = ark_instance

            desc = client.describe_image(FAKE_PNG, "image/png")
            assert desc is None

    def test_describe_image_empty_response(self, client, mock_ark):
        """模型返回空内容时应返回 None。"""
        mock_ark.return_value.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=None))]
        )

        desc = client.describe_image(FAKE_PNG, "image/png")
        assert desc is None

    def test_describe_image_no_api_key(self, client):
        """未配置 API Key 时返回 None 并记录警告。"""
        with patch("llm.volcengine_client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(api_key="")
            desc = client.describe_image(FAKE_PNG, "image/png")
            assert desc is None


class TestDescribeVideo:
    """describe_video 方法的单元测试。"""

    @pytest.fixture
    def client(self):
        return LLMClient()

    FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42mp41"

    @pytest.fixture
    def mock_ark(self):
        """Mock Ark 客户端，返回模拟的视觉模型响应。"""
        with patch("llm.volcengine_client.Ark") as mock:
            ark_instance = MagicMock()
            ark_instance.chat.completions.create.return_value = MagicMock(
                choices=[
                    MagicMock(message=MagicMock(
                        content="视频展示了用户上传文档的操作流程：1.点击上传按钮 2.选择文件 3.确认上传。"
                    ))
                ]
            )
            mock.return_value = ark_instance
            yield mock

    def test_describe_video_success(self, client, mock_ark):
        """成功调用 describe_video 应返回非空总结文本。"""
        desc = client.describe_video(self.FAKE_MP4, "video/mp4")

        assert desc is not None
        assert len(desc) > 0

    def test_describe_video_includes_fps(self, client, mock_ark):
        """验证 fps 参数传递到 API 请求中。"""
        client.describe_video(self.FAKE_MP4, "video/mp4", fps=1.0)

        call_kwargs = mock_ark.return_value.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        video_url = messages[1]["content"][0]["video_url"]
        assert video_url["fps"] == 1.0

    def test_describe_video_default_fps(self, client, mock_ark):
        """未指定 fps 时使用默认值 0.5。"""
        client.describe_video(self.FAKE_MP4, "video/mp4")

        call_kwargs = mock_ark.return_value.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        video_url = messages[1]["content"][0]["video_url"]
        assert video_url["fps"] == 0.5

    def test_describe_video_failure_returns_none(self, client):
        """API 调用失败时应返回 None。"""
        with patch("llm.volcengine_client.Ark") as mock:
            ark_instance = MagicMock()
            ark_instance.chat.completions.create.side_effect = Exception("Timeout")
            mock.return_value = ark_instance

            desc = client.describe_video(self.FAKE_MP4, "video/mp4")
            assert desc is None

    def test_describe_video_with_url_skips_base64(self, client, mock_ark):
        """传入 video_url 参数时应直接使用 URL。"""
        client.describe_video(
            self.FAKE_MP4, "video/mp4", video_url="https://example.com/video.mp4"
        )

        call_kwargs = mock_ark.return_value.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        url = messages[1]["content"][0]["video_url"]["url"]
        assert url == "https://example.com/video.mp4"