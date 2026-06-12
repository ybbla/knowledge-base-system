import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from app.core.config import get_settings
from app.core.models import new_id
from app.core.paths import UPLOAD_DIR, UPLOAD_URI_PREFIX
from assets.memory_store import MemoryAssetStore
from assets.minio_store import MinioAssetStore, make_minio_key

router = APIRouter(prefix="/upload", tags=["upload"])
logger = logging.getLogger(__name__)

DEFAULT_CATEGORY = "\u901a\u7528"
CHUNK_SIZE = 1024 * 1024
MINIO_PART_SIZE = 10 * 1024 * 1024


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str = Form(default=DEFAULT_CATEGORY),
):
    """保存上传文件并返回可入库的 source URI。"""
    cfg = get_settings(reload_env=True)
    original_name = file.filename or "upload"
    source_hash, size = _hash_upload(file)
    doc_id = new_id("doc")

    if cfg.minio_enabled:
        try:
            store = MinioAssetStore(MemoryAssetStore())
            key = make_minio_key(doc_id, original_name)
            store.ensure_buckets()
            file.file.seek(0)
            store.client.put_object(
                cfg.minio_bucket_input,
                key,
                file.file,
                length=size,
                content_type=file.content_type or "application/octet-stream",
                part_size=MINIO_PART_SIZE,
            )
            source_uri = f"minio://{cfg.minio_bucket_input}/{key}"
        except Exception:
            logger.exception("MinIO 上传失败，回退到本地磁盘存储")
            source_uri = _write_local_upload(file, original_name)
    else:
        source_uri = _write_local_upload(file, original_name)

    return {
        "source_uri": source_uri,
        "source_hash": source_hash,
        "doc_id": doc_id,
        "file_name": original_name,
        "size": size,
        "title": title or Path(original_name).stem,
        "category": category or DEFAULT_CATEGORY,
    }


def _hash_upload(file: UploadFile) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    file.file.seek(0)
    while chunk := file.file.read(CHUNK_SIZE):
        hasher.update(chunk)
        size += len(chunk)
    file.file.seek(0)
    return f"sha256:{hasher.hexdigest()}", size


def _write_local_upload(file: UploadFile, original_name: str) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    stored_path = UPLOAD_DIR / stored_name

    file.file.seek(0)
    with stored_path.open("wb") as output:
        while chunk := file.file.read(CHUNK_SIZE):
            output.write(chunk)
    file.file.seek(0)
    return f"file://{UPLOAD_URI_PREFIX}/{stored_name}"
