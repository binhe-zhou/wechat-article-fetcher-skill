"""微信公众号文章获取 MCP Server。

能力：
1. get_article_links   —— Windows 微信客户端 UI 自动化采集公众号文章链接
2. get_article_title   —— 按链接获取文章标题
3. get_article_publish_time —— 按链接获取发布时间
4. get_article_content —— 按链接获取文章正文

通过 MCP 协议（stdio transport）暴露 6 个 tool：
  check_environment / get_article_links / get_article_title /
  get_article_publish_time / get_article_content / get_article

链接采集基于 Windows 微信客户端 4.1.8.101 的 UIA 自动化，
文章解析仅依赖标准库，可在任意平台运行。
"""

__version__ = "1.0.0"
