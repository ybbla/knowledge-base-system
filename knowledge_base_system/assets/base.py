from abc import ABC, abstractmethod

from app.core.models import Asset


class AssetStore(ABC):
    """Abstract asset storage interface."""

    @abstractmethod
    def put(self, asset: Asset) -> None: ...

    @abstractmethod
    def get(self, asset_id: str) -> Asset | None: ...

    @abstractmethod
    def delete(self, asset_id: str) -> None: ...
