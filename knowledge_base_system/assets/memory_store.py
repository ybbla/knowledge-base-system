"""基于 dict 的内存 Asset 存储实现。

适用于测试和开发场景，数据不持久化。
"""

from app.core.models import Asset
from assets.base import AssetStore


class MemoryAssetStore(AssetStore):
    """基于内存字典的 Asset 存储。

    所有数据保存在内存中，进程重启后丢失。仅用于测试和开发环境。
    """

    def __init__(self) -> None:
        self._store: dict[str, Asset] = {}

    def put(self, asset: Asset) -> None:
        """存储 Asset（按 asset_id 为键）。"""
        self._store[asset.asset_id] = asset

    def get(self, asset_id: str) -> Asset | None:
        """按 ID 获取 Asset，不存在时返回 None。"""
        return self._store.get(asset_id)

    def delete(self, asset_id: str) -> None:
        """删除指定 ID 的 Asset（不存在时不报错）。"""
        self._store.pop(asset_id, None)
