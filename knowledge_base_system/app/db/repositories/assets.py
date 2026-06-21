"""资源仓储 — Asset 的 PostgreSQL 持久化与查询。"""

import logging

from app.core.models import Asset, AssetStatus, AssetType
from app.db.models import DbAsset
from app.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class PgAssetStore(BaseRepository):
    """资源仓储 — 实现 PostgreSQL 下的 Asset 持久化存储。"""

    def _to_db(self, asset: Asset) -> DbAsset:
        """将领域模型 Asset 转换为 ORM 对象 DbAsset。"""
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
        """将 ORM 对象 DbAsset 还原为领域模型 Asset。"""
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
        """保存资源（已存在则更新，不存在则新建）。"""
        with self._session() as session:
            db_asset = self._to_db(asset)
            session.merge(db_asset)
            session.commit()

    def get(self, asset_id: str) -> Asset | None:
        """按资源 ID 获取单个资源，不存在返回 None。"""
        with self._session() as session:
            db_asset = session.get(DbAsset, asset_id)
            if db_asset is None:
                return None
            return self._from_db(db_asset)

    def get_by_doc_id(self, doc_id: str) -> list[Asset]:
        """按文档 ID 获取关联的所有资源。"""
        with self._session() as session:
            db_assets = session.query(DbAsset).filter_by(doc_id=doc_id).all()
            return [self._from_db(db_asset) for db_asset in db_assets]

    def delete(self, asset_id: str) -> None:
        """按资源 ID 物理删除资源。"""
        with self._session() as session:
            db_asset = session.get(DbAsset, asset_id)
            if db_asset is not None:
                session.delete(db_asset)
                session.commit()
