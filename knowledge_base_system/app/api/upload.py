import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from app.core.paths import UPLOAD_DIR, UPLOAD_URI_PREFIX

router = APIRouter(prefix="/upload", tags=["upload"])

DEFAULT_CATEGORY = "\u901a\u7528"


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str = Form(default=DEFAULT_CATEGORY),
):
    """Store an uploaded file locally and return its ingest source URI."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "upload"
    suffix = Path(original_name).suffix
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    stored_path = UPLOAD_DIR / stored_name

    content = await file.read()
    stored_path.write_bytes(content)

    return {
        "source_uri": f"file://{UPLOAD_URI_PREFIX}/{stored_name}",
        "source_hash": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "file_name": original_name,
        "size": len(content),
        "title": title or Path(original_name).stem,
        "category": category or DEFAULT_CATEGORY,
    }
