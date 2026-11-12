---
name: wechat-article-fetcher
description: "基于 MCP 协议获取微信公众号文章：先在 Windows 微信客户端（必须为 4.1.8.101）中按公众号名称与日期区间采集文章链接，再按链接获取标题、发布时间与正文。当用户要求抓取或汇总某公众号某时间段的文章、提取公众号文章标题、发布时间、正文，或解析 mp.weixin.qq.com 文章链接时，应使用本 Skill。链接采集依赖账号类型映射表，且登录的微信账号需已订阅目标公众号或服务号；讲述人与 UIA 控件树仅作使用提示、不做校验；非 Windows 环境必须中止链接采集并告知用户，但仍可解析用户已提供的文章链接。"
---

# 微信公众号文章获取（MCP）

## 一、能力矩阵

| 能力 | MCP Tool | 数据来源 | 运行环境 |
| --- | --- | --- | --- |
| 环境自检 | `check_environment` | 注册表版本 / 进程 / 依赖 | 任意平台（可返回"不支持"结论） |
| 文章链接获取 | `get_article_links` | 微信客户端 RPA 复制文章链接 | **仅 Windows + 微信 4.1.8.101 + 账号已订阅该公众号**（讲述人仅提示，不校验） |
| 文章标题获取 | `get_article_title` | 文章页 `og:title` | 任意平台，需网络可达 `mp.weixin.qq.com` |
| 发布时间获取 | `get_article_publish_time` | 文章页 `var ct` / `publish_time` | 同上 |
| 文章内容获取 | `get_article_content` | 文章页 `js_content` 正文 | 同上 |
| 单篇全量获取 | `get_article` | 一次请求返回标题 + 时间 + 正文 | 同上 |

**核心依赖链：** 标题 / 发布时间 / 正文都以文章链接为输入。链接必须来自 `get_article_links` 的返回结果，或由用户明确提供合法的 `mp.weixin.qq.com` 链接。禁止推测、拼接或编造文章链接。

## 二、实现说明

链接采集在微信客户端内完成「搜索公众号 → 打开会话 → 进入主页 → 文章标签 → 复制链接」这条链路，由 `mcp_server/` 下的三个模块协作：

```
get_article_links
  -> Navigator.search_official_account(name, is_maximize, close_weixin)
       -> Navigator.open_weixin -> Tools.is_weixin_running / get_weixin_hwnd / cancel_pin
       -> SideBar.Weixin + Main_window.Search + SearchResult（按 GlobalConfig.language）
       -> 会话窗口标题栏最右 Button 打开主页
       -> Chrome_WidgetWin_0, title=GlobalConfig.get_official_account_type(name)
  -> 文章标签 / RootWebArea 控件树 / 日期分组 / 折叠条 / 卡片点击 / 复制链接
```

**全局配置（`mcp_server/wechat_runtime.py`）：**

- `OFFICIAL_ACCOUNT_TYPE_MAP`：公众号名称 →「公众号」/「服务号」，决定主页窗口的 `title`。**名称未登记时返回 `None`，主页窗口定位必然失败**。新增公众号时在该字典登记，或调用 `GlobalConfig.register_official_account(name, account_type)`。
- `load_delay`（默认 `2.0` 秒）：所有 `time.sleep` 与 `exists/wait` 超时的基数，乘以 `round(random.uniform(0.7, 1.3), 2)`。
- `language`（自动检测，失败回落简体中文）：决定搜索框 / 侧栏 / 关闭按钮的控件标题（简体中文 / English / 繁體中文三套常量）。
- `Version`（读注册表 `HKCU\Software\Tencent\Weixin` 的 `Version`）：环境校验据此匹配 4.1.8.101。
- `is_maximize`（默认 `False`）、`close_weixin`（默认 `False`）、`window_size`（默认 `(1000, 1000)`）。

**账号订阅前置条件（仅提示，不校验）：** 当前登录的微信账号必须提前关注（订阅）目标公众号或服务号。未订阅时搜索结果通常不出现该账号，或打不开带「文章」标签的主页，表现为 `NoResultsError` / `NotFoundError` / `count == 0`。该状态无法由程序可靠判断，故**未写入 `check_environment()` 的 `issues` 与 `capabilities`**；执行前由用户确认，失败时按 `references/troubleshooting.md` 排查。标题 / 发布时间 / 正文的解析不受此限制，可直接处理用户提供的链接。

## 三、强制前置检查

执行任何采集动作前，先调用 `check_environment`（或运行 `scripts/check_environment.py`）。

- `capabilities.get_article_links == false` → **立即中止链接采集**，把 `issues` 逐条转述给用户。常见原因：非 Windows、微信版本不是 4.1.8.101、微信未启动、依赖缺失。
- 采集前确认公众号名称已在账号类型映射表中、登录的微信账号**已订阅**该公众号或服务号（订阅状态仅作提示、不写入校验）；否则先补配置或请用户在微信中关注后再执行。
- `capabilities.get_article_* == true` 但用户未提供链接 → 先请用户提供链接，不得虚构。
- **「讲述人」是否开启、UIA 控件树是否可见不做校验**：这两项不写入 `issues`、不影响 `capabilities`，只在使用提示中告知用户。若因控件树不可见导致采集失败，按 `references/troubleshooting.md` 排查。

环境依赖与配置详解见 `references/environment.md`。

## 四、标准工作流

1. **确认意图**：明确公众号全称（与微信搜索结果完全一致）、日期区间 `YYYY-MM-DD`，并提示用户确认登录的微信账号**已订阅**该公众号或服务号。缺任一项先向用户询问。
2. **环境门控**：调用 `check_environment`；失败则按上一节处理。
3. **采集链接**：调用 `get_article_links(account_name, start_date, end_date)`，读取 `links`。
   - `ok == false` → 停止后续步骤，返回 `error`；若错误指向搜不到公众号，先提示用户确认订阅状态，不要反复重试。
   - `count == 0` → 如实说明"该区间内未采集到文章"，不要用其它来源补数据。
4. **解析文章**：对 `links` 中每条链接调用 `get_article`（推荐）；仅在用户只要某一字段时调用对应单一 tool。
   - 逐条处理，对 `ok == false` 的条目单独记录 `error`，不要中断整批。
   - 同一链接的多个字段工具共用缓存，不会重复请求。
5. **汇总输出**：按用户要求整理，保留 `url` 便于回溯；`publish_time_str` 为 UTC+8 时间。不要修改或补写正文内容。

批量处理时复用第 3 步拿到的 `links`，不要为每篇文章重新跑一次 RPA。

## 五、部署 MCP 服务

服务端代码位于 `mcp_server/`，以 stdio transport 运行：

```bash
cd <本 Skill 目录>
python -m pip install -r requirements.txt
python scripts/check_environment.py
python -m mcp_server
```

环境自检只校验平台、微信版本（注册表）、微信进程与依赖，不检测讲述人、UIA 控件树或账号订阅状态。

注册示例见外层 `../mcp.json.example`（WorkBuddy 中写入 `~/.workbuddy-ai/mcp.json` 的 `mcpServers`），`cwd` 必须指向本 Skill 目录。仅在 Windows 主机上运行链接采集；macOS / Linux 主机只适合调用解析类 tool。

Python 3.10+；依赖 `mcp`（或 `fastmcp`）、`pywinauto`、`pywin32`、`pyperclip`、`psutil`。

## 六、约束

- 控件定位方式与微信客户端 4.1.8.101 的 UIA 结构绑定。适配其它版本时，需同步更新 `wechat_runtime.py` 的控件常量、账号类型映射与相关文档，并重新验证完整链路。
- **不得跳过环境门控**，不得在 macOS / Linux 上尝试启动微信 RPA。
- **不得校验讲述人与 UIA 控件树可见性**：相关要求只作提示，不因这两项阻断采集。
- **账号订阅状态只作提示、不做校验**：不在 `check_environment` 中检测是否关注；遇到搜不到公众号时提示用户先关注，不要反复重试。
- **不得编造链接、标题、时间或正文**；任何字段获取失败都要显式标注。
- **不得自动重试 UI 自动化失败**（`ElementNotFoundError` / `TimeoutError` / `ComError` 等）：结束任务并反馈，是否重试由用户决定。
- **不得修改筛选口径**：本 Skill 只做"获取"，不做业务筛选。
- 所有日志写入 stderr；stdout 仅用于 MCP 协议报文。
- 遵守微信使用条款，控制采集频率。循环仅靠「分组日期早于起始日期」终止，没有额外的滚动次数上限。

## 七、资源索引

| 路径 | 用途 |
| --- | --- |
| `mcp_server/server.py` | MCP tools 定义（参数、返回结构） |
| `mcp_server/link_collector.py` | 文章链接采集 |
| `mcp_server/wechat_runtime.py` | 全局配置、控件常量、窗口导航 |
| `mcp_server/article_parser.py` | 标题 / 发布时间 / 正文解析 |
| `mcp_server/environment.py` | 环境自检（注册表版本；不含讲述人 / UIA / 订阅校验） |
| `scripts/check_environment.py` | 离线自检 CLI（输出 JSON） |
| `scripts/fetch_article.py` | 单链接解析调试 CLI |
| `references/environment.md` | 环境、注册表版本、全局配置与订阅前置条件 |
| `references/mcp-tools.md` | 工具参数 / 返回 / 错误码契约 |
| `references/troubleshooting.md` | 常见失败与处置 |

工具契约细节查阅 `references/mcp-tools.md`。
