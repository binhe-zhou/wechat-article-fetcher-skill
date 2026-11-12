#!/usr/bin/env python3
"""单链接解析调试 CLI（不经过 MCP，任意平台可运行）。

用法：
  python scripts/fetch_article.py --url https://mp.weixin.qq.com/s/xxxx
  python scripts/fetch_article.py --url <链接> --field title
可选 field：all（默认）/ title / time / content。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server import article_parser  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="解析单篇公众号文章")
    parser.add_argument("--url", required=True, help="mp.weixin.qq.com 文章链接")
    parser.add_argument("--field", default="all", choices=("all", "title", "time", "content"))
    args = parser.parse_args()

    article = article_parser.fetch_article(args.url)
    fields = {
        "all": None,
        "title": ("ok", "url", "title", "error"),
        "time": ("ok", "url", "publish_time", "publish_time_str", "error"),
        "content": ("ok", "url", "plain_content", "error"),
    }
    keys = fields[args.field]
    output = article if keys is None else {key: article[key] for key in keys}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if article["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
