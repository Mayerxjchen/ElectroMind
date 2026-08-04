"""输出层少量 ANSI 色（仅 TTY 且未禁色时使用）。"""

from __future__ import annotations

GREEN = "\033[32m"
RESET = "\033[0m"


def result(text: str) -> str:
    return f"{GREEN}{text}{RESET}"
