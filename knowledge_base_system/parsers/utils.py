"""解析器公共工具模块。

提供所有文档解析器共享的常量、正则和辅助函数，
消除跨解析器的代码重复，统一 MIME 推断、URL 识别、文本规范化和资源去重行为。
"""

import re
from dataclasses import dataclass
from html import unescape
from pathlib import PurePosixPath
from urllib.parse import urlparse

from app.core.models import Asset, AssetType

# ── MIME 映射表 ──────────────────────────────────────────────────────────

# 扩展名 → MIME 类型的权威映射（合并所有解析器中分散的 MIME 表）
MIME_MAP: dict[str, str] = {
    # 图片
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    # 视频
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".m4v": "video/mp4",
    # 音频
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    # 文档/附件
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
}


def guess_mime(url: str, asset_type: AssetType) -> str:
    """根据 URL 后缀和资源类型推断 MIME 类型。

    注意：不建议在 Asset 创建时调用此函数设置 metadata["mime_type"]。
    Asset 的 mime_type 应由 asset_processor 中 sniff_image_mime / sniff_video_mime
    通过文件魔数确定，扩展名推断不可靠且会被覆盖。

    Args:
        url: 资源 URL 或文件路径。
        asset_type: Asset 类型（image / image_link / video_link / document_link）。

    Returns:
        匹配的 MIME 字符串；未识别时按 asset_type 返回通配 MIME。
    """
    suffix = PurePosixPath(url.split("?", 1)[0]).suffix.lower()
    if suffix in MIME_MAP:
        return MIME_MAP[suffix]
    # 回退到类型通配
    if asset_type in (AssetType.image, AssetType.image_link):
        return "image/*"
    if asset_type == AssetType.video_link:
        return "video/*"
    return "application/octet-stream"


# ── URL 识别正则 ────────────────────────────────────────────────────────

# 视频 URL（YouTube / Vimeo / 常见视频扩展名）
VIDEO_URL_RE = re.compile(
    r"https?://[^\s\])<\"']*(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov|\.m4v)[^\s\])<\"']*",
    re.IGNORECASE,
)

# 通用 HTTP(S) URL
HTTP_URL_RE = re.compile(r"https?://[^\s\])<\"']+", re.IGNORECASE)

# 附件文件扩展名（用于识别下载链接）
ATTACHMENT_EXTENSIONS: set[str] = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".csv", ".txt", ".md",
}

# 链接文字后缀 → 资源类型分类（按链接锚文本后缀判断，非 URL）
_LINK_TEXT_IMAGE_EXT: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".tif",
}
_LINK_TEXT_VIDEO_EXT: set[str] = {".mov", ".mp4", ".webm", ".m4v"}
_LINK_TEXT_DOC_EXT: set[str] = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".csv", ".txt", ".md",
}


def is_video_url(url: str) -> bool:
    """判断 URL 是否为视频链接。"""
    return bool(VIDEO_URL_RE.search(url or ""))


def is_attachment_url(url: str) -> bool:
    """判断 URL 是否指向附件文件。"""
    suffix = PurePosixPath(url.split("?", 1)[0]).suffix.lower()
    return suffix in ATTACHMENT_EXTENSIONS if suffix else False


def classify_link_text(text: str) -> AssetType:
    """根据链接文字的后缀名判断资源类型。

    天空.png → image_link
    演示.mp4 → video_link
    手册.pdf → document_link
    百度 → web_link（无识别后缀）

    Args:
        text: 链接锚文本或文件名。

    Returns:
        对应的 AssetType 枚举值。
    """
    suffix = PurePosixPath(text.split("?", 1)[0]).suffix.lower()
    if suffix in _LINK_TEXT_IMAGE_EXT:
        return AssetType.image_link
    if suffix in _LINK_TEXT_VIDEO_EXT:
        return AssetType.video_link
    if suffix in _LINK_TEXT_DOC_EXT:
        return AssetType.document_link
    return AssetType.web_link


# ── 链接分类 ──────────────────────────────────────────────────────────────


def classify_link(url: str) -> str:
    """根据 URL 后缀或域名特征分类链接类型。

    返回类型优先级：image > video（后缀）> video（域名）> audio > document > url。

    Args:
        url: 链接地址。

    Returns:
        链接类型字符串：image / video / audio / document / url。
    """
    url_lower = url.lower().rstrip("/")
    path = urlparse(url_lower).path

    # 图片扩展名
    image_exts = (
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg",
        ".ico", ".tiff", ".tif",
    )
    for ext in image_exts:
        if path.endswith(ext):
            return "image"

    # 视频扩展名
    video_exts = (".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".webm")
    for ext in video_exts:
        if path.endswith(ext):
            return "video"

    # 视频平台域名
    video_domains = ("youtube.com", "youtu.be", "bilibili.com", "vimeo.com")
    for domain in video_domains:
        if domain in url_lower:
            return "video"

    # 音频扩展名
    audio_exts = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
    for ext in audio_exts:
        if path.endswith(ext):
            return "audio"

    # 文档扩展名
    doc_exts = (
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".txt", ".md", ".csv",
    )
    for ext in doc_exts:
        if path.endswith(ext):
            return "document"

    return "url"


# ── 文本规范化 ──────────────────────────────────────────────────────────


def normalize_text(text: str) -> str:
    """将连续空白字符归一化为单个空格，解码 HTML 实体，去除首尾空白。

    Args:
        text: 待规范化的原始文本。

    Returns:
        规范化后的文本。
    """
    if not text:
        return ""
    return re.sub(r"\s+", " ", unescape(text)).strip()


# ── 资源记录 ────────────────────────────────────────────────────────────


@dataclass
class AssetRecord:
    """内部 Asset 记录，包含 Asset 对象及去重用的查询键。

    供解析器在解析过程中缓存已创建的 Asset，
    避免同一文档中重复创建等价 Asset。
    """

    asset: Asset
    key: tuple[str, str]
