"""语义化颜色令牌 — 颜色只表达语义，状态必须同时带文字或符号。

默认文字  终端默认色     辅助元数据 Dim    运行中动作 Cyan
成功      Green         等待/审批 Yellow  失败/危险 Red
用户消息  Blue/Bold
"""

from __future__ import annotations

CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
RED = "\033[31m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"

# 语义符号：所有状态同时带符号与颜色
SYMBOL_RUNNING = "●"
SYMBOL_OK = "✓"
SYMBOL_WARN = "!"
SYMBOL_FAIL = "×"
SYMBOL_APPROVAL = "?"


def c(text: str, code: str, *, on: bool) -> str:
    return f"{code}{text}{RESET}" if on else text
