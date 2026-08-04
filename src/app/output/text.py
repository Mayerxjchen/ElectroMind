"""text 输出：仅最终人类可读结果（写 stdout）。进度/诊断一律走 stderr。"""

from __future__ import annotations

import sys


def write_text_result(text: str, *, color: bool = False, stream=None) -> None:
    stream = stream or sys.stdout
    if color:
        from . import colors

        text = colors.result(text)
    stream.write(text if text.endswith("\n") else text + "\n")
    stream.flush()
