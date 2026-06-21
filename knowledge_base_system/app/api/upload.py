"""旧版上传 API — 已废弃，保留仅为向后兼容。

注意：本模块中的 `save_upload_file()` 和 `_hash_upload()` 函数仍被 v1 上传接口
（app.api.v1.documents）复用，因此不可删除。

旧版上传接口 POST /upload 已废弃，请使用 v1 接口替代：
- 上传并入库：POST /api/v1/documents/upload

旧版接口将在后续大版本中移除。
"""

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, Response, UploadFile

from app.core.config import get_settings
from app.core.deps import document_repo, minio_asset_store
from app.core.models import new_id
from assets.minio_store import make_minio_key

router = APIRouter(prefix="/upload", tags=["upload (deprecated)"])
logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────
DEFAULT_CATEGORY = "通用"
CHUNK_SIZE = 1024 * 1024           # 哈希计算时的分块大小（1 MiB）
MINIO_PART_SIZE = 10 * 1024 * 1024  # MinIO 分片上传的块大小（10 MiB）


@router.post("", deprecated=True)
async def upload_file(
    response: Response,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str = Form(default=DEFAULT_CATEGORY),
):
    """上传文件并返回可入库的 source URI。已废弃：请使用 POST /api/v1/documents/upload。"""
    response.headers["X-Deprecated"] = "Use POST /api/v1/documents/upload"
    logger.warning("已废弃接口 POST /upload 被调用")
    return save_upload_file(file, title=title, category=category)


def save_upload_file(
    file: UploadFile,
    *,
    title: str | None = None,
    category: str = DEFAULT_CATEGORY,
    doc_id: str | None = None,
    check_duplicate: bool = True,
) -> dict:
    """保存上传文件到 MinIO，返回文件元信息。

    此函数同时服务于旧版 /upload 和 v1 /api/v1/documents/upload 两个接口，
    不可删除。

    参数：
        file:            FastAPI 上传文件对象。
        title:           文档标题，为空时从文件名推断。
        category:        文档分类，默认"通用"。
        doc_id:          预分配的文档 ID，为空时自动生成。
        check_duplicate: 是否进行 source_hash 去重检查。

    返回：
        dict 包含 duplicate、source_uri、source_hash、doc_id 等信息。
    """
    cfg = get_settings(reload_env=True)
    original_name = file.filename or "upload"
    source_hash, size = _hash_upload(file)
    resolved_doc_id = doc_id or new_id("doc")

    # ── 去重检查：相同 hash 的文档已存在时直接返回已有文档信息 ──
    if check_duplicate and document_repo is not None:
        existing = document_repo.find_by_hash(source_hash)
        if existing is not None:
            return {
                "duplicate": True,
                "existing_doc_id": existing.doc_id,
                "source_uri": existing.source_uri,
                "source_hash": source_hash,
                "doc_id": resolved_doc_id,
                "file_name": original_name,
                "size": size,
                "title": title or Path(original_name).stem,
                "category": category or DEFAULT_CATEGORY,
            }

    # ── 上传到 MinIO ──
    if not cfg.minio_enabled or minio_asset_store is None:
        raise RuntimeError("MinIO 未启用，文件上传失败")

    key = make_minio_key(resolved_doc_id, original_name)
    minio_asset_store.ensure_buckets()
    file.file.seek(0)
    minio_asset_store.client.put_object(
        cfg.minio_bucket_input,
        key,
        file.file,
        length=size,
        content_type=file.content_type or "application/octet-stream",
        part_size=MINIO_PART_SIZE,
    )
    source_uri = f"minio://{cfg.minio_bucket_input}/{key}"

    return {
        "duplicate": False,
        "source_uri": source_uri,
        "source_hash": source_hash,
        "doc_id": resolved_doc_id,
        "file_name": original_name,
        "size": size,
        "title": title or Path(original_name).stem,
        "category": category or DEFAULT_CATEGORY,
    }


def _hash_upload(file: UploadFile) -> tuple[str, int]:
    """计算上传文件的 SHA-256 哈希值，返回 (hash字符串, 字节大小)。

    此函数同时服务于旧版 /upload 和 v1 /api/v1/documents/upload 两个接口，
    不可删除。
    """
    hasher = hashlib.sha256()
    size = 0
    file.file.seek(0)
    while chunk := file.file.read(CHUNK_SIZE):
        hasher.update(chunk)
        size += len(chunk)
    file.file.seek(0)  # 重置文件指针，供后续上传使用
    return f"sha256:{hasher.hexdigest()}", size
