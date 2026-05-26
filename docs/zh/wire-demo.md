# Wire demo（本地浏览器 UI）

语言：中文 | [English](/wire-demo) | [日本語](/ja/wire-demo) | [四川话](/sc/wire-demo)

全栈示例：**FastAPI** 提供聊天页，浏览器消费 **`Agent.arun_wire()`** 的 `application/x-ndjson` 流。

::: tip 在线文档站不能代替本地 demo
GitHub Pages 只托管静态文档。要体验流式对话，请在本地启动服务。
:::

## 架构图

### 组件

```mermaid
flowchart TB
  subgraph browser [浏览器 — static/index.html]
    UI[聊天 UI + Wire 抽屉]
    PARSE[按行解析<br/>switch method / params]
    UI --> PARSE
  end

  subgraph server [FastAPI — server.py :8765]
    GET["GET / → index.html"]
    POST["POST /api/chat<br/>{ message }"]
    AG[Agent + Session 小帕]
    TOOL["@tool calculate"]
    WIRE[arun_wire]
    GET --> UI
    POST --> AG
    AG --> TOOL
    AG --> WIRE
  end

  subgraph external [外部]
    DS[(DeepSeek API<br/>/v1/chat/completions)]
  end

  PARSE <-->|fetch 流式<br/>application/x-ndjson| POST
  WIRE -->|NDJSON 行| PARSE
  AG <-->|OpenAI 兼容| DS
```

| 部分 | 文件 | 作用 |
|------|------|------|
| 前端 | `static/index.html` | `fetch("/api/chat")`，逐行解析，渲染气泡 / 工具 / 思考 |
| 后端 | `server.py` | `StreamingResponse`，来自 `agent.arun_wire(message)` |
| 库 | `pagent` | Agent 循环，事件 → Wire（[协议](./wire)） |

每次聊天请求会 **新建** 一个 `Agent`（demo 图简单；正式产品应按用户复用 session）。

### 一次对话的流程

```mermaid
sequenceDiagram
  autonumber
  participant User as 用户
  participant UI as index.html
  participant API as FastAPI
  participant Agent as Agent.arun_wire
  participant LLM as DeepSeek

  User->>UI: 输入并发送
  UI->>API: POST /api/chat { message }
  API->>Agent: arun_wire(message)
  Agent-->>UI: RunBegin
  loop 轮次 / 流式
    Agent->>LLM: chat completions
    LLM-->>Agent: 增量
    Agent-->>UI: TextDelta / ReasoningDelta …
    opt 工具调用
      Agent-->>UI: ToolCallBegin
      Note over Agent: calculate()
      Agent-->>UI: ToolResult
    end
    Agent-->>UI: StepEnd, TurnEnd …
  end
  Agent-->>UI: RunEnd
  UI->>User: 气泡 + 抽屉原始行

  Note over User,UI: 停止 → AbortController<br/>中断 fetch（非 Wire 入站）
```

### 停止生成

```mermaid
flowchart LR
  STOP[UI: 停止] --> ABORT[AbortController.abort]
  ABORT --> HTTP[关闭 HTTP 连接]
  HTTP --> SR[StreamingResponse 结束]
  SR --> AGENT[Agent 生成器停止]
```

Wire **没有** 取消类 `method` — 停止靠断开 HTTP。工具审批本 demo 也不做。

## 运行

示例使用 `uv run`。不了解 **uv** 可看 [官方文档](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/SyncLionPaw/pagent.git
cd pagent
export DEEPSEEK_API_KEY="your-key"

uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

浏览器打开 **http://127.0.0.1:8765**

## 停止

- **服务：** 终端里 `Ctrl+C`
- **生成中：** 点击界面上的 **停止**（中断 HTTP 请求）

## 演示内容

- 聊天气泡、工具卡片、可折叠思考区
- 右侧抽屉查看原始 Wire NDJSON 行
- 与 [Wire 协议](./wire) 相同，不是另一套消息系统

源码：[examples/wire_demo/](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_demo)
