"""MCP Server：微信公众号文章获取。

基于 MCP 协议（stdio transport）暴露 6 个 tool：
  check_environment          环境自检（强制前置）
  get_article_links          按公众号 + 日期区间采集文章链接
  get_article_title          按链接获取标题
  get_article_publish_time   按链接获取发布时间
  get_article_content        按链接获取正文
  get_article                一次返回标题 + 发布时间 + 正文

依赖顺序：get_article_links -> 链接 -> 其余解析类 tool。
所有 tool 统一返回 dict（ok / error / ...），不向协议层抛异常。
"""

from __future__ import annotations

from typing import Any, Callable

try:  # 官方 MCP Python SDK
    from mcp.server.fastmcp import FastMCP
except ImportError:  # 兼容 fastmcp 2.x
    from fastmcp import FastMCP

from . import article_parser, environment, link_collector

mcp = FastMCP("wechat-article-fetcher")


def _safe(handler: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return handler(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 保证 tool 始终返回结构化结果
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@mcp.tool()
def check_environment() -> dict[str, Any]:
    """校验运行环境，必须在采集文章链接前调用。

    检查 Windows 系统、微信客户端版本 4.1.8.101、微信进程与依赖完整性。
    不校验「讲述人」是否开启、UIA 控件树是否可见（仅在 Skill 文档中提示）。
    返回 capabilities 标明各 tool 是否可用。
    """
    return _safe(environment.check)


@mcp.tool()
def get_article_links(
    account_name: str,
    start_date: str,
    end_date: str,
    is_maximize: bool | None = None,
    close_weixin: bool | None = None,
) -> dict[str, Any]:
    """采集指定公众号在日期区间内的文章链接（Windows UIA 自动化）。

    Args:
        account_name: 公众号全称，需与微信搜索结果完全一致，且已在账号类型映射表
            （wechat_runtime.OFFICIAL_ACCOUNT_TYPE_MAP）中登记账号类型。
        start_date: 起始日期，YYYY-MM-DD（含当日）。
        end_date: 结束日期，YYYY-MM-DD（含当日）。
        is_maximize: 是否最大化微信窗口；None 时取 GlobalConfig.is_maximize（默认 False）。
        close_weixin: 任务结束是否关闭微信；None 时取 GlobalConfig.close_weixin（默认 False）。

    Returns:
        ok / account_name / date_range / count / links / error。
        前置条件：Windows + 微信客户端 4.1.8.101 + 已登录。
        讲述人与 UIA 控件树仅作使用提示，不参与校验。
    """
    return _safe(
        link_collector.get_article_links,
        account_name,
        start_date,
        end_date,
        is_maximize=is_maximize,
        close_weixin=close_weixin,
    )


@mcp.tool()
def get_article_title(url: str) -> dict[str, Any]:
    """按公众号文章链接获取文章标题。url 必须来自 get_article_links 或用户提供。"""
    def handler() -> dict[str, Any]:
        article = article_parser.fetch_article(url)
        return {
            "ok": article["ok"],
            "url": article["url"],
            "title": article["title"],
            "error": article["error"],
        }
    return _safe(handler)


@mcp.tool()
def get_article_publish_time(url: str) -> dict[str, Any]:
    """按公众号文章链接获取发布时间（Unix 秒 + UTC+8 可读字符串）。"""
    def handler() -> dict[str, Any]:
        article = article_parser.fetch_article(url)
        return {
            "ok": article["ok"],
            "url": article["url"],
            "publish_time": article["publish_time"],
            "publish_time_str": article["publish_time_str"],
            "error": article["error"],
        }
    return _safe(handler)


@mcp.tool()
def get_article_content(url: str) -> dict[str, Any]:
    """按公众号文章链接获取正文纯文本（js_content 去标签结果）。"""
    def handler() -> dict[str, Any]:
        article = article_parser.fetch_article(url)
        return {
            "ok": article["ok"],
            "url": article["url"],
            "content": article["plain_content"],
            "error": article["error"],
        }
    return _safe(handler)


@mcp.tool()
def get_article(url: str) -> dict[str, Any]:
    """一次获取文章标题 + 发布时间 + 正文，避免重复抓取同一链接。"""
    def handler() -> dict[str, Any]:
        article = article_parser.fetch_article(url)
        return {
            "ok": article["ok"],
            "url": article["url"],
            "title": article["title"],
            "publish_time": article["publish_time"],
            "publish_time_str": article["publish_time_str"],
            "content": article["plain_content"],
            "error": article["error"],
        }
    return _safe(handler)


def main() -> None:
    """以 stdio transport 启动 MCP Server。"""
    mcp.run()


if __name__ == "__main__":
    main()
