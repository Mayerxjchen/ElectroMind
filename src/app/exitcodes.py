"""CLI 退出码契约（冻结，见 docs/superpowers/specs/2026-08-01-cli-professional-refactor.md）。

stdout 只出最终结果或结构化事件；stderr 出进度、警告、诊断与 Debug 日志。
"""

EXIT_OK = 0
# CLI 参数或配置错误（argparse 自身错误也是 2）
EXIT_CLI = 2
# Provider / 认证错误（缺 API Key、连接失败、鉴权失败）
EXIT_PROVIDER = 3
# 权限拒绝（工具/命令被权限引擎拒绝，或非 TTY 下无法审批）
EXIT_PERMISSION = 4
# Tool / 执行失败（Agent 执行出错、工具返回失败且未恢复）
EXIT_EXECUTION = 5
# 用户取消（Ctrl+C 中断）
EXIT_CANCELLED = 6
# Service / 协议错误（wire/http 等协议层失败）
EXIT_SERVICE = 7
# 结果状态未知或中断（Run 被强制打断，状态不可判定）
EXIT_UNKNOWN = 8
