from app.core.models import Asset
from assets.base import AssetStore


class MemoryAssetStore(AssetStore):
    """In-memory asset store backed by a dict."""

    def __init__(self) -> None:
        self._store: dict[str, Asset] = {}

    def put(self, asset: Asset) -> None:
        self._store[asset.asset_id] = asset

    def get(self, asset_id: str) -> Asset | None:
        return self._store.get(asset_id)

    def delete(self, asset_id: str) -> None:
        self._store.pop(asset_id, None)
