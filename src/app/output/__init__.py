"""机器输出层：text / json / stream-json 三种输出格式。

契约（见 docs/superpowers/specs/2026-08-01-cli-professional-refactor.md）：

- stdout 只出最终结果或结构化事件（可被程序稳定解析）
- stderr 出进度、警告、诊断与 Debug 日志
- 非 TTY：无 ANSI、无动画、无交互审批
"""
