"""测试 process_image() 和 process_video() 中的视觉提取行为。

验证视觉成功/失败/禁用等场景下的正确行为。
"""

from unittest.mock import MagicMock, patch

import pytest

from app.core.models import Asset, AssetStatus, AssetType
from assets.base import AssetStore
from assets.image_processor import process_image, process_video


FAKE_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00\x00\x00\x00\x00"
FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42mp41"


class TestProcessImageVision:
    """process_image 视觉提取测试。"""

    @pytest.fixture
    def asset_store(self):
        """内存 AssetStore 用于测试。"""
        store = MagicMock(spec=AssetStore)
        store._metadata_store = store
        store._store = {}
        return store

    @pytest.fixture
    def image_asset(self):
        """创建带字节的图片 Asset。"""
        asset = Asset(
            doc_id="doc_test",
            asset_type=AssetType.image,
            original_uri="test.png",
            mime_type="image/png",
        )
        object.__setattr__(asset, "_data", FAKE_PNG)
        return asset

    def test_vision_extraction_sets_extracted_text(self, image_asset, asset_store):
        """视觉提取成功时应将描述文本写入 Asset.extracted_text。"""
        with patch("assets.image_processor.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(image_vision_enabled=True)
            with patch("llm.volcengine_client.llm_client") as mock_llm:
                mock_llm.describe_image.return_value = "测试图片描述"

                result = process_image(image_asset, asset_store)

                assert result.extracted_text == "测试图片描述"

    def test_vision_disabled_skips_extraction(self, image_asset, asset_store):
        """image_vision_enabled=false 时不调用视觉提取。"""
        with patch("assets.image_processor.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(image_vision_enabled=False)
            with patch("llm.volcengine_client.llm_client") as mock_llm:
                process_image(image_asset, asset_store)

                mock_llm.describe_image.assert_not_called()

    def test_vision_failure_continues_upload(self, image_asset, asset_store):
        """视觉提取失败时图片仍应正常上传 MinIO。"""
        with patch("assets.image_processor.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(image_vision_enabled=True)
            with patch("llm.volcengine_client.llm_client") as mock_llm:
                mock_llm.describe_image.side_effect = Exception("Vision API Error")

                result = process_image(image_asset, asset_store)

                # extracted_text 保持 None
                assert result.extracted_text is None
                # 图片仍然标记为 ready
                assert result.status == AssetStatus.ready

    def test_vision_none_result_keeps_none_text(self, image_asset, asset_store):
        """视觉提取返回 None 时 extracted_text 保持 None。"""
        with patch("assets.image_processor.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(image_vision_enabled=True)
            with patch("llm.volcengine_client.llm_client") as mock_llm:
                mock_llm.describe_image.return_value = None

                result = process_image(image_asset, asset_store)

                assert result.extracted_text is None
                assert result.status == AssetStatus.ready


class TestProcessVideo:
    """process_video 视觉提取测试。"""

    @pytest.fixture
    def asset_store(self):
        return MagicMock(spec=AssetStore)

    @pytest.fixture
    def video_asset(self):
        """创建视频链接 Asset（URL，无 _data，模拟下载后使用）。"""
        return Asset(
            doc_id="doc_test",
            asset_type=AssetType.video_link,
            original_uri="https://example.com/test.mp4",
            mime_type="video/mp4",
        )

    @pytest.fixture
    def external_video_asset(self):
        """创建外链视频 Asset（URL，下载会失败）。"""
        return Asset(
            doc_id="doc_test",
            asset_type=AssetType.video_link,
            original_uri="https://youtube.com/watch?v=test",
            mime_type="video/*",
        )

    def test_process_video_calls_describe(self, video_asset, asset_store):
        """下载成功 + 视觉理解成功。"""
        with (
            patch("assets.image_processor.download_to_bytes", return_value=FAKE_MP4),
            patch("llm.volcengine_client.llm_client") as mock_llm,
        ):
            mock_llm.describe_video.return_value = "视频总结内容"

            result = process_video(video_asset, asset_store)

            assert result.extracted_text == "视频总结内容"
            mock_llm.describe_video.assert_called_once()

    def test_external_video_download_fails_marks_failed(self, external_video_asset, asset_store):
        """外链视频下载失败时标记为 failed，不调用视觉提取。"""
        with patch("llm.volcengine_client.llm_client") as mock_llm:
            with patch("assets.image_processor.download_to_bytes", side_effect=OSError("timeout")):
                result = process_video(external_video_asset, asset_store)

            mock_llm.describe_video.assert_not_called()
            assert result.status.value == "failed"
            assert "download_failed" in result.error_message

    def test_video_vision_failure_does_not_block(self, video_asset, asset_store):
        """视频视觉提取失败不应抛出异常。"""
        with (
            patch("assets.image_processor.download_to_bytes", return_value=FAKE_MP4),
            patch("llm.volcengine_client.llm_client") as mock_llm,
        ):
            mock_llm.describe_video.side_effect = Exception("API Error")

            result = process_video(video_asset, asset_store)

            assert result.extracted_text is None
            asset_store.put.assert_called_once()
