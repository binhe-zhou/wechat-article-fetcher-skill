"""公众号文章链接采集。

在 Windows 微信客户端内搜索公众号 / 服务号、打开其主页「文章」标签，
按日期区间遍历文章卡片，并通过「更多 -> 复制链接」采集文章链接。

关键行为：
  - is_maximize / close_weixin 为 None 时取 GlobalConfig 默认值；
  - 所有等待以 GlobalConfig.load_delay 为基数并乘随机系数；
  - 主页由 Navigator.search_official_account 打开；
  - RootWebArea 控件树按 Y 坐标排序、按 runtime_id 去重，识别日期分组
    与「余下 X 篇」折叠条，点击卡片后从剪贴板读取链接；
  - 循环仅靠「分组日期早于 range_start」终止；
  - 结束时关闭公众号主页窗口。

运行日志写入 stderr，保证 MCP stdio 的 stdout 只承载协议报文。
"""

from __future__ import annotations

import random
import re
import sys
import time
from datetime import date, timedelta
from typing import Any

from . import environment
from .wechat_runtime import GlobalConfig, Navigator, NotFoundError


def _log(message: str) -> None:
    """把运行日志写入 stderr，不污染 MCP stdio 协议流。"""
    print(message, file=sys.stderr, flush=True)


def parse_article_date_text(text: str) -> date | None:
    """解析文章列表分组日期：今天 / 昨天 / 星期X / X月X日 / YYYY-MM-DD。"""
    today = date.today()
    text = text.strip()
    if text == "今天":
        return today
    if text == "昨天":
        return today - timedelta(days=1)

    week_map = {
        "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5, "星期日": 6,
        "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
    }
    if text in week_map:
        target_wd = week_map[text]
        delta = (today.weekday() - target_wd) % 7
        return today - timedelta(days=delta)

    m_month_day = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m_month_day:
        mon = int(m_month_day.group(1))
        day = int(m_month_day.group(2))
        try:
            return date(today.year, mon, day)
        except ValueError:
            return None

    m_ymd = re.search(r"(\d{4})[-‑](\d{1,2})[-‑](\d{1,2})", text)
    if m_ymd:
        try:
            return date(int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3)))
        except ValueError:
            return None
    return None


def is_date_in_range(dt: date | None, start: date, end: date) -> bool:
    """判断分组日期是否落在目标区间内。"""
    if dt is None:
        return False
    return start <= dt <= end


def collect_article_links(
    name: str,
    range_start: date,
    range_end: date,
    is_maximize: bool = None,
    close_weixin: bool = None,
) -> list[str]:
    """采集指定日期区间内的公众号文章链接。

    Args:
        name: 公众号名称（繁体如"工銀亞洲"），需在账号类型映射表中登记。
        range_start: 起始日期 date 对象。
        range_end: 结束日期 date 对象。
        is_maximize: 是否最大化窗口，None 时取 GlobalConfig.is_maximize。
        close_weixin: 任务结束是否关闭微信，None 时取 GlobalConfig.close_weixin。
    Returns:
        list[str]: 文章链接列表。
    """
    from pywinauto import Desktop
    import pyperclip

    if is_maximize is None:
        is_maximize = GlobalConfig.is_maximize
    if close_weixin is None:
        close_weixin = GlobalConfig.close_weixin

    # 打开公众号主页
    official_account_win = Navigator.search_official_account(
        name=name, is_maximize=is_maximize, close_weixin=close_weixin
    )
    time.sleep(GlobalConfig.load_delay * round(random.uniform(0.7, 1.3), 2))

    # 切换【文章】标签页
    tab_article = official_account_win.child_window(title="文章", control_type="Hyperlink")
    if not tab_article.exists(timeout=3):
        raise NotFoundError("公众号主页找不到【文章】标签")
    tab_article.click_input()
    time.sleep(GlobalConfig.load_delay * round(random.uniform(0.7, 1.3), 2))

    desktop_uia = Desktop(backend="uia")
    processed_runtime_ids = set()
    result_links = []
    stop_flag = False

    current_article_date: date | None = None

    while not stop_flag:
        # 拿到网页根文档节点 RootWebArea
        root_doc_spec = official_account_win.child_window(auto_id="RootWebArea")
        if not root_doc_spec.exists(timeout=4):
            _log("⚠️ 等待网页文档加载...")
            time.sleep(0.8 * round(random.uniform(0.7, 1.3), 2))
            continue
        root_doc = root_doc_spec.wait(wait_for="ready", timeout=4)

        # 获取文档下全部后代可见控件
        all_desc = []
        for c in root_doc.descendants():
            try:
                if not c.is_visible():
                    continue
                rid = c.element_info.runtime_id
                if rid in processed_runtime_ids:
                    continue
                y_pos = c.rectangle().top
                txt = c.window_text().strip()
                cls = c.element_info.class_name or ""
                all_desc.append({
                    "y": y_pos,
                    "ctrl": c,
                    "text": txt,
                    "rid": rid,
                    "cls": cls,
                })
            except Exception:  # noqa: BLE001 - 控件树刷新时跳过失效节点
                continue

        # 按屏幕从上到下排序（Y 升序）
        all_desc.sort(key=lambda x: x["y"])
        if not all_desc:
            _log("ℹ️ 当前页面无可见内容，向下翻页")
            root_doc.set_focus()
            root_doc.type_keys("{DOWN}" * 6)
            time.sleep(GlobalConfig.load_delay * round(random.uniform(0.7, 1.3), 2))
            continue

        # 标记本轮是否触发了展开，展开后需要重新获取控件树
        has_expanded = False

        for item in all_desc:
            ctrl = item["ctrl"]
            txt = item["text"]
            rid = item["rid"]
            cls = item["cls"]

            if len(txt) > 12 and current_article_date is None:
                continue

            # ---------- 识别日期文本 ----------
            parsed_dt = parse_article_date_text(txt)
            if parsed_dt is not None:
                current_article_date = parsed_dt
                _log(f"📅 识别分组日期文本：{txt} → {current_article_date}")
                # 如果分组日期早于目标起始，整体停止抓取
                if current_article_date < range_start:
                    _log(f"🛑 分组日期 {current_article_date} 早于目标区间，全部抓取任务结束")
                    stop_flag = True
                    break
                processed_runtime_ids.add(rid)
                continue

            # ========== 识别并展开「余下X篇」折叠条 ==========
            is_more_bar = "article-list__more-bar" in cls
            more_bar_text = ""
            if is_more_bar:
                # 外层 Group 本身无文本，去内部子 Text 控件提取"余下X篇"
                try:
                    sub_texts = ctrl.descendants(control_type="Text")
                    for st in sub_texts:
                        stxt = st.window_text().strip()
                        if "余下" in stxt and "篇" in stxt:
                            more_bar_text = stxt
                            break
                except Exception:  # noqa: BLE001
                    more_bar_text = ""

            if is_more_bar and more_bar_text:
                processed_runtime_ids.add(rid)
                # 只有当前分组日期在目标区间内才展开
                if current_article_date is not None and range_start <= current_article_date <= range_end:
                    _log("📂 检测到折叠文章组，点击展开")
                    # 滚动到可视区再点击
                    win_rect = official_account_win.rectangle()
                    win_bottom = win_rect.bottom - 40
                    bar_rect = ctrl.rectangle()
                    root_doc.set_focus()
                    while bar_rect.bottom > win_bottom:
                        root_doc.type_keys("{DOWN}")
                        time.sleep(0.25 * round(random.uniform(0.7, 1.3), 2))
                        bar_rect = ctrl.rectangle()
                    # 点击展开
                    ctrl.click_input(coords=(10, 10))
                    time.sleep(0.6 * round(random.uniform(0.7, 1.3), 2))
                    has_expanded = True
                    break  # 展开后 DOM 变化，退出本轮循环，重新获取控件树
                else:
                    # 日期不在范围内，跳过不展开
                    continue

            # ---------- 判断是否是文章条目 Group ----------
            is_article_item = ("article-item" in cls) or ("js_article_card" in cls)
            if not is_article_item:
                continue
            if current_article_date is None:
                continue

            # 判断该篇文章是否在目标时间区间
            if not is_date_in_range(current_article_date, range_start, range_end):
                processed_runtime_ids.add(rid)
                continue

            _log(f"✅ 命中目标文章，日期:{current_article_date}")
            processed_runtime_ids.add(rid)

            # ========== 滚动到可视区再点击 ==========
            # 1. 获取公众号窗口可视区域（屏幕绝对坐标）
            win_rect = official_account_win.rectangle()
            win_top = win_rect.top + 80  # noqa: F841 - 可视区上边界，预留供扩展使用
            win_bottom = win_rect.bottom - 40

            # 2. 获取当前文章卡片的屏幕绝对坐标
            card_rect = ctrl.rectangle()
            card_top = card_rect.top  # noqa: F841 - 卡片上边界，预留供扩展使用
            card_bottom = card_rect.bottom

            # 3. 如果卡片底部在窗口可视区外，就向下滚屏直到卡片完全可见
            root_doc.set_focus()
            scroll_try = 0
            while card_bottom > win_bottom and scroll_try < 10:
                root_doc.type_keys("{DOWN}")
                time.sleep(0.3 * round(random.uniform(0.7, 1.3), 2))
                card_rect = ctrl.rectangle()
                card_top = card_rect.top  # noqa: F841 - 卡片上边界，预留供扩展使用
                card_bottom = card_rect.bottom
                scroll_try += 1

            # 4. 计算相对控件左上角的点击坐标（水平居中，垂直 70% 处=标题区）
            card_width = card_rect.right - card_rect.left
            card_height = card_rect.bottom - card_rect.top
            rel_x = card_width // 2
            rel_y = int(card_height * 0.7)

            # 5. 点击 + 重试机制
            click_ok = False
            official_account_win.set_focus()
            time.sleep(0.15)

            # 先创建文章窗口的查找规范（WindowSpecification，支持 child_window）
            webview_spec = desktop_uia.window(class_name="Chrome_WidgetWin_0", title="微信")

            for retry in range(2):
                ctrl.click_input(coords=(rel_x, rel_y))
                time.sleep(0.5 * round(random.uniform(0.7, 1.3), 2))

                # 检查文章窗口是否弹出
                if webview_spec.exists(timeout=2):
                    click_ok = True
                    break
                _log(f"⚠️ 第{retry + 1}次点击未弹出窗口，重试")

            if not click_ok:
                _log("❌ 点击重试后仍未打开文章，跳过该篇")
                continue

            # 获取窗口控件实例，用于输入、点击等操作
            webview_win = webview_spec.wait(wait_for="ready", timeout=3)
            webview_win.set_focus()
            time.sleep(0.3 * round(random.uniform(0.7, 1.3), 2))

            url = ""
            more_btn_spec = webview_spec.child_window(class_name="AppMenuButton", title="更多")
            if more_btn_spec.exists(timeout=3):
                more_btn = more_btn_spec.wait(wait_for="ready")
                more_btn.click_input()
                time.sleep(0.5 * round(random.uniform(0.7, 1.3), 2))
                webview_win.type_keys("{DOWN}{DOWN}")  # 向下移动 2 次，定位到复制链接
                time.sleep(0.2 * round(random.uniform(0.7, 1.3), 2))
                webview_win.type_keys("{ENTER}")  # 回车执行【复制链接】
                time.sleep(0.35 * round(random.uniform(0.7, 1.3), 2))

                url = pyperclip.paste()
                if url:
                    result_links.append(url)
                else:
                    _log("❌ 键盘执行复制链接后剪贴板为空")

            # ========= 关闭按钮逻辑，用 spec 调用 child_window =========
            close_btn_spec = webview_spec.child_window(title="关闭", control_type="Button", found_index=1)
            if close_btn_spec.exists(timeout=2):
                close_btn_spec.click_input()
            time.sleep(GlobalConfig.load_delay * round(random.uniform(0.7, 1.3), 2))

        # for-end all_desc

        if stop_flag:
            break

        # 如果本轮触发了展开，不执行全局翻页，直接重新加载控件树
        if has_expanded:
            continue

        # 当前页处理完毕，向下滚动页面加载更多历史文章
        root_doc.set_focus()
        root_doc.type_keys("{DOWN}" * 2)
        time.sleep(GlobalConfig.load_delay * round(random.uniform(0.7, 1.3), 2))
    # while-end

    official_account_win.close()
    _log(f"✅ {name} 抓取完成，共拿到 {len(result_links)} 条文章链接")
    return result_links


def get_article_links(
    account_name: str,
    start_date: str,
    end_date: str,
    is_maximize: bool = None,
    close_weixin: bool = None,
) -> dict[str, Any]:
    """MCP 层包装：字符串日期解析、环境门控与结构化返回。

    采集由 collect_article_links 完成；本函数只做协议层转换，
    不改动采集结果与顺序。
    """
    result: dict[str, Any] = {
        "ok": False,
        "account_name": account_name,
        "date_range": {"start": start_date, "end": end_date},
        "count": 0,
        "links": [],
        "error": "",
    }
    try:
        range_start = date.fromisoformat(start_date)
        range_end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        result["error"] = f"日期格式应为 YYYY-MM-DD：{exc}"
        return result
    if range_start > range_end:
        result["error"] = "起始日期不能晚于结束日期"
        return result

    env = environment.check()
    if not env["capabilities"]["get_article_links"]:
        result["error"] = "环境校验未通过：" + "；".join(env["issues"])
        result["environment"] = env
        return result

    try:
        links = collect_article_links(
            account_name, range_start, range_end,
            is_maximize=is_maximize, close_weixin=close_weixin,
        )
    except Exception as exc:  # noqa: BLE001 - UIA 异常统一转为结构化错误，不自动重试
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["ok"] = True
    result["count"] = len(links)
    result["links"] = links
    return result
