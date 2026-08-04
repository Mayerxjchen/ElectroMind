# ElectroMind CLI 改造 Goal Condition

目标：将 ElectroMind CLI 改造成接近 Claude Code 使用体验的专业 Agent CLI。CLI 必须支持交互、自动化、会话恢复、运行中输入、权限审批、结构化输出和稳定终端渲染，并统一接入 Harness，不自行维护另一套运行状态。

## 一、启动与命令入口

- [x] 在项目目录执行 `electromind` 即可启动交互模式。
- [x] `electromind "任务描述"` 可携带初始任务进入交互模式。
- [x] `electromind -p "任务描述"` 可非交互执行并在完成后退出。
- [x] 支持 stdin：`cat file | electromind -p "分析内容"`。
- [x] `electromind -c` 可继续当前项目最近一次会话。
- [x] `electromind -r THREAD_ID` 可恢复指定会话。
- [x] `electromind --resume` 可打开交互式会话选择器。
- [x] `--help`、`--version` 和参数错误输出清晰且稳定。

## 二、运行选项

- [x] Task Mode、Execution Target、Permission Mode 相互独立。
- [x] 支持 `--mode ask|plan|run`。
- [x] 支持 `--target sandbox|local|ssh`。
- [x] 支持 `--permission-mode prompt|auto-safe`。
- [x] 默认 target 为 sandbox，默认 permission 为 prompt。
- [x] Local 必须显式选择并展示风险。
- [x] Sandbox 或 SSH 失败时不得自动回退 Local。
- [x] Run 启动后，model、mode、target、permission、project 和 tools 冻结进 RunSnapshot（EmbeddedAgentClient 在 Run 启动时冻结）。

## 三、交互体验

- [x] 输入框在模型生成、工具执行和等待审批期间始终可用。
- [x] Enter 发送，Shift+Enter 或 Alt+Enter 换行（Alt+Enter 生效；Shift+Enter 依赖终端 CSI-u）。
- [x] Esc 取消当前生成、关闭弹层或取消 Run。
- [x] Ctrl+C 第一次取消当前 Run，空闲时清空输入，再次触发退出。
- [x] Ctrl+R 可搜索输入历史。
- [x] `/` 打开命令与 Skill 补全。
- [x] `@` 提供项目文件路径补全。
- [x] `!command` 在当前 Execution Target 中执行，并经过 PermissionEngine。
- [x] 运行中输入可选择 immediate（Enter=steer）或 enqueue（Tab）。
- [x] 每条输入最终显示 accepted、applied、queued、deferred 或 rejected（input/state 事件驱动完整状态机）。
- [x] 禁止用户输入静默丢失。

## 四、终端渲染

- [x] 启动界面使用紧凑信息头，不显示大型 ASCII Logo（TUI；`--about` 保留 Logo）。
- [x] User、Assistant、Activity、Tool、Approval、Error 和 System Notice 有明确视觉区分。
- [x] Assistant 回复支持 Markdown、代码块、列表、引用和简单表格（基础 Markdown-lite）。
- [x] Raw reasoning 默认不显示，只展示公开 Activity。
- [x] Tool Card 显示工具名、目标环境、工作目录、状态、耗时和退出码。
- [x] Tool 输出默认显示摘要，完整日志按需打开（`o` 键；full_output 有 20k 上限）。
- [x] Approval Card 显示命令、Target、Workdir、风险和可用决策。
- [x] 状态栏持续显示 Mode、Target、Permission、Model 和 Run 状态。
- [x] 用户向上滚动后，流式输出不得强制拉回底部。
- [x] 窗口缩放后布局、边框、中英文和长路径不发生错位（prompt_toolkit + 宽度桶缓存）。
- [x] 流式 Delta 使用批处理（~30ms 合并窗口；条目级缓存，5000 条目 0.4ms/帧）。

## 五、输出模式

- [x] 支持 Full-screen TUI。
- [x] 支持 `--inline`，保留终端 scrollback。
- [x] 非 TTY 自动进入 Plain 模式。
- [x] 支持 `--output-format text|json|stream-json`。
- [x] text 模式 stdout 只输出最终结果。
- [x] json 模式输出稳定的单个 JSON 对象。
- [x] stream-json 模式每行输出一个合法事件。
- [x] stderr 只输出进度、警告和诊断。
- [x] 非 TTY 输出不得包含 ANSI、Spinner、动态覆盖或交互审批提示。

## 六、Harness 接入（CLI-4 主体）

- [x] CLI 不直接以 Runner 作为全局状态事实源（EmbeddedAgentClient + ThreadSessionManager 是唯一状态入口）。
- [x] CLI 通过统一 AgentClient 调用 Harness（EmbeddedAgentClient 进程内 + ServiceAgentClient 经 HTTP Service）。
- [x] 所有事件至少包含 thread_id 和 seq（EventBroker 打 envelope）。
- [x] Run 事件包含 run_id，Item 事件包含 item_id。
- [x] Approval 和 Cancel 精确绑定 thread_id、run_id 和对应对象（Manager 校验后原子消费；错误 run 拒绝）。
- [x] CLI 切换 Thread 不关闭旧 Runner，不取消后台 Run（/resume 只切视图）。
- [x] 不同 Thread 的消息、审批、错误和工具事件不会串流（每 Thread 独立视图 + 事件按 thread_id 路由）。
- [x] 重复 event_id 或 seq 不会重复渲染（broker seq 单调；request_id 幂等重放）。
- [x] 断线重连后可通过 Snapshot 或 after_seq 恢复状态（client.events(after_seq) + manager.snapshot）。

## 七、会话与 Slash Command

- [x] 支持 /help、/status、/model、/mode、/target 和 /permissions。
- [x] 支持 /skills、/sessions、/resume、/new 和 /history。
- [x] 支持 /compact、/doctor 和 /exit。
- [x] `electromind service start|status|stop|logs`（常驻 HTTP Service daemon，PID+日志落 home）。
- [x] `electromind completion bash|zsh|fish` 生成真实补全脚本。
- [x] Skill 与内置命令进入同一个 / 补全菜单。
- [x] /resume 切换视图时不得关闭其他 Thread 的 Runner。
- [x] 会话列表显示标题、项目、运行状态和最后更新时间。
- [x] TUI 会话选择器 overlay（/resume 无参；模糊搜索 + ↑↓ Enter Esc，不与 prompt_toolkit 抢终端）。
- [x] /help 打开 Help overlay（命令清单 + 快捷键），Esc 关闭不污染时间线。

## 八、配置与诊断

- [x] 配置优先级为 CLI > Local > Project > User > Built-in（load_settings_sources 分层合并 + 每字段来源）。
- [x] 支持 config get、set、unset、edit、validate 和 sources。
- [x] config sources 能显示每个最终值来自哪个作用域（含 CLI 覆盖与 untrusted 标注）。
- [x] 支持 electromind doctor。
- [x] doctor 至少检查 Provider、模型、配置、Sandbox、Container、SSH、Skills、Service（协议 v2 版本）和日志目录。
- [x] 配置错误提供字段路径、实际值和修复建议（如 `execution.mode: 非法值 'cloud'；应为 'local' | 'sandbox' | 'ssh'`）。
- [x] API Key、SSH 凭据和敏感环境变量不得出现在普通日志或事件中。
- [x] Project 中共享的权限规则第一次启用前必须进行 Workspace Trust（未信任 → 跳过项目 scope，fail-closed；`config trust` / 交互提示）。

## 九、安全与权限

- [x] `!command` 不得绕过 ExecutionManager 和 PermissionEngine。
- [x] Ask、Plan 模式不得通过 CLI 或 Skill 获得写权限。
- [x] auto-safe 只能自动批准后端判定为安全的操作（risk-gated：无删除/提权/写文件的命令自动放行，其余仍审批）。
- [x] 旧 Run 的 Approval 不得作用于新 Run（embedded：按 tool_call_id 绑定；harness：Run 终结即过期）。
- [x] Run 结束或取消后，待审批请求自动失效。
- [x] 相同 request_id 重试不得重复执行副作用（IdempotencyStore + manager receipt_history）。
- [x] --yolo 和 --auto 进入明确弃用周期，不作为推荐接口。

## 十、退出码与错误处理

- [x] 成功返回 0。
- [x] 参数或配置错误返回 2。
- [x] Provider 或认证错误返回 3。
- [x] 权限拒绝返回 4。
- [x] Tool 或执行失败返回 5。
- [x] 用户取消返回 6。
- [x] Service 或协议错误返回 7。
- [x] 中断或未知状态返回 8。
- [x] 默认错误不输出完整 traceback。
- [x] --debug 时才输出开发诊断和 traceback（默认 exit 8 + 单行错误）。

## 十一、性能与兼容性

- [x] 输入发送后 100 ms 内出现本地 accepted 状态（embedded 立即）。
- [x] 流式输出期间输入、滚动和取消保持响应。
- [x] 5000 个 RenderItem 时仍可正常滚动和输入（实测 15000 行 12ms 首渲染 / 0.4ms 缓存渲染）。
- [x] 大日志不作为单个 RenderItem 常驻主时间线（主视图只渲染摘要；full_output 有 20k 上限）。
- [x] 不支持的终端能力自动降级（TERM=dumb/未设置 → inline + 无颜色；非 TTY → Plain；`--inline` 手动降级亦可）。
- [x] 无持续增长的 Task/事件订阅/定时器/渲染缓存泄漏（close() 清空 Runner 与任务；broker/receipt/幂等均有上限；close 清理有测试）。

## 十二、必须通过的端到端场景

- [x] 启动新会话，发送任务，执行 Tool，完成回答。
- [x] Run 期间发送 immediate，输入被安全应用或 deferred。
- [x] Run 期间发送 enqueue，当前 Run 完成后严格 FIFO 执行。
- [x] 等待 Approval 时仍可编辑输入，普通输入不会被误认为审批答案。
- [x] Thread A 运行时切换 Thread B，A 继续后台运行。
- [x] 取消 A 不影响 B。
- [x] 恢复会话后消息、Tool 和审批不重复（embedded：恢复后消息来自磁盘历史）。
- [x] -p + json 可被脚本稳定解析。
- [x] stdin + stream-json 可持续输出合法事件。
- [x] SSH、Sandbox 和 Provider 启动失败均给出明确可恢复错误。

## 分发（CLI-6）

- [x] wheel + sdist（`uv build` 验证通过，`electromind = "app.cli:main"`）。
- [x] 发布脚本：`scripts/release.sh`（构建 + SHA256SUMS + gh release）。
- [x] standalone：`scripts/build-standalone.sh`（PyInstaller，含 tiktoken 数据）。
- [x] 发布流程文档：`RELEASING.md`（uv tool / pipx / standalone 安装、校验与签名、版本兼容承诺）。

## 验收修复记录（2026-08-03 评审后）

| 评审项 | 修复 |
|---|---|
| P0-1 auto-safe 放行危险命令 | 只读白名单（AUTO_SAFE_COMMANDS ~70 个纯检查命令）+ 引号感知元字符扫描；python/curl/chmod/git/sed/awk 一律需审批；`find . -name "*.py"` 仍安全 |
| P0-2 Approval 吞普通输入 | y/n/d 仅在 Composer 为空时生效（approval_key_enabled）；卡片标注「清空输入后按 y/n」 |
| P0-3 输入链路 | 3 个 harness checkpoint 测试复核通过（评审时工作树被并发修改）；TUI send_turn 乐观渲染用户消息（steer 以系统提示呈现） |
| P0-4 Cancel 未绑定 Run | EmbeddedAgentClient / wire cancel / ServiceAgentClient 三重 run_id 校验；迟到 Cancel 拒绝且不触碰新 Run（测试覆盖） |
| 非 TTY/--blocking 旧路径 | run_blocking_repl 重写：经 EmbeddedAgentClient（send_input/事件流/审批绑定），不再直接持有 Runner |
| HTTP 状态模型 | WireHttpSession 文档修正：多 Thread 状态在 wire state["_runners"] + 模块级 ThreadSessionManager，与 CLI 同一 Harness 模型 |
| TUI 无去重 | 按 seq 去重（ThreadView.last_seq），重放/幂等回放不重复渲染 |
| /compact 占位 | 真压缩：保留系统消息 + 最近 12 条，落盘 + TUI 时间线同步清空 |
| 会话表无状态列 | SessionInfo.status（metainfo last_run_status）+ 表格状态列 |
| doctor 缺模型/Service | 模型名称 + ctx 窗口检查；Service PID 存活 + /health 检查 |
| get_cwidth 误用 | 改用 shutil.get_terminal_size；Approval Card 按显示宽度（CJK=2）对齐 |
| 5000 条目无断言 | 时延上限（首渲染 < 2s）+ 缓存上限（条目 × 桶数，重复渲染不增长）断言 |
| -r 不存在退出码 1 | → exit 2（stderr 报错）；交互/REPL 致命路径 → exit 5 |
| stream-json 整读 EOF | 逐行流式消费（线程生产 + 队列），一行一到即处理，不等待 EOF |

## 复验修复记录（2026-08-03 第二轮评审后）

| 复验项 | 修复 |
|---|---|
| P0-1 白名单命令自身可副作用 | `_UNSAFE_ARG_MARKERS` 逐命令危险参数（find: -delete/-exec/-execdir/-ok/-fprint*；sort: -o；xxd: -r）；`env` 移出白名单。复验 5 样例（find -delete / find -exec / sort -o / env python / xxd -r）全部拒绝，只读变体保持安全 |
| P0-2 逐键 `yes...` 吞输入 | 删除全部裸 y/n/d 绑定；审批 = **Enter（空输入）批准 / Esc 取消 Run**；keymap 对 y/n/d 零绑定（测试断言）。逐键输入任何文本都不会触发审批 |
| P0-3 stream-json 整读 stdin | `_resolve_prompt` 对 stream-json **绝不调用 read()**（测试断言 read 未被调用）；run() 缺输入判定改用 `stdin.isatty()`；管道 stdin + stream-json 主路径端到端可执行（两行流式消费） |
| P0-4 attach_client 未挂载 | `attach_client` 同步化（client_holder 立即可用）；blocking /resume 不再关闭旧 client（后台 Run 继续、sink 停用、独立 done）、更新局部 thread_id、退出统一关闭所有 client |
| 质量门 ruff format | 全仓 246 文件 `ruff format --check .` 通过（含 editors/desktop/assets/generate_icons.py） |
| 契约补全 | UserMessageItem 增加 delivery 字段，input/state 经 request_id 回填（applied/queued/deferred/rejected 落到每条输入上）；EmbeddedAgentClient.cancel_run 拒绝无 run_id 的 Cancel（显式绑定是契约） |

## 三轮复验修复记录（2026-08-03）

| 复验项 | 修复 |
|---|---|
| P0-1 输入交付状态未贯通 | client `_emit_input_state` 全程携带 request_id（含幂等重放与检查点 applied——`_message_request` 维护 message_id→request_id）；TUI `_delivery_pending` 保留到终态（queued→applied 链路持续更新同一条输入）；immediate 输入也创建 UserMessageItem。实测 `queued(req-1) → immediate_pending(req-2) → applied(req-2)`，steer 到达 runner |
| P0-2 `top -W` 判为 safe | 移除交互式/写配置工具：`top`、`htop`、`less`（procps top -W 写配置、less 写 ~/.lesshst）；`top -W`/`htop`/`less` 全部拒绝，`more`/`ps`/`grep` 保持安全 |

## 四轮复验修复记录（2026-08-03）

| 复验项 | 修复 |
|---|---|
| P0-1 普通 queued 输入缺 applied 终态 | `start_run` 成功消费队头输入即发 `input/state(applied, 原 request_id)`（`_emit_consumed_applied`）——auto/enqueue 输入链路 `queued → applied` 完整；rejected 输入在 send_input 立即清理关联；`_drain_immediate` 的 applied 发出后 pop `_message_request` |
| P0-2 关联映射无清理路径 | `_message_request` 三处终态清理（消费 applied / 检查点 applied / rejected）；容量回归测试：3 轮 Run 后 3 个 applied（带 request_id）且映射回到 0 |

实测：`queued(req-0) → applied(req-0)`、`queued(req-1/2) → applied(req-1/2)`，`_message_request == {}`。

## 五轮复验修复记录（2026-08-03）

| 复验项 | 修复 |
|---|---|
| P0 Run 异常结束缺 deferred 状态 | `_finish_run` 终态转换前 `take_pending_immediate` → `restore_queued_at_head`（保持下次 Run 消费的 defer 语义）→ 转换（fail/cancel/complete）→ 每条未应用 immediate 发 `input/state(deferred, 原 request_id)` + pop `_message_request`。复现场景实测：`queued → applied → immediate_pending → deferred`，输入回到队首（未丢失），映射回到 0 |

## 最终完成条件

- [x] 交互使用只需 `electromind`。
- [x] 自动化使用 `electromind -p`。
- [x] 恢复使用 `electromind -c` 或 `-r`。
- [x] CLI、Desktop 和 HTTP 复用同一 Harness 协议（同一 JSON-RPC v2 事件形状 + ThreadSessionManager；wire 为既有实现）。
- [x] 用户输入零静默丢失。
- [x] CLI 渲染层不修改 Harness 状态。
- [x] 核心 CLI 不包含 CP2K、LAMMPS、DeepMD 或 Slurm 专属逻辑。
- [x] 旧 REPL 的全局 Runner、直接 Host 执行和 ANSI 字符串拼接路径已移除或隔离为兼容层。
