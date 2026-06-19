from app.core.models import Asset, AssetStatus, AssetType
from assets.image_processor import process_image


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class _RecordingAssetStore:
    def __init__(self) -> None:
        self.assets = {}

    def put(self, asset):
        self.assets[asset.asset_id] = asset

    def get(self, asset_id):
        return self.assets.get(asset_id)

    def delete(self, asset_id):
        self.assets.pop(asset_id, None)


def test_process_image_marks_ready_and_hashes():
    store = _RecordingAssetStore()
    asset = Asset(
        doc_id="doc_asset_test",
        asset_type=AssetType.image,
        original_uri="image.png",
    )
    object.__setattr__(asset, "_data", PNG_BYTES)

    result = process_image(asset, store)

    assert result.status == AssetStatus.ready
    assert result.content_hash.startswith("sha256:")
    assert result.mime_type == "image/png"
    assert store.get(asset.asset_id) is not None


def test_process_image_reuses_ready_duplicate():
    store = _RecordingAssetStore()
    first = Asset(
        doc_id="doc_asset_test",
        asset_type=AssetType.image,
        original_uri="image1.png",
        storage_uri="file://image1.png",
    )
    object.__setattr__(first, "_data", PNG_BYTES)
    process_image(first, store)

    second = Asset(
        doc_id="doc_asset_test",
        asset_type=AssetType.image,
        original_uri="image2.png",
    )
    object.__setattr__(second, "_data", PNG_BYTES)
    result = process_image(second, store)

    assert result.status == AssetStatus.ready
    assert result.storage_uri == first.storage_uri


def test_process_image_invalid_type_failed():
    store = _RecordingAssetStore()
    asset = Asset(
        doc_id="doc_asset_test",
        asset_type=AssetType.image,
        original_uri="bad.txt",
    )
    object.__setattr__(asset, "_data", b"not an image")

    result = process_image(asset, store)

    assert result.status == AssetStatus.failed
    assert result.error_message == "invalid_image_type"
