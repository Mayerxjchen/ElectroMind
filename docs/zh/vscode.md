# VS Code 插件

语言：中文 | [English](/vscode)

pagent VS Code 插件会在 VS Code 里提供一个聊天面板。你安装插件后，可以直接在侧边栏和 pagent 对话，让它在当前工作区里执行文件读取、命令运行、工具调用和会话恢复等操作。

## 安装

先从 [pagent GitHub Releases](https://github.com/SyncLionPaw/pagent/releases) 下载 VS Code 插件包：

下载文件名以 `.vsix` 结尾的插件文件。

在 VS Code 里安装：

1. 打开 VS Code 左侧 **Extensions** 面板。
2. 点击 Extensions 面板右上角的 `...` 菜单。
3. 选择 **Install from VSIX...**。
4. 选择刚下载的 `.vsix` 文件。
5. 安装完成后，重新加载窗口；左侧活动栏会出现 pagent 图标。

也可以打开命令面板，运行：

```text
Extensions: Install from VSIX...
```

插件还需要本机能运行 `pagent` 命令。先安装 CLI：

```bash
uv tool install pagent
```

如果 VS Code 提示找不到 `pagent`，可以在设置里把 `pagent.command` 改成 `pagent` 可执行文件的绝对路径。

## 第一次打开

点击左侧 pagent 图标，打开 **Chat**。

如果还没有配置过 API Key，插件会弹出输入框，引导你填写：

- API Key
- 模型名称，默认是 `deepseek-v4-flash`
- Base URL，可留空

保存后，插件会写入 `pagent.toml`，然后即可开始对话。

## 插件会创建哪些文件

插件会使用一个 pagent home 目录保存配置、会话和本地 skills。

如果当前工作区已经有 `.pagent/` 目录，插件会使用：

```text
<workspace>/.pagent/
```

如果当前工作区没有 `.pagent/`，插件会使用：

```text
~/.pagent/
```

如果你希望某个项目使用独立配置和独立会话历史，可以在项目根目录手动创建：

```bash
mkdir .pagent
```

之后插件会使用这个项目下的 `.pagent/`。

常见文件如下：

```text
.pagent/
├── pagent.toml          # 配置文件，保存模型、API Key、sandbox 等配置
├── threads/             # 会话历史
│   └── thread-.../
│       ├── metainfo.json
│       └── messages.jsonl
└── skills/              # 可选，本地 skills 目录
```

这些文件的含义：

| 路径 | 保存内容 |
| --- | --- |
| `pagent.toml` | 模型、API Key、Base URL、运行模式、SSH、审批模式等配置 |
| `threads/` | 会话历史，每个 thread 是一次可恢复的对话 |
| `metainfo.json` | thread 的标题、创建时间、更新时间、消息数量 |
| `messages.jsonl` | 该 thread 的消息内容 |
| `skills/` | 可选，本地 skills |

没有消息的空 thread 会在后端正常退出时自动清理。

如果 `.pagent/` 放在项目目录里，并且项目会提交到 Git，请避免提交包含 API Key 的 `pagent.toml`。

## 配置文件

插件第一次配置 API Key 后，会写入 `pagent.toml`。也可以手动编辑：

```toml
[provider]
api_key = "sk-..."
model = "deepseek-v4-flash"
# base_url = "https://..."

[sandbox]
backend = "local" # local | docker | podman | ssh
command_policy = "workdir"

[ssh]
config_path = "~/.ssh/config"
host = "my-remote"
workdir = "~/pagent"

[permission]
mode = "prompt" # prompt | auto
```

也可以通过环境变量提供 API Key：

```bash
export DEEPSEEK_API_KEY=sk-...
```

## 怎么使用

打开 Chat 后，直接在底部输入框输入问题，回车发送。`Shift+Enter` 换行。

插件会流式显示回复。模型的思考过程会显示在可折叠的 `thinking` 面板里。工具调用会显示成工具卡片，你可以展开查看细节。

## 标题栏按钮

Chat 视图右上角有三个按钮：

| 按钮 | 作用 |
| --- | --- |
| 在编辑器区打开 | 打开一个更宽的聊天面板 |
| 恢复会话 | 从历史会话中选择一个继续 |
| 新会话 | 开始一个新的空会话 |

## 输入框按钮

输入框下方有几个按钮：

| 按钮 | 作用 |
| --- | --- |
| `/` | 打开斜杠命令菜单 |
| 运行模式 | 选择工具运行在哪里 |
| 盖章 | 开启或关闭 YOLO 模式 |
| 发送 | 发送当前输入 |

YOLO 模式会自动批准危险工具调用，例如运行命令。只在你信任当前工作区和当前请求时开启。

## 运行模式

运行模式决定 pagent 的工具在哪里执行。

| 模式 | 含义 |
| --- | --- |
| Local | 在当前电脑上执行工具 |
| Docker | 在 Docker 容器里执行工具 |
| Podman | 在 Podman 容器里执行工具 |
| SSH | 在远程机器上执行工具 |

Docker 和 Podman 选项只有在 VS Code 所在环境能找到对应命令时才显示。

SSH 模式会读取 `~/.ssh/config`，展示里面明确写出的 `Host` 别名。`Host *` 这类通配项不会出现在菜单里。

## 斜杠命令

点击 `/` 按钮，或在输入框里输入 `/`，可以打开命令菜单。

当前支持：

| 命令 | 作用 |
| --- | --- |
| `/help` | 查看可用命令 |
| `/skills` | 查看已加载的 skills |
| `/history` | 查看会话信息 |
| `/pwd` | 查看当前 pagent home / 工作区上下文 |
| `/ls` | 列出当前上下文中的文件 |

斜杠命令不会触发模型对话，也不会写入会话历史。

## 工具审批

默认情况下，危险工具会先暂停，等待你批准。你会在工具卡片里看到批准和拒绝按钮。

如果开启 YOLO 模式，审批会自动通过。也可以在配置里写：

```toml
[permission]
mode = "auto"
```

## 常见问题

**安装后左侧没有 pagent 图标。**

确认 `.vsix` 已安装成功，并重新加载 VS Code 窗口。

**提示找不到 `pagent`。**

先执行 `uv tool install pagent`。如果仍然找不到，在 VS Code 设置里修改 `pagent.command`。

**Docker 或 Podman 没有出现在菜单里。**

当前 VS Code 环境里没有对应 CLI，或 CLI 不在 PATH 里。

**SSH Host 没有出现。**

检查 `pagent.sshConfigPath` 指向的文件，并确认里面有明确的 `Host xxx` 配置。

**会话历史在哪里。**

在当前 pagent home 的 `threads/` 目录下。项目模式通常是 `<workspace>/.pagent/threads/`，否则是 `~/.pagent/threads/`。
