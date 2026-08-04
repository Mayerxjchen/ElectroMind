"""终端能力探测（R6）：不支持的能力自动降级。

- 非 TTY → plain（不进入任何 TUI 路径）
- TERM=dumb / 未设置 → 无 full-screen、无颜色
- TERM 明确（xterm*/screen/tmux/linux/...）→ full-screen 可用
- COLORTERM 或 TERM 含 color → 颜色可用
"""

from __future__ import annotations

import os
import sys

# TERM 明确不支持 full-screen 的值
_NO_FULLSCREEN_TERMS = {"dumb", ""}
# 明确支持颜色的信号
_COLOR_HINTS = ("truecolor", "24bit", "256color")


def _term() -> str:
    return (os.environ.get("TERM") or "").strip()


def _colorterm() -> str:
    return (os.environ.get("COLORTERM") or "").strip().lower()


def color_supported(*, explicit: bool | None = None) -> bool:
    """颜色能力：显式参数优先，其次按终端探测。

    COLORTERM 明确（truecolor/24bit/256color）优先于 TERM 判定；
    TERM=dumb 且无 COLORTERM → 无颜色；其余默认支持 ANSI。
    """
    if explicit is not None:
        return explicit
    if not sys.stdout.isatty():
        return False
    if _colorterm() in _COLOR_HINTS:
        return True
    term = _term()
    if term in _NO_FULLSCREEN_TERMS:
        return False
    return True  # 现代终端默认支持 ANSI 颜色


def fullscreen_supported() -> bool:
    """alternate screen 能力：TERM 明确时可用；dumb/未设置 → 降级 inline。"""
    if not sys.stdout.isatty():
        return False
    term = _term()
    if term in _NO_FULLSCREEN_TERMS:
        return False
    return True


def unicode_supported() -> bool:
    """CJK/符号符号能力：LANG 含 UTF-8 或未设置时默认可用。"""
    lang = (os.environ.get("LANG") or "").upper()
    if not lang:
        return True
    return "UTF-8" in lang or "UTF8" in lang


def terminal_profile() -> dict:
    """汇总能力画像（供启动路径做降级决策）。"""
    return {
        "tty": sys.stdout.isatty(),
        "fullscreen": fullscreen_supported(),
        "color": color_supported(),
        "unicode": unicode_supported(),
    }
