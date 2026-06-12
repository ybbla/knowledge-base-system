from app.core.models import Asset, AssetStatus, AssetType
from assets.image_processor import process_image
from assets.memory_store import MemoryAssetStore


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_process_image_marks_ready_and_hashes():
    store = MemoryAssetStore()
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
    store = MemoryAssetStore()
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
    store = MemoryAssetStore()
    asset = Asset(
        doc_id="doc_asset_test",
        asset_type=AssetType.image,
        original_uri="bad.txt",
    )
    object.__setattr__(asset, "_data", b"not an image")

    result = process_image(asset, store)

    assert result.status == AssetStatus.failed
    assert result.error_message == "invalid_image_type"
