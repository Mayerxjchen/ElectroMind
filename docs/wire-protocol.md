# Wire 协议（内部）

Wire 是 **Desktop 与本地 Agent 子进程之间的内部传输层**——不承诺对外长期兼容，
仅供 `editors/desktop` 使用。

## 启动

```bash
electromind --wire
# stdin  → JSON-RPC 命令（NDJSON，每行一个命令对象）
# stdout → JSON-RPC 事件（NDJSON，每行一个事件对象）
```

Desktop 以 `--wire --execution-mode local` 启动子进程，经 stdio 通信。

## 命令

```text
reset / resume / cancel / user / input/send
list_threads / thread_meta / thread/snapshot / delete_thread / history
skills / skills/list / skills/get / skills/reload / skills/changed
skills/install / skills/update / skills/remove / skills/trust
plan/state / plan/propose / plan/approve / plan/revise / plan/cancel / plan/update-step
artifact/state / artifact/register / artifact/accept / artifact/reject
artifact/complete / artifact/validate
permit / deny / set_provider / get_config / environment_check
sandbox_status / sandbox_tree / commands / client_features
hpc/submissions
```

## 事件

事件携带 `method` + `params`，常见方法：

```text
ThreadList / ThreadState / HistoryReplay / ExecutionState / SkillsState
SlashCommands / ToolResult / Error / RunBegin / RunEnd / Approval*
```

协议 v2 起，事件经 EventBroker 封装（per-thread `seq`、`event_id`、快照缓冲），
并带 `protocol_version` 与 `timestamp`。

## 安全边界

- Desktop 主进程与 preload 各维护一份命令白名单（`ALLOWED_WIRE_COMMANDS`）——
  渲染进程只能发送白名单命令，防御纵深
- IPC 参数经 schema 校验（`editors/desktop/src/preload/ipc-schema.ts`）
- Renderer 启用 `contextIsolation` + `sandbox`；严格 CSP（`script-src 'self'`）

## HTTP（experimental，暂停开发）

```bash
electromind --http --host 127.0.0.1 --port 8848
# POST /command  → 发送命令
# GET  /events   → SSE 事件流
```

不承诺兼容，新功能不要求适配。
