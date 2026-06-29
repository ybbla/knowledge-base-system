"""HTTP 下载工具模块。

提供统一的 URL 下载函数，支持普通 HTTP/HTTPS URL、微信微盘分享链接等，
供 image_link、video_link、document_link 等链接类型资源处理使用。
"""

import json
import logging
import re
from urllib.request import Request, urlopen
from urllib.error import URLError

import httpx

logger = logging.getLogger(__name__)

# 默认 HTTP 请求超时时间（秒）
DEFAULT_TIMEOUT = 30

# 微信微盘分享链接正则（匹配 drive.weixin.qq.com/s?k=xxx）
_WECHAT_DRIVE_SHARE_RE = re.compile(
    r"^https?://drive\.weixin\.qq\.com/s\?k=([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)

# 通用浏览器 UA，用于避免被反爬拦截
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# access_token 缓存（企业微信 API，有效期 7200 秒）
_access_token_cache: dict = {"token": "", "expires_at": 0.0}
_access_token_lock: object = None  # 惰性初始化 threading.Lock


def _get_access_token() -> str:
    """获取企业微信 API 的 access_token（自动缓存与刷新）。

    从 Settings 读取 corpid 和 corpsecret，调用 /cgi-bin/gettoken，
    结果缓存至过期前 5 分钟自动刷新。
    未配置 corpid/corpsecret 时返回空字符串。

    Returns:
        access_token 字符串，不可用时返回 ""。
    """
    global _access_token_cache, _access_token_lock
    import time
    from threading import Lock

    if _access_token_lock is None:
        _access_token_lock = Lock()

    # 缓存未过期直接返回
    if _access_token_cache["token"] and time.time() < _access_token_cache["expires_at"]:
        return _access_token_cache["token"]

    with _access_token_lock:
        # 双重检查：拿到锁后再次确认
        if _access_token_cache["token"] and time.time() < _access_token_cache["expires_at"]:
            return _access_token_cache["token"]

        try:
            from app.core.config import get_settings

            cfg = get_settings()
            corpid = cfg.wechat_corpid
            corpsecret = cfg.wechat_corpsecret
        except Exception:
            logger.debug("读取企业微信配置失败", exc_info=True)
            return ""

        if not corpid or not corpsecret:
            return ""

        token_url = (
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
            f"?corpid={corpid}&corpsecret={corpsecret}"
        )
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(token_url, headers={"User-Agent": _BROWSER_UA})
                resp.raise_for_status()
                result = resp.json()
            if result.get("errcode") == 0:
                token = result["access_token"]
                expires_in = result.get("expires_in", 7200)
                # 提前 5 分钟过期，确保不会用到刚过期的 token
                _access_token_cache = {
                    "token": token,
                    "expires_at": time.time() + expires_in - 300,
                }
                logger.debug(
                    "已获取企业微信 access_token（有效期 %ds）", expires_in
                )
                return token
            else:
                logger.warning(
                    "获取企业微信 access_token 失败: errcode=%s errmsg=%s",
                    result.get("errcode"),
                    result.get("errmsg"),
                )
        except Exception:
            logger.warning("请求企业微信 access_token 网络异常", exc_info=True)

    return ""


# ── 微信微盘 JS 数据解析 ──────────────────────────────────────────────

def _js_to_json(text: str) -> str:
    """将 JS 对象字面量转为合法 JSON。

    处理 JS 特有的语法：
    - Boolean(true)/Boolean(false)/Boolean() → true/false/false
    - Number(n)/Number() → n/0
    - \\xHH 十六进制转义 → 实际 Unicode 字符
    - 末尾多余逗号（JS 容忍，JSON 不允许）
    """
    # Boolean(true) / Boolean(false) / Boolean()
    text = re.sub(r"\bBoolean\(true\)", "true", text)
    text = re.sub(r"\bBoolean\(false\)", "false", text)
    text = re.sub(r"\bBoolean\(\s*\)", "false", text)
    # Number(0) / Number(1) / Number()
    text = re.sub(r"\bNumber\((\d+)\)", r"\1", text)
    text = re.sub(r"\bNumber\(\s*\)", "0", text)
    # \\xHH 十六进制转义 → 实际字符（如 \\x26 → &）
    text = re.sub(
        r"\\x([0-9a-fA-F]{2})",
        lambda m: chr(int(m.group(1), 16)),
        text,
    )
    # 末尾多余逗号（JS 容忍，JSON 不允许）
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _parse_wechat_drive_page(
    url: str, timeout: int = DEFAULT_TIMEOUT
) -> dict:
    """获取并解析微信微盘分享页面，提取文件元数据。

    Args:
        url: 微盘分享链接（drive.weixin.qq.com/s?k=xxx）。
        timeout: 请求超时时间（秒）。

    Returns:
        包含 file_id、object_name、file_size、auth_type 等字段的字典。

    Raises:
        ValueError: 无法从页面中提取到微盘数据时。
        httpx.HTTPError: HTTP 请求失败时。
    """
    logger.debug("获取微信微盘分享页: %s", url)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(
            url,
            headers={
                "User-Agent": _BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        response.raise_for_status()
        html = response.text

    # 提取 xd_global_shareInitDate = {...}（JS 变量声明无分号，以 </script> 收尾）
    match = re.search(
        r'xd_global_shareInitDate\s*=\s*(\{.*?\})\s*</script>',
        html,
        re.DOTALL,
    )
    if not match:
        raise ValueError(
            "无法从页面中解析微信微盘文件信息，"
            "链接可能已失效或页面结构已变更"
        )

    try:
        js_obj = _js_to_json(match.group(1))
        data = json.loads(js_obj)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"解析微信微盘页面数据失败: {exc}"
        ) from exc

    logger.debug(
        "微信微盘文件: name=%s size=%d auth_type=%s",
        data.get("object_name"),
        data.get("file_size", 0),
        data.get("auth_type"),
    )
    return data


# ── 微信微盘下载 ──────────────────────────────────────────────────────

def _load_cookies_from_config() -> dict:
    """从 Settings.wechat_drive_cookies 加载 Cookie 字典。

    wechat_drive_cookies 为 JSON 字符串（如 {"wedrive_sid":"xxx"}），
    在 .env 中通过 WECHAT_DRIVE_COOKIES 配置。

    Returns:
        Cookie 字典，未配置或解析失败时返回空字典。
    """
    try:
        from app.core.config import get_settings

        cfg = get_settings()
        raw = cfg.wechat_drive_cookies
        if raw:
            cookies = json.loads(raw)
            if isinstance(cookies, dict) and cookies:
                logger.debug("已加载微信微盘 Cookie（%d 项）", len(cookies))
                return cookies
    except Exception:
        logger.debug("加载微信微盘 Cookie 配置失败", exc_info=True)
    return {}


def _get_cookies_via_browser(url: str, file_name: str) -> dict:
    """通过 Playwright 持久化浏览器获取微盘登录 Cookie。

    使用持久化浏览器配置文件（~/.kb_wechat_profile/），
    登录态会自动保存。首次使用需手动扫码登录企业微信，
    后续自动复用已保存的登录态。

    Args:
        url: 微盘分享链接。
        file_name: 文件名（用于提示）。

    Returns:
        Cookie 字典，获取失败返回空字典。
    """
    from pathlib import Path

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright 未安装，无法使用浏览器自动登录。"
                       "请运行: pip install playwright && playwright install chromium")
        return {}

    profile_dir = Path.home() / ".kb_wechat_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    logger.info("正在打开浏览器获取微盘登录态（首次需扫码）...")
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                locale="zh-CN",
            )
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=30_000)

            # 检测是否需要登录
            login_btn = page.query_selector('button:has-text("登录查看")')
            if login_btn:
                logger.info(
                    "══════════════════════════════════════════\n"
                    "  请在浏览器窗口中扫码登录企业微信\n"
                    "  文件: %s\n"
                    "  登录完成后系统将自动继续下载\n"
                    "══════════════════════════════════════════",
                    file_name,
                )

            # 等待登录完成：下载按钮出现（最多等待 3 分钟供用户扫码）
            try:
                page.wait_for_selector(
                    'button:has-text("下载"), [class*="download"]',
                    timeout=180_000,
                )
                logger.info("登录成功，正在提取 Cookie...")
            except Exception:
                # 也可能是无需下载按钮的情况（公开分享等）
                logger.debug("未检测到下载按钮，尝试提取 Cookie 继续")

            # 等待页面 JS 执行完毕
            page.wait_for_timeout(2000)

            cookies = context.cookies()
            context.close()

            if cookies:
                result = {c["name"]: c["value"] for c in cookies}
                # 同时持久化到 JSON 文件，供后续快速加载
                cookie_file = profile_dir.parent / ".kb_wechat_cookies.json"
                cookie_file.write_text(json.dumps(result, ensure_ascii=False))
                logger.info("已获取 %d 个 Cookie，已保存至 %s", len(result), cookie_file)
                return result
    except Exception:
        logger.warning("通过浏览器获取 Cookie 失败", exc_info=True)

    return {}


def _load_cookies_from_file() -> dict:
    """从持久化文件加载之前保存的浏览器 Cookie。"""
    from pathlib import Path

    cookie_file = Path.home() / ".kb_wechat_cookies.json"
    try:
        if cookie_file.exists():
            cookies = json.loads(cookie_file.read_text())
            if isinstance(cookies, dict) and cookies:
                logger.debug("已从文件加载 %d 个 Cookie", len(cookies))
                return cookies
    except Exception:
        logger.debug("读取 Cookie 文件失败", exc_info=True)
    return {}


def _download_wechat_drive(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    cookies: dict | None = None,
) -> bytes:
    """从微信微盘分享链接下载文件。

    实现策略：
    1. 解析分享页获取文件元数据（file_id、buff、auth_type 等）。
    2. 若 auth_type != 0（需要登录），检查 cookies。
    3. cookies 来源优先级：传入参数 > WECHAT_DRIVE_COOKIES 配置。
    4. 若 auth_type == 0（公开分享），尝试获取下载链接并下载。

    Args:
        url: 微盘分享链接。
        timeout: 请求超时时间（秒）。
        cookies: 可选，企业微信登录 Cookie 字典（如 {"wedrive_sid": "..."}）。

    Returns:
        下载的原始字节数据。

    Raises:
        ValueError: 解析页面失败或 URL 不合法时。
        PermissionError: 文件需要登录认证且未提供有效 Cookie 时。
        httpx.HTTPError: 网络请求失败时。
    """
    if cookies is None:
        cookies = _load_cookies_from_config()
    # 回退 1：从持久化文件加载浏览器 Cookie
    if not cookies:
        cookies = _load_cookies_from_file()

    share_data = _parse_wechat_drive_page(url, timeout)

    file_id = share_data.get("file_id", "")
    file_name = share_data.get("object_name", "unknown")
    buff = share_data.get("buff", "")
    auth_type = share_data.get("auth_type", 0)
    share_key_match = _WECHAT_DRIVE_SHARE_RE.match(url)
    share_key = share_key_match.group(1) if share_key_match else ""

    # 需要登录的文件：尝试通过浏览器获取 Cookie
    if auth_type != 0 and not cookies:
        corp_name = share_data.get("corp_name", "未知企业")
        # 回退 2：弹出浏览器让用户扫码登录
        cookies = _get_cookies_via_browser(url, file_name)
        if not cookies:
            raise PermissionError(
                f"微信微盘文件「{file_name}」需要登录企业微信 "
                f"（{corp_name}）后才能下载。\n"
                f"请尝试：\n"
                f"  1) 安装 Playwright: pip install playwright && playwright install chromium\n"
                f"  2) 或在 .env 中配置 WECHAT_CORPID / WECHAT_CORPSECRET（企业 API）\n"
                f"  3) 或在 .env 中配置 WECHAT_DRIVE_COOKIES（浏览器 Cookie）"
            )

    # ── 获取下载链接 ──
    # 策略 1：企业微信公开 API（需要 access_token 和 file_id）
    # 策略 2：微盘内部 API（需要登录 Cookie）
    download_url = share_data.get("download_url", "")
    if not download_url and file_id:
        download_url = _fetch_wechat_drive_download_url(
            file_id, share_key, buff, cookies, timeout
        )

    if not download_url:
        raise ValueError(
            f"无法获取微信微盘文件「{file_name}」的下载链接，"
            f"请确认文件未被删除且分享链接有效"
        )

    # ── 下载文件 ──
    logger.debug("开始从微盘下载: %s → %s", file_name, download_url)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        cookies=cookies,
    ) as client:
        dl_response = client.get(
            download_url,
            headers={
                "User-Agent": _BROWSER_UA,
                "Referer": url,
            },
        )
        dl_response.raise_for_status()
        data = dl_response.content

    logger.debug("微盘下载完成: %s (%d bytes)", file_name, len(data))
    return data


def _call_wechat_file_download_api(
    file_id: str,
    access_token: str,
    timeout: int,
) -> str:
    """调用企业微信开放 API 获取微盘文件下载链接。

    Args:
        file_id: 微盘文件 ID。
        access_token: 企业微信 API access_token。
        timeout: 请求超时时间（秒）。

    Returns:
        下载直链 URL，失败返回空字符串。
    """
    token_url = (
        "https://qyapi.weixin.qq.com/cgi-bin/wedrive/"
        f"file_download?access_token={access_token}"
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                token_url,
                json={"fileid": file_id},
                headers={"User-Agent": _BROWSER_UA},
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("errcode") == 0:
                    url = result.get("download_url", "")
                    if url:
                        logger.debug("企业微信 API 返回下载链接")
                        return url
                    else:
                        logger.warning(
                            "企业微信 API 返回空下载链接: %s",
                            result.get("errmsg"),
                        )
                else:
                    logger.warning(
                        "企业微信 file_download API 失败: "
                        "errcode=%s errmsg=%s",
                        result.get("errcode"),
                        result.get("errmsg"),
                    )
    except Exception:
        logger.debug("企业微信开放 API 请求异常", exc_info=True)
    return ""


def _fetch_wechat_drive_download_url(
    file_id: str,
    share_key: str,
    buff: str,
    cookies: dict,
    timeout: int,
) -> str:
    """通过多种策略获取微盘文件下载链接。

    尝试顺序（持久化方案优先）：
    1. 企业微信开放 API — corpid/corpsecret 自动获取 token（长期有效）
    2. 企业微信开放 API — cookies 中手动传入的 access_token
    3. 微盘内部分享 API — 浏览器登录 Cookie

    返回下载直链 URL，获取失败返回空字符串。
    """
    # ── 策略 1：自动 token（持久化方案）──
    auto_token = _get_access_token()
    if auto_token:
        download_url = _call_wechat_file_download_api(
            file_id, auto_token, timeout
        )
        if download_url:
            return download_url

    # ── 策略 2：Cookie 中手动传入的 access_token ──
    manual_token = cookies.get("access_token", "")
    if manual_token and manual_token != auto_token:
        download_url = _call_wechat_file_download_api(
            file_id, manual_token, timeout
        )
        if download_url:
            return download_url

    # ── 策略 3：微盘内部分享 API（需要浏览器登录 Cookie）──
    if share_key and file_id:
        api_url = "https://drive.weixin.qq.com/disk/file/download"
        try:
            with httpx.Client(
                timeout=timeout,
                cookies=cookies,
            ) as client:
                resp = client.post(
                    api_url,
                    json={
                        "file_id": file_id,
                        "share_key": share_key,
                        "buff": buff,
                    },
                    headers={
                        "User-Agent": _BROWSER_UA,
                        "Referer": (
                            "https://drive.weixin.qq.com/"
                            f"s?k={share_key}"
                        ),
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    result = resp.json()
                    url = result.get("download_url", "")
                    if url:
                        return url
        except Exception:
            logger.debug("微盘内部 API 获取下载链接失败", exc_info=True)

    return ""


# ── 统一下载入口 ──────────────────────────────────────────────────────

def download_to_bytes(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    cookies: dict | None = None,
) -> bytes:
    """从 HTTP/HTTPS URL 下载资源，返回原始字节。

    支持普通 URL、微信微盘分享链接（drive.weixin.qq.com/s?k=xxx）等。

    Args:
        url: 资源 URL。
        timeout: 请求超时时间（秒），默认 30 秒。
        cookies: 可选 Cookie 字典，用于需要登录的资源（如微盘认证文件）。

    Returns:
        下载的原始字节数据。

    Raises:
        ValueError: URL 为空、协议不支持或解析失败时。
        PermissionError: 微信微盘文件需要登录认证时。
        URLError: 网络不可达、DNS 解析失败时。
        OSError: 超时时。
    """
    if not url:
        raise ValueError("下载 URL 不能为空")

    # 微信微盘分享链接：走专用下载通道
    if _WECHAT_DRIVE_SHARE_RE.match(url):
        return _download_wechat_drive(url, timeout, cookies=cookies)

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
