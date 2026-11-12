"""运行环境自检。

链接采集链路校验下列条件，任一不满足即中止并告知用户：
  - Windows 操作系统
  - 本地安装并登录微信客户端 4.1.8.101（版本严格匹配）
  - pywinauto / pywin32 / pyperclip / psutil 可用

版本号从 HKCU\\Software\\Tencent\\Weixin 的 Version 注册表值解析，
实现见 wechat_runtime.read_registry_version()。

自检不覆盖的使用前提：讲述人是否开启、UIA 控件树是否可见、
登录账号是否已订阅目标公众号或服务号。这些条件仅在使用文档中提示，
不进入 issues，也不影响 capabilities.get_article_links。

标题 / 发布时间 / 正文解析仅需网络可达 mp.weixin.qq.com，
因此 capabilities 中这几项恒为 True（数据源仍依赖先拿到文章链接）。

Windows 专属库均在函数内延迟导入，使本模块在 macOS / Linux 上
也可导入并执行自检，返回明确的"平台不支持"结论。
"""

from __future__ import annotations

import importlib.util
import platform
import subprocess
import sys
from typing import Any

from .wechat_runtime import read_registry_version

REQUIRED_WECHAT_VERSION = "4.1.8.101"
WECHAT_PROCESS_NAME = "weixin.exe"

WINDOWS_DEPENDENCIES = ("pywinauto", "win32gui", "pyperclip", "psutil")
MCP_MODULES = ("mcp.server.fastmcp", "fastmcp")


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _process_names() -> list[str]:
    """返回小写进程名列表；psutil 不可用时回退到 tasklist。"""
    try:
        import psutil

        return [
            (p.info.get("name") or "").lower()
            for p in psutil.process_iter(["name"])
        ]
    except Exception:  # noqa: BLE001 - psutil 缺失或非 Windows
        pass
    if platform.system() == "Windows":
        try:
            output = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout
            return [line.split('","')[0].strip('"').lower() for line in output.splitlines()]
        except Exception:  # noqa: BLE001
            return []
    return []


def check() -> dict[str, Any]:
    """执行完整自检，返回结构化 JSON 结果（不含讲述人 / UIA 可见性校验）。"""
    system = platform.system()
    wechat_running = WECHAT_PROCESS_NAME in _process_names()

    # 从注册表读取微信客户端版本；非 Windows 平台不尝试读取
    wechat_version = ""
    if system == "Windows":
        try:
            wechat_version = read_registry_version() or ""
        except Exception:  # noqa: BLE001 - 版本读取失败按"无法确认"处理
            wechat_version = ""

    missing = [name for name in WINDOWS_DEPENDENCIES if not _module_available(name)]
    mcp_available = any(_module_available(name) for name in MCP_MODULES)

    issues: list[str] = []
    if system != "Windows":
        issues.append(f"当前系统为 {system}，链接采集仅支持 Windows")
    if system == "Windows" and not wechat_running:
        issues.append("微信客户端未启动或未登录")
    if system == "Windows" and not wechat_version:
        issues.append(f"无法读取微信客户端版本，请确认已安装 {REQUIRED_WECHAT_VERSION}")
    elif wechat_version and wechat_version != REQUIRED_WECHAT_VERSION:
        issues.append(f"微信客户端版本为 {wechat_version}，本 Skill 仅适配 {REQUIRED_WECHAT_VERSION}")
    if missing:
        issues.append("缺少依赖：" + ", ".join(missing))
    if not mcp_available:
        issues.append("缺少 MCP SDK，请安装 mcp 或 fastmcp")

    link_ready = system == "Windows" and not issues
    return {
        "ok": link_ready,
        "platform": system,
        "python_version": sys.version.split()[0],
        "required_wechat_version": REQUIRED_WECHAT_VERSION,
        "wechat_running": wechat_running,
        "wechat_version": wechat_version,
        "version_match": wechat_version == REQUIRED_WECHAT_VERSION,
        "dependencies": {
            "windows_libs_complete": not missing,
            "missing": missing,
            "mcp_sdk_available": mcp_available,
        },
        "issues": issues,
        "capabilities": {
            "get_article_links": link_ready,
            # 解析链路仅需网络与合法链接，不受 Windows / 微信版本限制
            "get_article_title": True,
            "get_article_publish_time": True,
            "get_article_content": True,
            "get_article": True,
        },
    }
