# Wire demo（本地浏览器 UI）

语言：中文 | [English](/wire-demo) | [日本語](/ja/wire-demo) | [四川话](/sc/wire-demo)

全栈示例：**FastAPI** 提供聊天页，浏览器消费 **`Agent.arun_wire()`** 的 `application/x-ndjson` 流。

::: tip 在线文档站不能代替本地 demo
GitHub Pages 只托管静态文档。要体验流式对话，请在本地启动服务。
:::

## 运行

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
