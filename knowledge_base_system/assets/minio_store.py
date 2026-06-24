"""MinIO 对象存储后端。

实现 AssetStore 接口，将 Asset 的二进制数据上传到 MinIO，元数据委托给内嵌的 metadata_store。
同时提供 URI 解析、预签名 URL 生成和通用字节读取等工具函数。
"""

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
    """解析 minio://bucket/object-key 格式的 URI。

    Args:
        uri: 符合 minio://<bucket>/<key> 格式的 URI 字符串。

    Returns:
        (bucket_name, object_key) 元组。

    Raises:
        ValueError: URI 格式无效时。
    """
    parsed = urlparse(uri)
    if parsed.scheme != "minio" or not parsed.netloc or not parsed.path:
        raise ValueError(f"无效的 minio URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def make_minio_key(doc_id: str, file_name: str, asset_id: str | None = None) -> str:
    """生成按 doc_id 前两位分片的 MinIO object key。

    分片策略避免单目录文件过多，格式：{prefix}/{doc_id}/{asset_id}/{file_name}
    或 {prefix}/{doc_id}/{file_name}（无 asset_id 时）。

    Args:
        doc_id: 文档 ID。
        file_name: 原始文件名。
        asset_id: Asset ID（可选，不传时省略该层级）。

    Returns:
        MinIO object key 字符串。
    """
    safe_name = Path(file_name or "asset.bin").name
    prefix = doc_id[:2] if len(doc_id) >= 2 else doc_id
    if asset_id:
        return f"{prefix}/{doc_id}/{asset_id}/{safe_name}"
    return f"{prefix}/{doc_id}/{safe_name}"


class MinioAssetStore(AssetStore):
    """MinIO 文件存储 + 委托式 Asset 元数据存储。

    将二进制数据存储到 MinIO，Asset 元数据委托给 metadata_store 管理。
    支持自动创建 Bucket、预签名 URL 生成和字节上传/下载。
    """

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
        """懒加载 MinIO 客户端实例。"""
        if self._client is None:
            try:
                from minio import Minio
            except ImportError as exc:
                raise RuntimeError("minio 未安装") from exc
            self._client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        return self._client

    def put(self, asset: Asset) -> None:
        """存储 Asset：上传二进制数据到 MinIO，元数据委托给 metadata_store。"""
        data = getattr(asset, "_data", None)
        if data is not None and not asset.storage_uri:
            file_name = asset.metadata.get("file_name") or Path(asset.original_uri).name
            key = make_minio_key(asset.doc_id, file_name, asset.asset_id)
            self.upload_bytes(self.assets_bucket, key, data, "application/octet-stream")
            asset.storage_uri = f"minio://{self.assets_bucket}/{key}"
        self._metadata_store.put(asset)

    def get(self, asset_id: str) -> Asset | None:
        """获取 Asset 并附上预签名 URL。"""
        asset = self._metadata_store.get(asset_id)
        if asset is None:
            return None
        return self.with_presigned_url(asset)

    def get_by_doc_id(self, doc_id: str) -> list[Asset]:
        """获取指定文档的全部资源元数据，供重入库清理使用。"""
        if not hasattr(self._metadata_store, "get_by_doc_id"):
            return []
        return self._metadata_store.get_by_doc_id(doc_id)

    def delete(self, asset_id: str) -> None:
        """删除 Asset：从 MinIO 移除对象文件，再从元数据存储中删除。"""
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
        """将字节数据上传到 MinIO 指定 Bucket 和 Key。

        Args:
            bucket: 目标 Bucket 名称。
            key: 对象 Key。
            data: 要上传的字节数据。
            content_type: 对象的 Content-Type。

        Returns:
            minio://<bucket>/<key> 格式的存储 URI。
        """
        self.client.put_object(
            bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )
        return f"minio://{bucket}/{key}"

    def get_object_bytes(self, uri: str) -> bytes:
        """从 MinIO 读取指定 URI 的对象字节。

        Args:
            uri: minio://<bucket>/<key> 格式的 URI。

        Returns:
            对象的原始字节数据。
        """
        bucket, key = parse_minio_uri(uri)
        response = self.client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def presign_uri(self, uri: str) -> str:
        """为 minio:// URI 生成带时效的预签名下载 URL。

        Args:
            uri: minio://<bucket>/<key> 格式的 URI。

        Returns:
            带签名的 HTTP(S) URL，有效期为 presigned_expiry 秒。
        """
        bucket, key = parse_minio_uri(uri)
        return self.client.presigned_get_object(
            bucket,
            key,
            expires=timedelta(seconds=self.presigned_expiry),
        )

    def with_presigned_url(self, asset: Asset) -> Asset:
        """返回一个 storage_uri 替换为预签名 URL 的 Asset 深拷贝。"""
        if asset.storage_uri and asset.storage_uri.startswith("minio://"):
            asset = asset.model_copy(deep=True)
            asset.storage_uri = self.presign_uri(asset.storage_uri)
        return asset


def read_uri_bytes(uri: str, minio_store: MinioAssetStore | None = None) -> bytes:
    """读取 file://、minio://、http(s):// 或普通路径指向的字节。

    支持的协议：
    - minio://  → 通过 MinioAssetStore 读取
    - file://   → 通过 resolve_file_uri 解析本地路径读取
    - http(s):// → 通过 httpx 发起 GET 请求读取
    - 纯路径     → 按本地文件读取

    Args:
        uri: 资源 URI。
        minio_store: 读取 minio:// URI 时必需的 MinioAssetStore 实例。

    Returns:
        资源的原始字节数据。

    Raises:
        ValueError: minio:// URI 未提供 minio_store 时。
    """
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
