"""微信 Windows 客户端 UIA 运行时层。

为文章链接采集提供窗口导航与控件定位能力：
  - GlobalConfig：采集参数、公众号账号类型映射、客户端语言与版本
  - UIElements：按客户端语言提供搜索框、侧栏与窗口按钮的定位字典
  - Tools：进程检测、主窗口句柄查找、窗口置顶状态复位
  - Navigator：连接微信主窗口、搜索并打开公众号主页

仅包含文章链接采集所需的部分。所有 Windows 专属库在函数内延迟导入，
使本模块可在非 Windows 平台导入。
"""

from __future__ import annotations

import random
import re
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# 公众号名称 -> 账号类型映射。
# 作用：search_official_account 用它作为公众号主页窗口的 title。
#      未登记的名称返回 None，主页定位失败。
#      新增公众号时在此登记"公众号"或"服务号"，或调用
#      GlobalConfig.register_official_account(name, account_type)。
# ---------------------------------------------------------------------------
OFFICIAL_ACCOUNT_TYPE_MAP: dict[str, str] = {
    "工银亚洲": "公众号",
    "工銀亞洲": "公众号",
    "中银香港": "公众号",
    "中銀香港": "公众号",
    "中銀香港微銀行": "服务号",
    "汇丰香港": "服务号",
    "渣打香港": "服务号",
    "今日建行": "公众号",
    "农银国际": "公众号",
    "交银国际": "公众号",
    "工银全球金融服务": "公众号",
    "中国建设银行亚洲": "服务号",
    "中國建設銀行亞洲": "服务号",
    "招商永隆银行": "服务号",
    "招商永隆銀行": "服务号",
    "招商永隆微服务": "服务号",
    "信银国际": "服务号",
    "交銀香港": "服务号",
}


def _log(message: str) -> None:
    """把运行日志写入 stderr（MCP stdio 的 stdout 只承载协议报文）。"""
    print(message, file=sys.stderr, flush=True)


def read_registry_version() -> str | None:
    """从 HKCU\\Software\\Tencent\\Weixin 的 Version 值解析出 4.1.x.xx 版本号。"""
    try:
        import winreg

        reg_path = r"Software\Tencent\Weixin"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
            int_version = winreg.QueryValueEx(key, "Version")[0]
            hex_str = hex(int_version)[5:]
            return f"{hex_str[0]}.{hex_str[1]}.{int(hex_str[2], 16)}.{int(hex_str[-2:], 16)}"
    except Exception:  # noqa: BLE001
        return None


class _GlobalConfig:
    """文章链接采集所需的全局配置。"""

    def __init__(self) -> None:
        self.is_maximize = False
        self.close_weixin = False
        self.load_delay = 2.0
        self.window_size = (1000, 1000)
        self._language: str | None = None
        self._version: str | None = None
        self._official_account_type_map = dict(OFFICIAL_ACCOUNT_TYPE_MAP)

    @property
    def language(self) -> str:
        """客户端语言：由 WechatAppex 进程命令行检测，失败回落简体中文。"""
        if self._language is None:
            self._language = self._language_detector() or "简体中文"
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        if value not in {"简体中文", "English", "繁體中文"}:
            raise ValueError("language 必须是 简体中文 / English / 繁體中文")
        self._language = value

    @property
    def Version(self) -> str:
        """微信客户端版本：从注册表读取，读取失败时回落默认版本。"""
        if self._version is None:
            self._version = read_registry_version() or "4.1.9.30"
        return self._version

    @Version.setter
    def Version(self, value: str) -> None:
        self._version = value

    @property
    def official_account_type_map(self) -> dict[str, str]:
        return self._official_account_type_map.copy()

    def get_official_account_type(self, name: str) -> str | None:
        """按公众号名称返回账号类型；未登记的名称返回 None。"""
        return self._official_account_type_map.get(name, None)

    def register_official_account(self, name: str, account_type: str) -> None:
        """登记新的公众号名称与账号类型（"公众号" / "服务号"）。"""
        if account_type not in {"公众号", "服务号"}:
            raise ValueError("account_type 必须是 公众号 或 服务号")
        self._official_account_type_map[name] = account_type

    def _language_detector(self) -> str | None:
        """通过 WechatAppex 进程命令行参数判断客户端语言。"""
        try:
            import psutil
        except ImportError:  # 非 Windows 平台导入保护
            return None
        lang = None
        cmdlines = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            if proc.info["name"] and "wechatappex" in proc.info["name"].lower():
                cmdlines.append(proc.info["cmdline"])
        for cmdline in cmdlines:
            cmd_str = " ".join(cmdline).lower()
            if "--type=renderer" in cmd_str:
                if "--lang=zh-cn" in cmd_str:
                    lang = "简体中文"
                if "--lang=zh-tw" in cmd_str:
                    lang = "繁體中文"
                if "--lang=en" in cmd_str:
                    lang = "English"
        return lang


GlobalConfig = _GlobalConfig()


# ---------------------------------------------------------------------------
# 控件定位常量：open_weixin / search_official_account 使用的 4 组控件
# ---------------------------------------------------------------------------
class UIElements:
    """按 GlobalConfig.language 返回控件定位字典。"""

    _SIDEBAR_WEIXIN = {
        "简体中文": {"title": "微信", "control_type": "Button", "class_name": "mmui::XTabBarItem"},
        "English": {"title": "Weixin", "control_type": "Button", "class_name": "mmui::XTabBarItem"},
        "繁體中文": {"title": "微信", "control_type": "Button", "class_name": "mmui::XTabBarItem"},
    }
    _MAIN_SEARCH = {
        "简体中文": {"title": "搜索", "control_type": "Edit", "class_name": "mmui::XValidatorTextEdit"},
        "English": {"title": "Search", "control_type": "Edit", "class_name": "mmui::XValidatorTextEdit"},
        "繁體中文": {"title": "搜尋", "control_type": "Edit", "class_name": "mmui::XValidatorTextEdit"},
    }
    _CLOSE_BUTTON = {
        "简体中文": {"title": "关闭", "class_name": "ImageButton", "control_type": "Button", "found_index": 0},
        "English": {"title": "Close", "class_name": "ImageButton", "control_type": "Button", "found_index": 0},
        "繁體中文": {"title": "關閉", "class_name": "ImageButton", "control_type": "Button", "found_index": 0},
    }
    _OFFLINE_BUTTON = {
        "简体中文": {"title": "当前网络不可用", "control_type": "Button"},
        "English": {"title": "Network unavailable", "control_type": "Button"},
        "繁體中文": {"title": "目前網路不可用", "control_type": "Button"},
    }
    # 搜索结果列表（不区分语言）
    SEARCH_RESULT = {"title": "", "control_type": "List", "auto_id": "search_list"}

    def __init__(self, language: str) -> None:
        self.SideBarWeixin = self._SIDEBAR_WEIXIN[language]
        self.MainSearch = self._MAIN_SEARCH[language]
        self.CloseButton = self._CLOSE_BUTTON[language]
        self.OffLineButton = self._OFFLINE_BUTTON[language]
        self.SearchResult = self.SEARCH_RESULT


def ui_elements() -> UIElements:
    return UIElements(GlobalConfig.language)


_DESKTOP: Any = None


def desktop() -> Any:
    """返回 Desktop(backend='uia') 单例（懒加载）。"""
    global _DESKTOP
    if _DESKTOP is None:
        from pywinauto import Desktop

        _DESKTOP = Desktop(backend="uia")
    return _DESKTOP


# ---------------------------------------------------------------------------
# 采集链路异常类型
# ---------------------------------------------------------------------------
class NotStartError(Exception):
    def __init__(self, error="微信未启动,请先启动并登录微信后再使用pyweixin!"):
        super().__init__(error)


class NotLoginError(Exception):
    def __init__(self, error="微信未登录,请先点击登录后再使用pyweixin!"):
        super().__init__(error)


class NotFoundError(Exception):
    def __init__(self, error="无法识别定位到微信主界面,UI树不可见,暂无解决办法..."):
        super().__init__(error)


class NetWorkError(Exception):
    def __init__(self, error="当前网络不可用,无法进行UI自动化!"):
        super().__init__(error)


class NoResultsError(Exception):
    def __init__(self, error):
        super().__init__(error)


# ---------------------------------------------------------------------------
# 窗口与进程工具
# ---------------------------------------------------------------------------
class Tools:
    @staticmethod
    def is_weixin_running() -> bool:
        """检测 weixin.exe 进程是否运行。"""
        import psutil

        for process in psutil.process_iter(["name"]):
            if process.info["name"].lower() == "weixin.exe":
                return True
        return False

    @staticmethod
    def get_weixin_hwnd() -> int:
        """获取微信主窗口句柄。

        枚举 win32 层面的 Qt 通用窗口（Qt51514QWindowIcon），再用 UIA 类名
        mmui::.*Window 过滤出主窗口 / 登录窗口，返回首个句柄；找不到返回 0。
        """
        import win32gui

        pattern = re.compile(r"mmui::.*Window")

        def callback(hwnd, _):
            class_name = win32gui.GetClassName(hwnd)
            if class_name == "Qt51514QWindowIcon":
                hwnds.append(hwnd)

        hwnds: list[int] = []
        win32gui.EnumWindows(callback, None)
        hwnds = [hwnd for hwnd in hwnds if pattern.match(desktop().window(handle=hwnd).class_name())]
        if not hwnds:
            return 0
        return hwnds[0]

    @staticmethod
    def cancel_pin(main_window: Any) -> None:
        """取消主窗口置顶状态。"""
        import win32con
        import win32gui

        win32gui.SetWindowPos(
            main_window.handle,
            win32con.HWND_NOTOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
        )


# ---------------------------------------------------------------------------
# 窗口导航
# ---------------------------------------------------------------------------
class Navigator:
    @staticmethod
    def open_weixin(is_maximize: bool = None, window_size: tuple = None) -> Any:
        """连接已登录的微信主窗口并完成窗口布局准备。"""
        import win32api
        import win32con
        import win32gui

        if is_maximize is None:
            is_maximize = GlobalConfig.is_maximize
        if window_size is None:
            window_size = GlobalConfig.window_size
        if not Tools.is_weixin_running():
            raise NotStartError()
        hwnd = Tools.get_weixin_hwnd()
        if not hwnd:
            raise NotFoundError()

        main_window = desktop().window(handle=hwnd)
        if main_window.class_name() == "mmui::LoginWindow":
            raise NotLoginError()
        if main_window.class_name() == "mmui::MainWindow":
            ui = ui_elements()
            main_window.restore()
            close_button = main_window.child_window(**ui.CloseButton)
            if close_button.exists(timeout=0.1):
                close_button.click()
                main_window.restore()
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST,
                0, 0, window_size[0], window_size[1], win32con.SWP_NOMOVE,
            )
            window_width, window_height = window_size[0], window_size[1]
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            new_left = (screen_width - window_width) // 2
            new_top = (screen_height - window_height) // 2
            if screen_width != window_width:
                win32gui.MoveWindow(hwnd, new_left, new_top, window_width, window_height, True)
            if is_maximize:
                win32gui.SendMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_MAXIMIZE, 0)
            if not is_maximize:
                win32gui.SendMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_RESTORE, 0)
            offline_button = main_window.child_window(**ui.OffLineButton)
            if offline_button.exists(timeout=0.1):
                main_window.close()
                raise NetWorkError("当前网络不可用,无法进行UI自动化!")
            Tools.cancel_pin(main_window)
            return main_window

    @staticmethod
    def search_official_account(
        name: str,
        load_delay: float = None,
        subscribe: bool = False,
        is_maximize: bool = None,
        close_weixin: bool = None,
    ) -> Any:
        """搜索公众号并打开其主页，返回主页窗口对象。

        主页窗口用 title=GlobalConfig.get_official_account_type(name) 定位，
        该值来自账号类型映射表。
        """
        from pywinauto import Desktop

        if is_maximize is None:
            is_maximize = GlobalConfig.is_maximize
        if load_delay is None:
            load_delay = GlobalConfig.load_delay
        if close_weixin is None:
            close_weixin = GlobalConfig.close_weixin

        ui = ui_elements()
        main_window = Navigator.open_weixin(is_maximize=is_maximize)
        main_window.child_window(**ui.SideBarWeixin).click_input()
        search_edits = main_window.descendants(**ui.MainSearch)
        search_edit = search_edits[1] if len(search_edits) == 2 else search_edits[0]
        search_edit.click_input()
        search_edit.set_text(name)

        search_result_spec = main_window.child_window(**ui.SearchResult)
        if search_result_spec.exists(timeout=load_delay):
            search_list_view = search_result_spec.wait(wait_for="ready", timeout=load_delay)
            items = search_list_view.items()
            target_item = None
            for item in items:
                item_text = item.window_text().strip()
                if item_text == name:
                    target_item = item
                    break
            if target_item is None:
                raise NoResultsError(f"在搜索结果列表中未找到名称【{name}】的公众号")
            target_item.click_input()
            time.sleep(GlobalConfig.load_delay * round(random.uniform(0.7, 1.3), 2))
            _log(f"✅ 已点击目标公众号：{name}")

            desktop_uia = Desktop(backend="uia")
            chat_window_spec = desktop_uia.window(
                class_name="mmui::ChatSingleWindow", title_re=f".*{name}.*"
            )
            if not chat_window_spec.exists(timeout=load_delay):
                raise NoResultsError("公众号会话窗口未正常打开")

            title_bar_spec = chat_window_spec.child_window(auto_id="chat_message_page") \
                .child_window(class_name="mmui::ChatTitleBarMasterView")
            title_bar = title_bar_spec.wait(wait_for="ready", timeout=2)

            btn_list = [
                ctrl for ctrl in title_bar.descendants()
                if ctrl.element_info.control_type == "Button" and ctrl.is_visible()
            ]
            if not btn_list:
                raise NotFoundError("未找到公众号主页入口按钮")
            btn_list.sort(key=lambda b: b.rectangle().left)
            profile_button = btn_list[-1]

            profile_button.click_input()
            time.sleep(GlobalConfig.load_delay * round(random.uniform(0.7, 1.3), 2))
            official_account_win_spec = desktop_uia.window(
                class_name="Chrome_WidgetWin_0",
                title=GlobalConfig.get_official_account_type(name),
            )
            if not official_account_win_spec.exists(timeout=load_delay):
                raise NotFoundError("点击资料图标后，公众号主页窗口未弹出")

            chat_window_spec.close()
            return official_account_win_spec
        raise NoResultsError("查无此公众号!")
