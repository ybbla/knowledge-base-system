"""图片和视频资源处理器。

负责 Asset 的后续处理流程：文件读取、格式校验、哈希去重、视觉理解和 MinIO 上传。
"""

import hashlib
import logging
from pathlib import Path

from app.core.config import get_settings, settings
from app.core.models import Asset, AssetStatus
from assets.base import AssetStore
from assets.minio_store import MinioAssetStore, make_minio_key, read_uri_bytes

logger = logging.getLogger(__name__)

# 魔数 → MIME 类型映射（用于验证图片文件头）
MAGIC_MIME = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",
    b"BM": "image/bmp",
}


def process_image(
    asset: Asset,
    asset_store: AssetStore,
    minio_store: MinioAssetStore | None = None,
) -> Asset:
    """处理图片 Asset：读取、校验、哈希去重，并按需上传 MinIO。

    处理流程：
    1. 从 asset._data 或 original_uri 读取字节
    2. 通过魔数校验图片 MIME 类型
    3. 计算 SHA-256 哈希，查找已有副本实现去重
    4. 调用视觉理解模型生成图片描述（可选）
    5. 上传 MinIO 并更新 storage_uri

    Args:
        asset: 待处理的图片 Asset。
        asset_store: Asset 元数据存储。
        minio_store: MinIO 对象存储后端（None 时跳过上传）。

    Returns:
        处理后的 Asset（状态为 ready 或 failed）。
    """
    try:
        data = getattr(asset, "_data", None)
        if data is None:
            data = read_uri_bytes(asset.original_uri, minio_store)

        mime_type = sniff_image_mime(data)
        if mime_type is None:
            asset.status = AssetStatus.failed
            asset.error_message = "invalid_image_type"
            asset_store.put(asset)
            return asset

        asset.mime_type = mime_type
        asset.content_hash = f"sha256:{hashlib.sha256(data).hexdigest()}"
        duplicate = find_ready_duplicate(asset_store, asset.content_hash, asset.asset_id)
        if duplicate is not None:
            asset.storage_uri = duplicate.storage_uri
            asset.extracted_text = duplicate.extracted_text
            asset.status = AssetStatus.ready
            asset_store.put(asset)
            return asset

        # 视觉理解：调用多模态模型生成图片内容描述
        cfg = get_settings(reload_env=True)
        if cfg.image_vision_enabled:
            try:
                from llm.volcengine_client import llm_client

                description = llm_client.describe_image(data, mime_type)
                if description:
                    asset.extracted_text = description
                else:
                    logger.warning("图片 %s 视觉理解返回空结果", asset.asset_id)
            except Exception:
                logger.exception("图片 %s 视觉理解失败，继续上传 MinIO", asset.asset_id)
                # 视觉失败不阻塞入库——图片仍然上传

        if minio_store is not None:
            file_name = asset.metadata.get("file_name") or Path(asset.original_uri).name
            key = make_minio_key(asset.doc_id, file_name or f"{asset.asset_id}.bin", asset.asset_id)
            asset.storage_uri = minio_store.upload_bytes(
                minio_store.assets_bucket,
                key,
                data,
                mime_type,
            )
        elif not asset.storage_uri:
            asset.storage_uri = _local_or_external_uri(asset.original_uri)

        asset.status = AssetStatus.ready
        object.__setattr__(asset, "_data", data)
        asset_store.put(asset)
        return asset
    except Exception as exc:
        logger.warning("图片资源处理失败: %s", exc)
        asset.status = AssetStatus.failed
        asset.error_message = str(exc)
        asset_store.put(asset)
        return asset


def process_video(
    asset: Asset,
    asset_store: AssetStore,
) -> Asset:
    """处理视频 Asset：尝试调用多模态模型生成内容总结。

    仅对可获取字节（`_data` 属性非空）的视频调用视觉理解。
    外链视频（无字节）直接跳过，不调用视觉模型。

    Args:
        asset: 待处理的视频 Asset。
        asset_store: Asset 元数据存储。

    Returns:
        处理后的 Asset。
    """
    data = getattr(asset, "_data", None)
    if data is None:
        # 外链视频，无字节可处理
        asset_store.put(asset)
        return asset

    try:
        from llm.volcengine_client import llm_client

        description = llm_client.describe_video(data, asset.mime_type or "video/mp4")
        if description:
            asset.extracted_text = description
        else:
            logger.warning("视频 %s 视觉理解返回空结果", asset.asset_id)
    except Exception:
        logger.exception("视频 %s 视觉理解失败", asset.asset_id)
        # 失败不阻塞——Asset 仍然落存储

    asset_store.put(asset)
    return asset


def sniff_image_mime(data: bytes) -> str | None:
    """通过文件头魔数推断图片的 MIME 类型。

    Args:
        data: 图片文件的原始字节。

    Returns:
        MIME 类型字符串（如 "image/png"），无法识别时返回 None。
    """
    for magic, mime in MAGIC_MIME.items():
        if data.startswith(magic):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime
    return None


def _local_or_external_uri(uri: str) -> str:
    """为本地路径补充 file:// 前缀，已是远程协议的 URI 原样返回。"""
    if uri.startswith(("http://", "https://", "file://", "minio://")):
        return uri
    return f"file:///{Path(uri).resolve().as_posix()}"


def find_ready_duplicate(
    asset_store: AssetStore,
    content_hash: str,
    current_asset_id: str,
) -> Asset | None:
    """在已存储的 Asset 中查找具有相同 content_hash 的 ready 状态副本。

    支持两种存储后端：
    - 内存存储（MemoryAssetStore）：直接遍历内部 dict
    - 数据库存储（PgAssetStore）：通过 session_factory 查询

    Args:
        asset_store: Asset 存储后端。
        content_hash: 待匹配的内容哈希值。
        current_asset_id: 当前 Asset 的 ID（排除自身匹配）。

    Returns:
        匹配的已存在 Asset，未找到时返回 None。
    """
    metadata_store = getattr(asset_store, "_metadata_store", asset_store)
    if hasattr(metadata_store, "_store"):
        for asset in metadata_store._store.values():
            if (
                asset.asset_id != current_asset_id
                and asset.content_hash == content_hash
                and asset.status == AssetStatus.ready
            ):
                return asset

    session_factory = getattr(metadata_store, "_session_factory", None)
    if session_factory is not None:
        try:
            from app.db.models import DbAsset
            from app.db.repositories.assets import PgAssetStore

            with session_factory() as session:
                row = (
                    session.query(DbAsset)
                    .filter_by(content_hash=content_hash, status=AssetStatus.ready.value)
                    .first()
                )
                if row and row.asset_id != current_asset_id:
                    return PgAssetStore(session_factory)._from_db(row)
        except Exception:
            logger.exception("查询重复 Asset 失败")
    return None
