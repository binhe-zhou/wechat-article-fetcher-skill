# wechat-article-fetcher-skill

基于 MCP 协议的微信公众号文章获取 Skill：在 Windows 微信客户端中采集指定公众号 / 服务号在日期区间内的文章链接，并按链接获取**标题、发布时间、正文**。

仓库同时包含一个标准 Agent Skill（`wechat-article-fetcher/`，含 `SKILL.md` / `scripts/` / `references/`）和一个 stdio 模式的 MCP Server，可直接注册到支持 MCP 的 AI 客户端。

## 能力

| 能力 | MCP Tool | 运行环境 |
| --- | --- | --- |
| 环境自检 | `check_environment` | 任意平台 |
| 文章链接获取 | `get_article_links` | Windows + 微信 4.1.8.101 |
| 文章标题获取 | `get_article_title` | 任意平台 + 网络 |
| 发布时间获取 | `get_article_publish_time` | 任意平台 + 网络 |
| 文章内容获取 | `get_article_content` | 任意平台 + 网络 |
| 单篇全量获取 | `get_article` | 任意平台 + 网络 |

工作流：`check_environment → get_article_links → links[] → get_article(每条链接) → 汇总`。标题、发布时间、正文都以文章链接为输入，不支持脱离链接直接抓取。

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | 链接采集仅支持 **Windows**；解析类 tool 可在任意平台运行 |
| 微信客户端 | **4.1.8.101**（严格匹配，控件树结构与该版本绑定） |
| 登录账号 | 必须**提前订阅**目标公众号或服务号 |
| Python | 3.10+ |
| 依赖 | `mcp`、`pywinauto`、`pywin32`、`pyperclip`、`psutil` |
| 账号类型 | 公众号名称需在 `OFFICIAL_ACCOUNT_TYPE_MAP` 中登记「公众号」/「服务号」 |

**使用提示（不参与环境校验）**：微信 4.x 默认不暴露完整 UIA 控件树，建议在 Windows 上开启「讲述人」并保持微信前台；登录账号是否已订阅目标公众号，也需要用户自行确认。这两类条件无法由程序可靠判断，详见 `wechat-article-fetcher/references/environment.md`。

## 快速开始

```bash
git clone <repository-url>
cd wechat-article-fetcher-skill/wechat-article-fetcher
python -m pip install -r requirements.txt
python scripts/check_environment.py
```

自检输出 `ok: true` 且 `version_match: true` 后，将 `mcp.json.example` 中的条目合并进AI Agent的 MCP 配置文件（WorkBuddy 为 `~/.workbuddy-ai/mcp.json`），以完成MCP Server的注册：

```json
{
  "mcpServers": {
    "wechat-article-fetcher": {
      "command": "C:\\Python311\\python.exe",
      "args": ["-m", "mcp_server"],
      "cwd": "C:\\path\\to\\wechat-article-fetcher-skill\\wechat-article-fetcher",
      "env": { "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1" }
    }
  }
}
```

`cwd` 必须指向 `wechat-article-fetcher/` 的绝对路径，`command` 使用已安装依赖的 Python 解释器。新增的自定义连接器需在客户端的连接器管理页点击「信任 / 启用」。

**安装 Skill**：把 `wechat-article-fetcher/` 整个目录拷到AI Agent的 skills 目录（WorkBuddy 用户级：`~/.workbuddy-ai/skills/`）或在Agent上直接添加技能。该目录名与 `SKILL.md` 的 `name` 一致，可独立分发。

**单独验证解析链路**（不需要微信客户端、不经过 MCP）：

```bash
python scripts/fetch_article.py --url "https://mp.weixin.qq.com/s/<真实文章链接>"
```

## 目录结构

```
wechat-article-fetcher-skill/
├── README.md                  # 项目说明
├── LICENSE                    # LGPL-2.1
├── NOTICE                     # 第三方归属声明
├── .gitignore
├── mcp.json.example           # MCP 客户端注册示例
└── wechat-article-fetcher/    # 可直接安装 / 分发的 Skill 单元
    ├── SKILL.md               # 触发条件、工作流与约束
    ├── requirements.txt
    ├── mcp_server/            # MCP Server 与全部实现
    │   ├── server.py          # 6 个 tool 定义
    │   ├── wechat_runtime.py  # 全局配置、控件常量、窗口导航
    │   ├── link_collector.py  # 文章链接采集
    │   ├── article_parser.py  # 标题 / 发布时间 / 正文解析
    │   └── environment.py     # 环境自检
    ├── scripts/
    │   ├── check_environment.py
    │   └── fetch_article.py
    └── references/
        ├── environment.md     # 环境与配置说明
        ├── mcp-tools.md       # 工具参数 / 返回 / 错误码
        └── troubleshooting.md # 排障手册
```

## 配置

采集行为由 `mcp_server/wechat_runtime.py` 的 `GlobalConfig` 控制：

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `OFFICIAL_ACCOUNT_TYPE_MAP` | 18 条映射 | 公众号名称 → 账号类型，作为主页窗口 `title` 的唯一来源 |
| `load_delay` | `2.0` | 所有等待与控件超时的基数 |
| `language` | 自动检测，回落简体中文 | 决定搜索框 / 侧栏 / 关闭按钮的控件标题 |
| `Version` | 注册表读取 | 环境校验据此匹配 4.1.8.101 |
| `is_maximize` / `close_weixin` | `False` / `False` | 窗口行为 |
| `window_size` | `(1000, 1000)` | 主窗口尺寸 |

新增公众号时，编辑 `OFFICIAL_ACCOUNT_TYPE_MAP` 或调用 `GlobalConfig.register_official_account(name, "公众号" / "服务号")`。主页窗口按精确标题定位，请勿改为模糊匹配。

## 设计要点

- **环境门控**：`get_article_links` 先执行 `check_environment`，不满足条件直接返回结构化错误。
- **版本强绑定**：4.1.8.101 的 `mmui::*` 控件树、`auto_id` 与菜单层级决定了定位方式，升级微信需重新适配。
- **不校验的使用前提**：讲述人、UIA 控件树可见性、账号订阅状态只在使用文档中提示。
- **失败不重试**：UI 自动化异常一律结束任务并反馈，是否重跑由用户决定。
- **不造数据**：任何字段获取失败都显式写入 `error`。
- **日志走 stderr**：MCP stdio 的 stdout 只承载协议报文。

完整工具契约见 [`wechat-article-fetcher/references/mcp-tools.md`](wechat-article-fetcher/references/mcp-tools.md)，环境与配置见 [`environment.md`](wechat-article-fetcher/references/environment.md)，常见问题见 [`troubleshooting.md`](wechat-article-fetcher/references/troubleshooting.md)。

## 合规与许可

- 请遵守微信使用条款，控制采集频率，仅处理有权访问的内容。
- 本项目采用 **GNU Lesser General Public License v2.1**，详见 [LICENSE](LICENSE)；第三方归属见 [NOTICE](NOTICE)。
