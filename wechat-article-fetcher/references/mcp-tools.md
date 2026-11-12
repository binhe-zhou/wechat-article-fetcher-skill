# MCP Tools 契约

Server 名称：`wechat-article-fetcher`，transport：`stdio`。启动方式 `python -m mcp_server`（cwd 为 Skill 根目录）。

所有 tool 返回 JSON 对象，统一含 `ok`（bool）与 `error`（str，成功时为空字符串）。服务端不向协议层抛异常，失败一律结构化返回。

---

## 1. `check_environment`

环境自检，调用其它 tool 前必须执行。无参数。校验平台、微信客户端版本（读注册表）、微信进程与依赖完整性；**不校验「讲述人」是否开启、UIA 控件树是否可见、账号是否已订阅**，也不返回对应字段。

```json
{
  "ok": true,
  "platform": "Windows",
  "python_version": "3.11.9",
  "required_wechat_version": "4.1.8.101",
  "wechat_running": true,
  "wechat_version": "4.1.8.101",
  "version_match": true,
  "dependencies": {"windows_libs_complete": true, "missing": [], "mcp_sdk_available": true},
  "issues": [],
  "capabilities": {
    "get_article_links": true,
    "get_article_title": true,
    "get_article_publish_time": true,
    "get_article_content": true,
    "get_article": true
  }
}
```

`capabilities.get_article_links == false` 时禁止调用 `get_article_links`。讲述人、UIA 可见性与账号订阅状态属于使用提示，不会出现在 `issues` 中。

---

## 2. `get_article_links`

按公众号名称与日期区间采集文章链接（Windows UIA 自动化）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `account_name` | string | 是 | — | 公众号全称，需与微信搜索结果完全一致、已在账号类型映射表中登记，且**登录的微信账号已订阅该公众号/服务号** |
| `start_date` | string | 是 | — | `YYYY-MM-DD`，含当日；包装层转为 `date` 对象 |
| `end_date` | string | 是 | — | `YYYY-MM-DD`，含当日 |
| `is_maximize` | bool \| null | 否 | `null` | 为 `null` 时取 `GlobalConfig.is_maximize`（默认 `False`） |
| `close_weixin` | bool \| null | 否 | `null` | 为 `null` 时取 `GlobalConfig.close_weixin`（默认 `False`） |

> **前置条件（仅提示，不校验）**：登录的微信账号必须提前订阅目标公众号或服务号。未订阅时通常搜索不到该账号或打不开「文章」标签，环境自检不会检测订阅状态，详见 `troubleshooting.md`。
>
> 没有 `max_scrolls` 等额外参数：循环仅靠「分组日期早于 `start_date`」结束。

返回：

```json
{
  "ok": true,
  "account_name": "示例公众号",
  "date_range": {"start": "2026-11-01", "end": "2026-11-05"},
  "count": 2,
  "links": ["https://mp.weixin.qq.com/s/xxxx", "https://mp.weixin.qq.com/s/yyyy"],
  "error": ""
}
```

失败时 `ok=false`，`error` 为可执行的原因；环境未通过时额外带 `environment` 字段。采集层返回 `list[str]`，MCP 层只做结构化封装，不改动采集结果与顺序。

### 采集流程

1. `Navigator.search_official_account()` → `Navigator.open_weixin()` → `Tools.is_weixin_running()` / `get_weixin_hwnd()`（`EnumWindows` 筛 Qt 通用窗口 + UIA `mmui::.*Window` 过滤）/ `cancel_pin()`。
2. 按 `GlobalConfig.language` 取控件常量，点击侧栏「微信」、在搜索框 `set_text(name)`、在 `search_list` 中精确匹配公众号名并点击。
3. 会话窗口标题栏取最右侧可见 Button 打开主页；主页窗口用 `Chrome_WidgetWin_0` + `title=GlobalConfig.get_official_account_type(name)` 定位。
4. 切换「文章」标签 → `RootWebArea` 控件树按 Y 排序、按 `runtime_id` 去重 → 日期分组（今天 / 昨天 / 星期X / X月X日 / YYYY-MM-DD）→ 展开「余下 X 篇」→ 卡片滚动到可视区后点击 → 文章窗口「更多 → 复制链接」→ `pyperclip.paste()` → 关闭窗口 → 翻页。
5. 分组日期早于起始日期即停止；结束关闭公众号主页窗口。

所有等待为 `GlobalConfig.load_delay * round(random.uniform(0.7, 1.3), 2)`（默认 `load_delay=2.0`）。

---

## 3. `get_article_title`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `url` | string | `mp.weixin.qq.com` 文章链接 |

```json
{"ok": true, "url": "https://mp.weixin.qq.com/s/xxxx", "title": "文章标题", "error": ""}
```

解析优先级：`og:title` → `<title>`。

---

## 4. `get_article_publish_time`

```json
{
  "ok": true,
  "url": "https://mp.weixin.qq.com/s/xxxx",
  "publish_time": 1762000000,
  "publish_time_str": "2026-11-01 18:26",
  "error": ""
}
```

`publish_time` 为 Unix 秒，`publish_time_str` 为 UTC+8 的 `YYYY-MM-DD HH:MM`；未解析到时 `publish_time = 0`。解析优先级：`var ct = "..."` → `publish_time%22%3A` → `"publish_time"`。

---

## 5. `get_article_content`

```json
{"ok": true, "url": "https://mp.weixin.qq.com/s/xxxx", "content": "正文纯文本…", "error": ""}
```

从 `id="js_content"` 提取，去除 script / style / HTML 标签并反转义，按非空行拼接。

---

## 6. `get_article`

单篇全量获取（推荐批量场景使用，避免重复抓取）：

```json
{
  "ok": true,
  "url": "https://mp.weixin.qq.com/s/xxxx",
  "title": "文章标题",
  "publish_time": 1762000000,
  "publish_time_str": "2026-11-01 18:26",
  "content": "正文纯文本…",
  "error": ""
}
```

---

## 错误码与错误文本

| 场景 | `error` 示例 | 处置 |
| --- | --- | --- |
| 环境不满足 | `环境校验未通过：当前系统为 Darwin…` | 转述 `issues`，中止采集 |
| 日期非法 | `日期格式应为 YYYY-MM-DD：…` | 修正参数 |
| 微信未启动 / 未登录 | `NotStartError` / `NotLoginError` | 启动并登录微信 4.1.8.101 |
| 公众号未登记映射 | `NotFoundError: 点击资料图标后，公众号主页窗口未弹出` | 在 `OFFICIAL_ACCOUNT_TYPE_MAP` 登记名称与账号类型 |
| 搜索无结果 | `NoResultsError: 在搜索结果列表中未找到名称【x】的公众号` | 核对公众号全称与订阅状态，不重试 |
| 控件定位失败 | `NotFoundError: 未找到公众号主页入口按钮` / `公众号主页找不到【文章】标签` | 建议开启讲述人并保持微信前台（仅提示，不校验）；不要自动重试 |
| 链接非法 | `仅支持 mp.weixin.qq.com 域名下的公众号文章链接` | 换用合法链接 |
| 内容过小 | `返回内容过小，可能为链接失效或访问受限` | 浏览器打开核验 |
| 安全验证 | `触发微信安全验证（环境异常/滑块验证码）…` | 人工在浏览器完成验证后重试 |
| 页面结构变化 | `未能解析到标题与正文，可能文章已删除或页面结构变化` | 检查解析正则 |

解析结果按 URL 缓存 300 秒：`get_article_title` / `get_article_publish_time` / `get_article_content` 连续调用同一链接时只发出一次 HTTP 请求。

---

## 调用示例（工作流）

```
1. check_environment()                     -> capabilities.get_article_links
2. get_article_links("示例公众号",
                     "2026-11-01",
                     "2026-11-05")         -> links[]
3. for url in links: get_article(url)     -> 标题 + 发布时间 + 正文
4. 汇总时保留 url，逐条标注失败项
```
