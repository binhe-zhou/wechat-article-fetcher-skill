"""公众号文章解析：标题 / 发布时间 / 正文。

通过标准库 urllib 抓取 mp.weixin.qq.com 文章页，从 HTML 中解析
og:title、publish_time 与 js_content 正文；包含 URL 白名单校验、
微信安全验证识别与短时结果缓存（同一链接只请求一次页面）。

本模块不依赖微信客户端，仅要求网络可达 mp.weixin.qq.com，可在任意平台运行。
"""

from __future__ import annotations

import html
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ARTICLE_HOST = "mp.weixin.qq.com"
CST = timezone(timedelta(hours=8))  # 发布时间统一按 UTC+8 展示
CACHE_TTL = 300  # 秒；标题/时间/正文三个工具共用同一次抓取结果

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class ArticleParseError(Exception):
    """文章链接非法或抓取失败。"""


def _normalize_url(url: str) -> str:
    """校验并规范化公众号文章链接，拒绝非微信域名。"""
    if not isinstance(url, str) or not url.strip():
        raise ArticleParseError("文章链接不能为空")
    clean = html.unescape(url.strip())
    parsed = urlparse(clean)
    if parsed.scheme not in ("http", "https") or parsed.hostname != ARTICLE_HOST:
        raise ArticleParseError("仅支持 mp.weixin.qq.com 域名下的公众号文章链接")
    return urlunparse(parsed._replace(scheme="https"))


def _fetch_html(url: str, timeout: float = 20.0, ua: str = DEFAULT_UA, retries: int = 1) -> str:
    """抓取文章页 HTML，使用标准库 urllib 并携带浏览器 User-Agent。"""
    request = urllib.request.Request(
        url, headers={"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9"}
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - 统一转换为可读错误
            last_error = exc
            if attempt < retries:
                time.sleep(1.0)
    raise ArticleParseError(f"抓取文章 HTML 失败：{last_error}")


def parse_title(page: str) -> str:
    """提取标题：og:title -> <title>。"""
    match = re.search(r'<meta property="og:title" content="([^"]+)"', page)
    if match:
        return html.unescape(match.group(1)).strip()
    match = re.search(r"<title[^>]*>(.*?)</title>", page, re.S)
    if match:
        return html.unescape(match.group(1)).strip()
    return ""


def parse_publish_time(page: str) -> int:
    """提取发布时间（Unix 秒）：var ct -> publish_time%22%3A -> "publish_time"。"""
    patterns = (
        r'var\s+ct\s*=\s*["\']?(\d{10})',
        r"publish_time%22%3A(\d{10})",
        r'"publish_time"\s*:\s*(\d{10})',
    )
    for pattern in patterns:
        match = re.search(pattern, page)
        if match:
            return int(match.group(1))
    return 0


def parse_content(page: str) -> str:
    """提取 js_content 正文并转为纯文本。"""
    match = re.search(r'id="js_content"[^>]*>(.*?)(?:<script|</div>)', page, re.S)
    if not match:
        match = re.search(r'id="js_content"[^>]*>(.*)', page, re.S)
    if not match:
        return ""
    body = match.group(1)
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.S)
    body = re.sub(r"<[^>]+>", "\n", body)
    body = html.unescape(body)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return "\n".join(lines)


def _is_captcha(page: str) -> bool:
    return (
        ("环境异常" in page)
        or ("appmsgcaptcha" in page)
        or ("完成验证后即可继续访问" in page)
    )


def _empty_result(url: str) -> dict[str, Any]:
    return {
        "url": url,
        "title": "",
        "publish_time": 0,
        "publish_time_str": "",
        "plain_content": "",
        "ok": False,
        "error": "",
    }


def fetch_article(
    url: str,
    *,
    timeout: float = 20.0,
    ua: str = DEFAULT_UA,
    use_cache: bool = True,
) -> dict[str, Any]:
    """抓取并解析单篇文章，一次请求得到标题 / 发布时间 / 正文。

    返回结构：url, title, publish_time, publish_time_str, plain_content, ok, error。
    """
    result = _empty_result(url if isinstance(url, str) else "")
    try:
        normalized = _normalize_url(url)
    except ArticleParseError as exc:
        result["error"] = str(exc)
        return result

    result["url"] = normalized
    if use_cache:
        cached = _CACHE.get(normalized)
        if cached and time.time() - cached[0] < CACHE_TTL:
            return dict(cached[1])

    try:
        page = _fetch_html(normalized, timeout=timeout, ua=ua)
    except ArticleParseError as exc:
        result["error"] = str(exc)
        return result

    if len(page) < 1000:
        result["error"] = "返回内容过小，可能为链接失效或访问受限"
        return result
    if _is_captcha(page):
        result["error"] = (
            "触发微信安全验证（环境异常/滑块验证码），请在浏览器手动打开链接完成验证后重试"
        )
        return result

    result["title"] = parse_title(page)
    result["publish_time"] = parse_publish_time(page)
    if result["publish_time"]:
        result["publish_time_str"] = datetime.fromtimestamp(
            result["publish_time"], CST
        ).strftime("%Y-%m-%d %H:%M")
    result["plain_content"] = parse_content(page)

    if not result["title"] and not result["plain_content"]:
        result["error"] = "未能解析到标题与正文，可能文章已删除或页面结构变化"
        return result

    result["ok"] = True
    if use_cache:
        _CACHE[normalized] = (time.time(), dict(result))
    return result


def clear_cache() -> None:
    """清空解析结果缓存。"""
    _CACHE.clear()
