import os

import pytest

from app.core.models import Asset, AssetType
from assets.memory_store import MemoryAssetStore
from assets.minio_store import MinioAssetStore, make_minio_key, parse_minio_uri


def test_minio_uri_helpers():
    assert parse_minio_uri("minio://kb-assets/ab/doc/file.png") == (
        "kb-assets",
        "ab/doc/file.png",
    )
    assert make_minio_key("doc_abcdef", "file.png") == "do/doc_abcdef/file.png"
    assert make_minio_key("doc_abcdef", "file.png", "asset_1") == (
        "do/doc_abcdef/asset_1/file.png"
    )


@pytest.mark.skipif(
    os.getenv("RUN_MINIO_TESTS") != "1",
    reason="需要 Docker MinIO；设置 RUN_MINIO_TESTS=1 后运行",
)
class TestMinioAssetStore:
    def test_put_get_delete_and_presigned_url(self):
        metadata_store = MemoryAssetStore()
        store = MinioAssetStore(metadata_store)
        store.ensure_buckets()

        asset = Asset(
            doc_id="doc_minio_test",
            asset_type=AssetType.image,
            original_uri="image.png",
            mime_type="image/png",
        )
        object.__setattr__(asset, "_data", b"\x89PNG\r\n\x1a\ncontent")
        store.put(asset)

        loaded = store.get(asset.asset_id)
        assert loaded is not None
        assert loaded.storage_uri is not None
        assert loaded.storage_uri.startswith("http")

        store.delete(asset.asset_id)
        assert metadata_store.get(asset.asset_id) is None
