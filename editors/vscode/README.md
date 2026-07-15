# pagent VS Code 插件

把 pagent Agent 接进 VS Code 的插件，按 20 课渐进式实现，最终对齐 Cursor Agent 模式。
课程大纲见 [ROADMAP.md](./ROADMAP.md)。

本目录是 monorepo 的一部分，走独立的 npm 工具链，不进 PyPI 发布包
（`pyproject.toml` 的 `module-name` 只打 `src/` 下的 Python 包）。

## 开发

需要 Node 18+（本机用 nvm 管理，node v22）。

```bash
cd editors/vscode
npm install      # 安装 @types/vscode / esbuild / typescript
npm run compile  # 打包宿主 bundle 到 dist/
npm run check    # 只做类型检查
```

在 VS Code 里打开本目录，按 **F5** 启动“扩展开发宿主”窗口，插件在其中加载。

## 当前进度

阶段 A —— 骨架与通信：

- 第 1 课：最小可激活插件。命令面板运行 `pagent: Hello` 会弹出激活确认通知。
- 第 2 课：活动栏出现 pagent 图标，展开是一个侧边栏 Webview 视图（占位内容 + 视图脚本）。
- 第 3 课：视图有输入框，回车把文本经 postMessage 回传宿主，宿主回显到视图与输出通道。
- 第 4 课：宿主 spawn `pagent --wire` 子进程，把用户输入转成 JSON 命令喂进 stdin，
  子进程 stdout 事件行 / stderr 日志打进“输出”面板的 pagent 通道。
- 第 5 课：宿主把 stdout 逐行按 JSON-RPC notification 解析成 `{method, params}` 事件，
  在输出通道里显示结构化事件。

Python 侧新增 `pagent --wire`（[src/app/wire.py](../../src/app/wire.py)）：stdin 收 JSON 命令
（`{"cmd":"user","text":...}`），stdout 出 Wire 事件 NDJSON。

阶段 B —— 聊天体验：

- 第 6 课：宿主把解析后的事件转发给视图；视图 `ChatRenderer` 把 `TextDelta` 累积进
  assistant 气泡、`RunEnd` 时定稿，用户输入本地上屏 user 气泡。气泡样式走
  `media/style.css` 的 `--vscode-*` 主题变量，CSP 用 `webview.cspSource` 放行样式。
- 第 7 课：打字机效果。`TextDelta` 先入 pending 队列，`requestAnimationFrame` 每帧
  吐几个字符（pending 越长吐越快），整段回复平滑滚出；`RunEnd` 时补齐余量并收尾。
- 第 8 课：`ReasoningDelta` 累积进正文上方的可折叠“思考”面板（`<details>`，默认展开），
  弱化配色与正文区分，参照 trace 视图的 thinking-panel。
- 第 9 课：主题同步。颜色靠 `--vscode-*` 变量随主题自动切换；宿主用
  `onDidChangeActiveColorTheme` 把主题类别（亮/暗/高对比度）推给视图写进 `<body data-theme>`，
  高对比度主题下给气泡补明显描边。
- 第 10 课：多轮对话与会话恢复。多轮天然保持（同一子进程/thread 累积历史）。会话级操作
  收进视图原生标题栏（与「PAGENT: CHAT」同一行）：「新会话」发 `{"cmd":"reset"}`，Python 侧
  关旧 runner、开一个干净 `thread-<时间戳>`；「恢复会话」由宿主读工作区 `.pagent/threads/`
  目录名列出已有 thread，`showQuickPick` 选中后发 `{"cmd":"resume","thread_id":...}`，Python 侧
  切到该 thread。reset/resume 后端都回发一条 `HistoryReplay` 控制事件（`params.messages` 是规整
  后的历史数组，空数组表示新会话），前端据此清屏并逐条重建气泡/思考面板/工具卡。

阶段 C —— 工具与上下文：

- 第 11 课：工具卡片。`ToolCallBegin` 建一张折叠卡（工具名 + 参数，标“运行中”），
  `ToolResult` 按 `tool_call_id` 回填结果并按 `ok`/`fail` 配色。卡片插在文字流中间时先封口
  当前 assistant 气泡，保证 DOM 顺序（前文 → 工具卡 → 后文）。
- 第 12 课：工具审批。危险工具（`run_command` / `copy_from_host`）执行前挂起，等用户拍板。
  Python 侧 `wire.py` 改并发模型：一轮 Agent 作为后台 task 跑，主循环持续读 stdin，
  `ToolCallBegin` 后补发 `PermitRequest` 控制事件；前端在对应工具卡片里展开“批准/拒绝”条，
  点击经 `permit` / `deny` 入站命令回后端，`runner.inbound` 解开审批阻塞后工具才继续执行。

UI 打磨（贯穿阶段 B/C，非独立课）：

- 运行态占位：发出消息到首个增量到达之间，assistant 位显示三点闪动“思考中”。
- 智能滚动：流式内容仅在贴近底部时自动跟随，上翻历史不被拽回。
- 多行输入：`textarea` 自适应高度，回车发送 / Shift+Enter 换行，独立发送按钮。
- 运行模式：输入框左下角显示 `LOCAL` / `SSH`，点击后保存到工作区设置
  `pagent.sandboxMode` 并重启 Wire 后端。SSH 连接读取项目 `pagent.toml` 的
  `[ssh] host/config_path/workdir`。
- 布局稳定：聊天区预留滚动条槽位，长回复触发滚动条时不改变消息区域宽度。
- 会话加载：选择历史线程后显示模拟 user/assistant 布局的骨架屏，历史完整返回后淡出并
  切换为实际内容；加载期间锁定输入，超时或后端退出时恢复可操作状态并提示用户。
- 空状态与角色标签：首开/新会话显示引导文案，每条消息标 you/pagent。
- 图标：接入 `@vscode/codicons`（官方图标字体），发送按钮用图标；由 esbuild
  把 `codicon.css` + `codicon.ttf` 拷进 `dist/`，CSP 加 `font-src` 放行字体。标题栏的
  「新会话」/「恢复会话」按钮走 VS Code 原生渲染，图标用 `$(add)` / `$(history)`。
  思考面板用内联大脑 SVG 图标（Lucide brain，随主题走），工具卡用扳手图标 `codicon-wrench`。
- 输入框：Claude Code 风格单容器——textarea 与发送按钮同处一个圆角描边框内，整体聚焦时高亮描边。
  输入框右下角并列斜杠按钮与发送按钮；斜杠按钮弱化透明底、发送按钮用主色块。
- 折叠行摘要：思考面板与工具卡流式期间展开可见；本轮结束（`RunEnd`）后折叠，
  折叠行内联显示一段单行摘要（超长省略号），不额外占竖向空间。历史回放的思考/工具默认折叠。
- 工具卡状态图标：状态文字（运行中/完成/失败/待审批/已拒绝）统一用 codicon 表达
  （`codicon-loading` 自旋、`codicon-pass-filled` 绿、`codicon-error` 红、`codicon-question`、`codicon-circle-slash`），
  `title` 属性保留中文语义供悬停/无障碍读出。
- slash 命令：输入框旁的斜杠按钮弹出命令菜单，清单由后端 `wire.py` 的 `SlashCommands`
  事件下发（`help`/`skills`/`history`/`pwd`/`ls`），前端只负责展示，避免前后端漂移。以 `/`
  开头的输入被后端识别为 slash 命令（不跑 Agent、不进对话历史），复用 REPL 只读能力，
  结果经 `SlashResult` 事件回前端渲染成折叠命令卡。菜单支持 `/` 后文本过滤、上下键导航、
  回车/点击选中。
- Markdown 渲染：assistant 正文在流式期间继续保留打字机节奏，同时按约 48ms 批量用
  `marked` + `DOMPurify` 增量渲染当前缓冲区（含 GFM 表格），`RunEnd` 和工具卡插入前强制 flush；
  历史回放复用同一套解析与消毒逻辑。user 输入保持纯文本。气泡统一小圆角（6px）与内边距/字体；
  表格在窄侧栏下横向滚动，代码块/列表/引用等元素走 `--vscode-*` 主题变量。
- 会话标题：每个 thread 目录多写一个 `metainfo.json`（`title` 取首条用户消息截断、`created_at`/
  `updated_at`/`message_count`）。`thread-<时间戳>` 是内部管理编号，「恢复会话」列表用 `title`
  面向用户展示，thread id 降级为副标题。
- 编辑器区面板：侧栏视图受工作台约束无法设默认宽度或强制放右侧。标题栏「在编辑器区打开」
  （`pagent.chat.openInEditor`）用 `createWebviewPanel` + `ViewColumn.Beside` 在编辑器区开一个
  更宽、可由用户拖到右侧的聊天面板，与侧栏共用同一子进程，事件广播到两侧。

## 分层

- `src/extension.ts` + `src/host/`：宿主层，跑在 Node，能用 vscode API 和子进程。
- `src/webview/`：视图层，跑在 Webview 沙箱，只能 `postMessage`（从第 2 课起启用）。

两层只走结构化消息，互不直接引用对方对象。
