"""HTTP 下载工具模块。

提供统一的 URL 下载函数，供 image_link、video_link、document_link 等
链接类型资源处理使用。
"""

import logging
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# 默认 HTTP 请求超时时间（秒）
DEFAULT_TIMEOUT = 30


def download_to_bytes(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """从 HTTP/HTTPS URL 下载资源，返回原始字节。

    Args:
        url: 资源 URL。
        timeout: 请求超时时间（秒），默认 30 秒。

    Returns:
        下载的原始字节数据。

    Raises:
        ValueError: URL 为空或协议不支持时。
        URLError: 网络不可达、DNS 解析失败时。
        OSError: 超时时。
    """
    if not url:
        raise ValueError("下载 URL 不能为空")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"不支持的协议: {url}")

    logger.debug("开始下载: %s", url)
    req = Request(url, headers={"User-Agent": "KnowledgeBase/1.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            data = response.read()
            logger.debug("下载完成: %s (%d bytes)", url, len(data))
            return data
    except URLError as exc:
        logger.warning("下载失败: %s (%s)", url, exc)
        raise
