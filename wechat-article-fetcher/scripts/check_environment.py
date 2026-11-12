#!/usr/bin/env python3
"""离线环境自检 CLI：输出 JSON，供 Skill 或运维在启动 MCP 服务前调用。

用法：python scripts/check_environment.py
退出码：0 = 链接采集环境就绪；1 = 不满足（解析类 tool 仍可用）。
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server import environment  # noqa: E402


def main() -> int:
    result = environment.check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
