# 运行环境依赖

本 Skill 的两条链路环境要求不同，必须区分清楚。

| 链路 | 环境要求 |
| --- | --- |
| 文章链接获取（`get_article_links`） | Windows + 微信客户端 **4.1.8.101** + 已登录 + **登录账号已订阅目标公众号/服务号（仅提示，不校验）** + Python 3.10 及依赖 + 公众号名称已登记账号类型 |
| 标题 / 发布时间 / 正文解析 | 任意平台 + 网络可访问 `mp.weixin.qq.com`（Python 标准库即可，不需要微信客户端） |

注意：解析链路虽然不依赖 Windows，但**数据上仍依赖链接**。没有链接时，解析类 tool 无从调用。

**账号订阅前置条件（仅提示，不校验）**：链接采集在微信客户端内搜索并进入公众号 / 服务号主页读取「文章」列表，因此**当前登录的微信账号必须提前关注（订阅）目标公众号或服务号**。未订阅时搜索结果通常不出现该账号，或打不开带「文章」标签的主页。该状态无法由程序可靠判断，**未纳入 `check_environment()` 的 `issues` 与 `capabilities`**，也不在任何 tool 中检测；执行前由用户确认，失败时按 `troubleshooting.md` 排查。解析类 tool 不受此限制。

## 1. 操作系统：仅 Windows

链接采集通过 `pywinauto` 的 UI Automation（`backend="uia"`）驱动微信桌面客户端，依赖 `win32gui` / `win32api` / `pyperclip`。macOS、Linux 无法运行，`check_environment()` 会返回 `issues` 并把 `capabilities.get_article_links` 置为 `false`。

## 2. 微信客户端版本：严格 4.1.8.101

`REQUIRED_WECHAT_VERSION = "4.1.8.101"`，版本不一致直接拒绝采集。

版本号由 `wechat_runtime.read_registry_version()` 读取 `HKEY_CURRENT_USER\Software\Tencent\Weixin` 下的 `Version` 值，按 `hex(int_version)[5:]` 拆成四段（`主.次.修订.构建`），例如解析出 `4.1.8.101`。若注册表项缺失，自检返回「无法读取微信客户端版本」。

采集逻辑依赖该版本微信 4.x 的 UIA 控件树结构，包括：

- 主窗口 `mmui::MainWindow` / `mmui::LoginWindow`；
- 会话窗口 `mmui::ChatSingleWindow`、标题栏 `mmui::ChatTitleBarMasterView`；
- 搜索结果列表 `auto_id="search_list"`、搜索框 `mmui::XValidatorTextEdit`；
- 公众号主页窗口 `Chrome_WidgetWin_0` + `RootWebArea` + `article-item` / `js_article_card` / `article-list__more-bar`；
- 文章弹窗 `Chrome_WidgetWin_0` + `AppMenuButton`（更多）→ 复制链接。

## 3. 全局配置与控件定位

链接采集的行为由 `mcp_server/wechat_runtime.py` 的 `GlobalConfig` 决定：

| 配置 | 默认 | 作用 |
| --- | --- | --- |
| `OFFICIAL_ACCOUNT_TYPE_MAP` | 18 条映射 | `get_official_account_type(name)` 返回「公众号」/「服务号」，作为主页窗口 `title`；未登记的名称返回 `None`，主页定位失败 |
| `load_delay` | `2.0` | 所有 `sleep` 与 `exists/wait` 超时的基数，乘随机系数 `round(random.uniform(0.7,1.3),2)` |
| `language` | 检测 WechatAppex 命令行，失败回落简体中文 | 决定 `SideBar.Weixin` / `Main_window.Search` / `Buttons.CloseButton` / `OffLineButton` 的标题（简体中文 / English / 繁體中文三套） |
| `Version` | 注册表读取 | 见上一节 |
| `is_maximize` / `close_weixin` | `False` / `False` | 传入 `search_official_account` |
| `window_size` | `(1000, 1000)` | 主窗口尺寸 |

新增公众号：编辑 `OFFICIAL_ACCOUNT_TYPE_MAP` 或调用 `GlobalConfig.register_official_account(name, "公众号"/"服务号")`。主页窗口按精确标题定位，请勿改用模糊匹配。

**关于 `Qt51514QWindowIcon`**：它只出现在 `Tools.get_weixin_hwnd()` 的 `win32gui.EnumWindows` 回调里，用于筛出 win32 层面的 Qt 通用窗口；随后还要用 UIA 类名匹配 `mmui::.*Window` 才算拿到主窗口句柄。业务层不直接使用这个类名定位窗口。

## 4. 讲述人（Narrator）与 UIA 控件树：仅提示，不校验

**本 Skill 不对讲述人是否开启、UIA 控件树是否可见做任何校验。** `check_environment()` 不检测 `Narrator.exe` 进程，也不读取微信主窗口 `class_name` 判断 UIA 可见性；这两项不写入 `issues`、不影响 `capabilities.get_article_links`，也不返回对应字段。

微信 4.x 默认不向 UIA 暴露完整控件树；讲述人等屏幕阅读器启动时，系统可访问性 API 要求应用暴露完整 UI 元素信息，控件树才可见。若未开启，采集阶段可能出现控件定位失败，届时按 `troubleshooting.md` 处理，而不是由环境自检提前阻断。

建议的手动操作（非自检项）：`Win + Ctrl + Enter` 开启讲述人；登录微信 4.1.8.101 并保持主窗口前台、非最小化、屏幕未锁定。已知限制：微信 4.1+ 对从未使用过无障碍模式的新账号可能无法提供 UI 树，属客户端侧限制。

## 5. 依赖清单

| 依赖 | 用途 | 平台 |
| --- | --- | --- |
| `mcp>=1.2.0` 或 `fastmcp>=2.0.0` | MCP 协议服务 | 全部 |
| `pywinauto>=0.6.8` | UIA 控件定位与点击 | Windows |
| `pywin32>=308` | `win32gui` / `win32api` / `win32con` 窗口与注册表 | Windows |
| `pyperclip>=1.8.2` | 读取「复制链接」写入的剪贴板 | Windows |
| `psutil>=5.9.5` | 进程检测与语言检测 | Windows |

解析链路使用 `urllib`，无第三方依赖。

## 6. 自检结果字段

`check_environment` / `scripts/check_environment.py` 返回：

- `ok`：链接采集链路是否整体就绪；
- `platform`、`python_version`、`required_wechat_version`、`wechat_running`、`wechat_version`（注册表）、`version_match`；
- `dependencies.windows_libs_complete` / `missing` / `mcp_sdk_available`；
- `issues`：所有不满足项（直接转述给用户）；
- `capabilities`：逐 tool 的可用性，解析类恒为 `true`。

不返回 `narrator_running`、`ui_tree_visible` 等字段；讲述人、UIA 控件树与账号订阅状态属于使用提示，不参与校验。
