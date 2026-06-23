"""测试 SemanticExtractor._elements_to_json 的 asset_descriptions 注入。

验证具有 extracted_text 的 Asset 信息正确注入到 LLM 窗口 JSON 中。
"""

import json

import pytest

from app.core.models import (
    Asset,
    AssetType,
    ElementType,
    ParsedElement,
    SourceLocation,
)
from llm.semantic_extractor import SemanticExtractor


class TestElementsToJsonAssetDescriptions:
    """_elements_to_json 资产描述注入测试。"""

    def test_element_with_described_asset(self):
        """有 extracted_text 的 Asset 应注入 asset_descriptions。"""
        elements = [
            ParsedElement(
                element_id="el_001",
                doc_id="doc_test",
                element_type=ElementType.image,
                text="[图片: screenshot.png]",
                asset_ids=["asset_001"],
                source_location=SourceLocation(),
            )
        ]
        assets = [
            Asset(
                asset_id="asset_001",
                doc_id="doc_test",
                asset_type=AssetType.image,
                original_uri="screenshot.png",
                extracted_text="图片展示了上传状态列表，包含处理中、成功和失败三种状态。",
            )
        ]

        result_json = SemanticExtractor._elements_to_json(elements, assets)
        result = json.loads(result_json)

        assert "asset_descriptions" in result[0]
        assert len(result[0]["asset_descriptions"]) == 1
        desc = result[0]["asset_descriptions"][0]
        assert desc["asset_id"] == "asset_001"
        assert desc["asset_type"] == "image"
        assert desc["description"] == "图片展示了上传状态列表，包含处理中、成功和失败三种状态。"

    def test_element_with_no_extracted_text(self):
        """extracted_text 为 None 的 Asset 不应注入描述。"""
        elements = [
            ParsedElement(
                element_id="el_001",
                doc_id="doc_test",
                element_type=ElementType.image,
                text="[图片: x.png]",
                asset_ids=["asset_001"],
                source_location=SourceLocation(),
            )
        ]
        assets = [
            Asset(
                asset_id="asset_001",
                doc_id="doc_test",
                asset_type=AssetType.image,
                original_uri="x.png",
                extracted_text=None,
            )
        ]

        result_json = SemanticExtractor._elements_to_json(elements, assets)
        result = json.loads(result_json)

        assert "asset_descriptions" not in result[0]

    def test_multiple_assets_with_descriptions(self):
        """一个元素关联多个有描述的 Asset 时应全部注入。"""
        elements = [
            ParsedElement(
                element_id="el_001",
                doc_id="doc_test",
                element_type=ElementType.paragraph,
                text="请参考以下截图。",
                asset_ids=["asset_001", "asset_002"],
                source_location=SourceLocation(),
            )
        ]
        assets = [
            Asset(
                asset_id="asset_001", doc_id="doc_test",
                asset_type=AssetType.image, original_uri="a.png",
                extracted_text="描述A",
            ),
            Asset(
                asset_id="asset_002", doc_id="doc_test",
                asset_type=AssetType.image, original_uri="b.png",
                extracted_text="描述B",
            ),
        ]

        result_json = SemanticExtractor._elements_to_json(elements, assets)
        result = json.loads(result_json)

        assert len(result[0]["asset_descriptions"]) == 2
        desc_ids = [d["asset_id"] for d in result[0]["asset_descriptions"]]
        assert "asset_001" in desc_ids
        assert "asset_002" in desc_ids

    def test_mixed_assets_some_with_description(self):
        """部分 Asset 有描述、部分没有时，只注入有描述的。"""
        elements = [
            ParsedElement(
                element_id="el_001", doc_id="doc_test",
                element_type=ElementType.paragraph, text="文本",
                asset_ids=["asset_with", "asset_without"],
                source_location=SourceLocation(),
            )
        ]
        assets = [
            Asset(asset_id="asset_with", doc_id="doc_test",
                  asset_type=AssetType.image, original_uri="a.png",
                  extracted_text="有描述"),
            Asset(asset_id="asset_without", doc_id="doc_test",
                  asset_type=AssetType.image, original_uri="b.png",
                  extracted_text=None),
        ]

        result_json = SemanticExtractor._elements_to_json(elements, assets)
        result = json.loads(result_json)

        assert len(result[0]["asset_descriptions"]) == 1
        assert result[0]["asset_descriptions"][0]["asset_id"] == "asset_with"

    def test_no_assets_passed(self):
        """不传 assets 参数时正常序列化，不报错。"""
        elements = [
            ParsedElement(
                element_id="el_001", doc_id="doc_test",
                element_type=ElementType.paragraph, text="普通段落",
                asset_ids=[], source_location=SourceLocation(),
            )
        ]

        result_json = SemanticExtractor._elements_to_json(elements)
        result = json.loads(result_json)

        assert result[0]["element_id"] == "el_001"
        assert "asset_descriptions" not in result[0]

    def test_video_asset_description_injected(self):
        """视频 Asset 有 extracted_text 时也应注入描述。"""
        elements = [
            ParsedElement(
                element_id="el_vid", doc_id="doc_test",
                element_type=ElementType.video, text="[视频]",
                asset_ids=["vid_001"], source_location=SourceLocation(),
            )
        ]
        assets = [
            Asset(asset_id="vid_001", doc_id="doc_test",
                  asset_type=AssetType.video_link, original_uri="demo.mp4",
                  extracted_text="视频演示了上传操作流程。"),
        ]

        result_json = SemanticExtractor._elements_to_json(elements, assets)
        result = json.loads(result_json)

        assert "asset_descriptions" in result[0]
        assert result[0]["asset_descriptions"][0]["asset_type"] == "video_link"
        assert "上传操作流程" in result[0]["asset_descriptions"][0]["description"]