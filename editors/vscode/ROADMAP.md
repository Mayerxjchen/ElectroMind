# pagent VS Code 插件 —— 20 课渐进式路线

面向读者：想从零把 pagent 接进 VS Code、并最终对齐 Cursor Agent 模式的开发者。

## 设计原则

1. **分层明确**：宿主层（`extension.ts` + `src/host/`，跑在 Node，能碰 VS Code API 和子进程）与
   视图层（`src/webview/`，跑在受限 Webview，只能 `postMessage`）严格分开。两层之间只走
   结构化消息，任何一侧都不直接引用另一侧的对象。
2. **渐进式**：每课只加一点。前一课能跑，后一课在其上叠加，不推倒重来。
3. **VS Code API 就近注释**：凡是调用 `vscode.*` 的地方，都写清楚这个 API 做什么、为什么这样用、
   有什么坑（激活时机、生命周期、Webview 沙箱限制等）。

## 与 pagent 的对接点

插件不重写 Agent。它 `spawn` 一个 Python 子进程跑 pagent，通过 stdio 走 **Wire 协议**
（NDJSON，每行一个 JSON-RPC 2.0 notification：`{"jsonrpc":"2.0","method":"<事件类名>","params":{...}}`）。
事件类型见 `src/pagentv4/core/events.py`，序列化见 `src/pagentv4/adapters/acp.py` 的 `encode_event_line`。

- 出站（Python → 插件）：`RunBegin` / `TurnBegin` / `TextDelta` / `ReasoningDelta` /
  `ToolCallBegin` / `ToolResult` / `TurnResult` / `TurnEnd` / `RunEnd`。
- 入站（插件 → Python）：`user` 跑一轮、`reset` 开新会话，以及后续课程的 `steer` / `cancel` /
  `permit` / `deny` 与工具结果回传。入站不是 Wire 的一部分，由我们在 stdin 上自定义一行一个 JSON 命令。

## 目录结构（最终形态）

```
editors/vscode/
├── package.json          # 扩展清单：命令、视图、激活事件、构建脚本
├── tsconfig.json         # TS 编译配置（宿主 + 视图共用类型检查）
├── esbuild.js            # 把宿主和视图分别打成两个 bundle
├── .vscode/launch.json   # F5 启动“扩展开发宿主”窗口
├── ROADMAP.md            # 本文件
├── media/                # 视图静态资源（CSS，复用 trace 配色）
└── src/
    ├── extension.ts      # 宿主入口：activate/deactivate，注册视图与命令
    ├── host/
    │   ├── wire.ts       # NDJSON 行缓冲 + JSON-RPC notification 解析
    │   ├── agent.ts      # spawn pagent 子进程，桥接 stdout→事件 / 命令→stdin
    │   └── panel.ts      # WebviewViewProvider：托管侧边栏、转发消息
    └── webview/
        ├── main.ts       # 视图入口：收事件渲染、发用户输入
        ├── render.ts     # 把事件流渲染成气泡 / 思考块 / 工具卡片
        └── style.css     # 复用 trace_view 的 --vscode-* 主题变量
```

## 20 课

阶段 A —— 骨架与通信（1-5）

| 课 | 目标 | 主要新增 |
|----|------|---------|
| 01 | 空插件能激活，弹一句 hello | `package.json` + `extension.ts` + esbuild + F5 |
| 02 | 侧边栏出现一个空 Webview 视图 | `WebviewViewProvider` 注册、`views` 贡献点 |
| 03 | 视图里有输入框，回车能把文本回显到宿主日志 | Webview→宿主 `postMessage` 桥、CSP |
| 04 | 宿主 spawn `pagent --wire`，把 stdout 原样打进输出通道 | `child_process.spawn` + Python 侧 `--wire` 入口 |
| 05 | NDJSON 逐行解析成事件对象，打日志 | `host/wire.ts` 行缓冲 + JSON-RPC 校验 |

阶段 B —— 聊天体验（6-10）

| 课 | 目标 | 主要新增 |
|----|------|---------|
| 06 | 用户输入送进子进程，Agent 回复整段显示在视图 | 入站命令行协议 + 事件回传视图 |
| 07 | `TextDelta` 流式打字机效果 | 视图侧增量拼接渲染 |
| 08 | `ReasoningDelta` 折叠“思考”块 | 复用 trace 的 thinking 面板样式 |
| 09 | 主题同步：亮/暗随 VS Code 切换 | `--vscode-*` CSS 变量 + `onDidChangeActiveColorTheme` |
| 10 | 多轮对话与会话保持 | 复用 pagent `thread_id`，视图侧只存映射 |

阶段 C —— 工具与上下文（11-15）

| 课 | 目标 | 主要新增 |
|----|------|---------|
| 11 | `ToolCallBegin` / `ToolResult` 渲染成折叠工具卡片 | 复用 trace 的 tool-card 样式 |
| 12 | 工具审批：危险工具先弹确认再执行 | 入站 `permit` / `deny` + `showInformationMessage` |
| 13 | 停止按钮：运行中可 `cancel` | 入站 `cancel` + 运行态 UI |
| 14 | 把“当前文件 / 选中代码”作为上下文带入 | `window.activeTextEditor` + selection |
| 15 | `@` 提及工作区文件，插进提示 | `workspace.findFiles` + QuickPick |

阶段 D —— 编辑与 Agent 模式（16-20）

| 课 | 目标 | 主要新增 |
|----|------|---------|
| 16 | 宿主侧提供 `read_file` 工具给 Agent 调 | Wire 注册工具 + `workspace.fs.readFile` |
| 17 | 宿主侧 `write_file` / `str_replace`，改动写进内存快照 | `WorkspaceEdit` 暂存 |
| 18 | Inline Diff 审阅：改动逐块 接受/拒绝 | `vscode.diff` + `TextEditorDecoration` |
| 19 | 终端集成：`run_command` 工具 + 输出回传 | `window.createTerminal` / `Pseudoterminal` |
| 20 | Plan 模式：任务分解、步骤状态、可中断 | 计划面板 + 步骤事件渲染 |

## 每课的落地约定

- 每课在提交信息里写清“本课新增了什么、如何验证（F5 后点哪、看到什么）”。
- 每课结束时插件都应能 `npm run compile` 通过并 F5 跑起来。
- 涉及 Python 侧改动（如第 4 课的 `--wire`）时，改动落在 `src/`，插件只调用，不复制逻辑。
