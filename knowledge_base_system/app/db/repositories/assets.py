import logging

from app.core.models import Asset, AssetStatus, AssetType
from app.db.engine import create_session_factory
from app.db.models import DbAsset

logger = logging.getLogger(__name__)


class PgAssetStore:
    """PostgreSQL-backed Asset store matching the AssetStore ABC."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or create_session_factory()

    def _to_db(self, asset: Asset) -> DbAsset:
        return DbAsset(
            asset_id=asset.asset_id,
            doc_id=asset.doc_id,
            source_element_id=asset.source_element_id,
            asset_type=asset.asset_type.value,
            original_uri=asset.original_uri,
            storage_uri=asset.storage_uri,
            mime_type=asset.mime_type,
            content_hash=asset.content_hash,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            status=asset.status.value,
            extracted_text=asset.extracted_text,
            error_message=asset.error_message,
            meta=asset.metadata,
        )

    def _from_db(self, db_asset: DbAsset) -> Asset:
        return Asset(
            asset_id=db_asset.asset_id,
            doc_id=db_asset.doc_id,
            source_element_id=db_asset.source_element_id,
            asset_type=AssetType(db_asset.asset_type),
            original_uri=db_asset.original_uri,
            storage_uri=db_asset.storage_uri,
            mime_type=db_asset.mime_type,
            content_hash=db_asset.content_hash,
            created_at=db_asset.created_at,
            updated_at=db_asset.updated_at,
            status=AssetStatus(db_asset.status),
            extracted_text=db_asset.extracted_text,
            error_message=db_asset.error_message,
            metadata=db_asset.meta or {},
        )

    def put(self, asset: Asset) -> None:
        with self._session_factory() as session:
            db_asset = self._to_db(asset)
            session.merge(db_asset)
            session.commit()

    def get(self, asset_id: str) -> Asset | None:
        with self._session_factory() as session:
            db_asset = session.get(DbAsset, asset_id)
            if db_asset is None:
                return None
            return self._from_db(db_asset)

    def get_by_doc_id(self, doc_id: str) -> list[Asset]:
        with self._session_factory() as session:
            db_assets = session.query(DbAsset).filter_by(doc_id=doc_id).all()
            return [self._from_db(db_asset) for db_asset in db_assets]

    def delete(self, asset_id: str) -> None:
        with self._session_factory() as session:
            db_asset = session.get(DbAsset, asset_id)
            if db_asset is not None:
                session.delete(db_asset)
                session.commit()
