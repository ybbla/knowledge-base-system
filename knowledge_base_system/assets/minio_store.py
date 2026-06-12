import io
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.models import Asset
from app.core.paths import resolve_file_uri
from assets.base import AssetStore

logger = logging.getLogger(__name__)


def parse_minio_uri(uri: str) -> tuple[str, str]:
    """解析 minio://bucket/object-key 格式。"""
    parsed = urlparse(uri)
    if parsed.scheme != "minio" or not parsed.netloc or not parsed.path:
        raise ValueError(f"invalid minio uri: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def make_minio_key(doc_id: str, file_name: str, asset_id: str | None = None) -> str:
    """生成按 doc_id 前两位分片的 MinIO object key。"""
    safe_name = Path(file_name or "asset.bin").name
    prefix = doc_id[:2] if len(doc_id) >= 2 else doc_id
    if asset_id:
        return f"{prefix}/{doc_id}/{asset_id}/{safe_name}"
    return f"{prefix}/{doc_id}/{safe_name}"


class MinioAssetStore(AssetStore):
    """MinIO 文件存储 + 委托式 Asset 元数据存储。"""

    def __init__(
        self,
        metadata_store: AssetStore,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool | None = None,
        input_bucket: str | None = None,
        assets_bucket: str | None = None,
        presigned_expiry: int | None = None,
    ) -> None:
        self._metadata_store = metadata_store
        self.endpoint = endpoint or settings.minio_endpoint
        self.access_key = access_key or settings.minio_access_key
        self.secret_key = secret_key or settings.minio_secret_key
        self.secure = settings.minio_secure if secure is None else secure
        self.input_bucket = input_bucket or settings.minio_bucket_input
        self.assets_bucket = assets_bucket or settings.minio_bucket_assets
        self.presigned_expiry = presigned_expiry or settings.minio_presigned_expiry
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from minio import Minio
            except ImportError as exc:
                raise RuntimeError("minio is not installed") from exc
            self._client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        return self._client

    def ensure_buckets(self) -> None:
        for bucket in (self.input_bucket, self.assets_bucket):
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
                logger.info("已创建 MinIO bucket: %s", bucket)

    def put(self, asset: Asset) -> None:
        data = getattr(asset, "_data", None)
        if data is not None and not asset.storage_uri:
            file_name = asset.metadata.get("file_name") or Path(asset.original_uri).name
            key = make_minio_key(asset.doc_id, file_name, asset.asset_id)
            self.upload_bytes(self.assets_bucket, key, data, asset.mime_type)
            asset.storage_uri = f"minio://{self.assets_bucket}/{key}"
        self._metadata_store.put(asset)

    def get(self, asset_id: str) -> Asset | None:
        asset = self._metadata_store.get(asset_id)
        if asset is None:
            return None
        return self.with_presigned_url(asset)

    def delete(self, asset_id: str) -> None:
        asset = self._metadata_store.get(asset_id)
        if asset and asset.storage_uri and asset.storage_uri.startswith("minio://"):
            bucket, key = parse_minio_uri(asset.storage_uri)
            try:
                self.client.remove_object(bucket, key)
            except Exception:
                logger.exception("删除 MinIO 对象失败: %s", asset.storage_uri)
        self._metadata_store.delete(asset_id)

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.ensure_buckets()
        self.client.put_object(
            bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )
        return f"minio://{bucket}/{key}"

    def get_object_bytes(self, uri: str) -> bytes:
        bucket, key = parse_minio_uri(uri)
        response = self.client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def presign_uri(self, uri: str) -> str:
        bucket, key = parse_minio_uri(uri)
        return self.client.presigned_get_object(
            bucket,
            key,
            expires=timedelta(seconds=self.presigned_expiry),
        )

    def with_presigned_url(self, asset: Asset) -> Asset:
        if asset.storage_uri and asset.storage_uri.startswith("minio://"):
            asset = asset.model_copy(deep=True)
            asset.storage_uri = self.presign_uri(asset.storage_uri)
        return asset


def read_uri_bytes(uri: str, minio_store: MinioAssetStore | None = None) -> bytes:
    """读取 file://、minio://、http(s):// 或普通路径指向的字节。"""
    if uri.startswith("minio://"):
        if minio_store is None:
            raise ValueError("读取 minio:// URI 需要 MinioAssetStore")
        return minio_store.get_object_bytes(uri)
    if uri.startswith("file://"):
        return resolve_file_uri(uri).read_bytes()
    if uri.startswith("http://") or uri.startswith("https://"):
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(uri)
            response.raise_for_status()
            return response.content
    return Path(uri).read_bytes()
