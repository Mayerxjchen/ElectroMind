# Wire demo（本地浏览器 UI）

语言：四川话 | [English](/wire-demo) | [普通话](/zh/wire-demo) | [日本語](/ja/wire-demo)

全栈例子：**FastAPI** 摆聊天页，浏览器吃 **`Agent.arun_wire()`** 的 `application/x-ndjson` 流。

::: tip 在线文档站代替不了本地 demo
GitHub Pages 只托管静态文档。要体验流式对话，本地把服务扯起来。
:::

## 跑起来

```bash
git clone https://github.com/SyncLionPaw/pagent.git
cd pagent
export DEEPSEEK_API_KEY="your-key"

uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

浏览器开 **http://127.0.0.1:8765**

## 停起

- **服务：** 终端里 `Ctrl+C`
- **生成中：** 点界面上的 **停止**（把 HTTP 请求掐了）

## 演示些啥子

- 聊天气泡、工具卡片、可折叠脑壳转区
- 右边抽屉看原始 Wire NDJSON 行
- 跟 [Wire 协议](./wire) 一套，莫得另一套消息系统

源码：[examples/wire_demo/](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_demo)
