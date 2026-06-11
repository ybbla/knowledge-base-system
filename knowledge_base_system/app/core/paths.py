from pathlib import Path
from urllib.parse import unquote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = RUNTIME_DATA_DIR / "uploads"
UPLOAD_URI_PREFIX = "data/uploads"


def resolve_file_uri(uri: str) -> Path:
    """将 file:// URI 解析为稳定的本地路径。"""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"不支持的文件 URI: {uri}")

    if parsed.netloc:
        path = Path(parsed.netloc) / unquote(parsed.path).lstrip("/")
    else:
        path = Path(unquote(parsed.path.lstrip("/")))

    if path.is_absolute():
        return path
    return PROJECT_ROOT / path
