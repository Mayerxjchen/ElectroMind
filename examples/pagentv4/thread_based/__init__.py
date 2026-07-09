"""Thread-based Runner 示例集。

先按能力选 Runner：

- ChatRunner：只需要 conversation 持久化，不需要 sandbox。
- CodeRunner：需要 sandbox，能读写文件、执行命令，并自动注入 sandbox tools。
- Runner：完整 runtime 入口，适合需要 thread 生命周期、sandbox、hooks、inbound 等能力。

喜欢把可运行整体称作 Agent 的用户，也可以使用等价别名：
ChatAgent = ChatRunner，CodeAgent = CodeRunner，ThreadAgent = Runner。

示例顺序：

- conversation_only   最小 conversation 持久化示例
- tool_call           ChatRunner + 自定义工具 + 完整事件流
- code_runner         CodeRunner + sandbox 文件/命令能力
- full_thread         Runner.create() 打开完整 thread 生命周期

`runner.run()` 默认返回 event 流；只想打印模型文本时传 `return_type="text"`。
用完 runner 后调用 `await runner.close()`，让 sandbox / store 等资源按顺序关闭；
thread 目录和 conversation 数据会保留在磁盘上。
"""
