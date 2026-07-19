# 桌面端

语言：中文 | [English](/desktop)

**pagent Desktop** 是在电脑上使用的 AI 助手工作台：左侧看历史会话，中间对话，右侧看沙箱里的文件和生成物（网页、PDF 等）。

本文面向**普通用户**——下载安装、配置 Key、创建第一个任务、日常怎么用。若要改桌面端代码，请看仓库里的 [开发者 README](https://github.com/SyncLionPaw/pagent/blob/main/editors/desktop/README.md)。

## 安装

### 1. 安装后端（必做）

桌面端需要本机有 `pagent` 命令（和 VS Code 插件一样）：

```bash
uv tool install pagent
```

若之后提示无法启动后端，确认终端里能运行 `pagent`，或重新执行上面的安装命令。

还没有 `uv`？可先按 [安装指南](./guide/install) 装好 Python 环境，再执行 `uv tool install pagent`。

### 2. 下载桌面应用

在 [pagent GitHub Releases](https://github.com/SyncLionPaw/pagent/releases) 下载桌面端：

- **macOS（Apple 芯片）** — `pagent-Desktop-<版本号>-arm64.zip`，或资源里的 `pagent Desktop.app`。

解压后把 **pagent Desktop** 拖进「应用程序」文件夹。

::: tip macOS 首次打开
安装包尚未公证。若系统拦截，请 **右键应用 → 打开 → 仍要打开**，确认一次后以后可双击正常启动。
:::

**Windows / Linux** 安装包暂未发布，可先用 [VS Code 插件](./vscode) 或终端命令 `pagent`。

## 发第一条消息前：配置 API Key

**桌面端首次打开不会弹出配置向导**（VS Code 插件会引导填写）。

请先配置模型 Key，任选一种方式：

**环境变量：**

```bash
export DEEPSEEK_API_KEY=sk-...
```

**配置文件（推荐）：** 新建 `~/.pagent/pagent.toml`：

```toml
[provider]
api_key = "sk-..."
model = "deepseek-v4-flash"
```

更多模型说明见 [模型与 API Key](./guide/providers)。

若未配置，发送消息后会出现错误提示。标题栏 **设置**（齿轮）可查看是否已有配置文件——该页面**只读**，不能在应用里直接保存修改。

## 第一次打开

1. 启动 **pagent Desktop**。
2. 应用会自动拉起后端，并尝试**恢复当前项目下最近一条会话**。
3. 想从新对话开始，点侧栏 **新建任务**。

### 新建任务

在 **新建任务** 对话框里：

| 项 | 建议 |
| --- | --- |
| **沙箱类型** | 选 **local**（本机运行，默认即可，无需 Docker） |
| **项目目录** | 选要让助手操作的那个文件夹 |

点 **创建会话**，在底部输入框打字，**Enter** 发送（**Shift+Enter** 换行）。

## 界面说明

```text
┌─────────────┬──────────────────────┬─────────────┐
│  会话列表   │        对话          │ 文件与生成物 │
└─────────────┴──────────────────────┴─────────────┘
```

- **左侧** — 历史会话，点一条可继续聊。
- **中间** — 对话内容、工具步骤、输入框。
- **右侧** — 沙箱目录、项目文件、生成物预览、日志。

可拖动中间分隔条调宽度。**⌘K** 或标题栏 **?** 查看快捷键。

## 输入框

| 按钮 | 作用 |
| --- | --- |
| **发送 / 停止** | 发送消息；运行中变为 **停止**，可取消当前任务 |
| **闪电（YOLO）** | 自动批准工具调用——仅在完全信任当前任务时开启 |
| **圆环** | 上下文用量的大致比例 |
| **@** | 把项目或沙箱里的文件路径插入到消息里 |

## 设置与帮助

| 入口 | 作用 |
| --- | --- |
| **齿轮** | 查看 `~/.pagent/pagent.toml`（密钥显示为「已配置」） |
| **书本图标** | 在浏览器打开本文档站 |
| **用户菜单 → 扫码看文档** | 手机扫码阅读文档 |

改模型或高级沙箱选项，请用文本编辑器改 `pagent.toml`。

## 文件存在哪

```text
~/.pagent/
├── pagent.toml       # API Key 与模型
├── threads/          # 会话记录
└── skills/           # 可选本地 skills

<你的项目>/
└── artifacts/        # 助手生成的文件（网页等）
```

不要把含真实 Key 的 `pagent.toml` 发给别人或提交到 Git。

## 遇到问题

| 现象 | 可以试试 |
| --- | --- |
| 后端 / Bridge 起不来 | 执行 `uv tool install pagent`；看右侧日志 |
| 发送后报错 | 检查 `pagent.toml` 或 `DEEPSEEK_API_KEY` |
| 设置里写「还没有配置文件」 | 按上文创建 `~/.pagent/pagent.toml` |
| 工具一直显示「运行中」 | 点 **停止** 或重新发消息；新版本重开会自动修复 |

## 延伸阅读

- [VS Code 插件](./vscode) — 在 VS Code 里用，首次有 Key 引导
- [安装指南](./guide/install) — 还没有 `uv` 时从这里开始
