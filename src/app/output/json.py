"""json 输出：最终结构化结果（单文档，写 stdout）。"""

from __future__ import annotations

import json
import sys


def write_json_result(result: dict, *, stream=None) -> None:
    stream = stream or sys.stdout
    stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    stream.flush()
