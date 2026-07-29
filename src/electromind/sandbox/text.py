"""文本渲染辅助 —— 给 read_file / str_replace 用。

参考 zagent/src/computer/text.py：
- 行号右对齐宽度自适应
- 按行范围切片（1 起始闭区间）
- 超长输出中间省略，头尾各留一半
"""

from __future__ import annotations


def format_with_line_numbers(text: str) -> str:
    if not text:
        return text
    lines = text.splitlines()
    width = len(str(len(lines)))
    return "\n".join(
        f"{index:>{width}} | {line}" for index, line in enumerate(lines, start=1)
    )


def slice_by_line_range(
    text: str,
    start_line: int | None,
    end_line: int | None,
) -> tuple[str, str | None]:
    if start_line is None and end_line is None:
        return text, None

    lines = text.splitlines()
    total = len(lines)
    if total == 0:
        return text, "文件为空，无法按行读取。"

    start = start_line if start_line is not None else 1
    end = end_line if end_line is not None else total

    if start < 1:
        return text, "start_line 必须 >= 1。"
    if end < start:
        return text, "end_line 不能小于 start_line。"
    if start > total:
        return text, f"start_line 超出文件行数（共 {total} 行）。"

    end = min(end, total)
    return "\n".join(lines[start - 1 : end]), None


def truncate_output(text: str, max_output: int) -> str:
    if max_output <= 0 or len(text) <= max_output:
        return text
    marker = "\n...[truncated, use grep/tail/head or start_line/end_line]...\n"
    chunk_size = max((max_output - len(marker)) // 2, 1)
    return text[:chunk_size] + marker + text[-chunk_size:]


def prepare_read_file_output(
    text: str,
    *,
    line_numbers: bool,
    start_line: int | None,
    end_line: int | None,
    max_output: int,
) -> tuple[str, str | None]:
    content, error = slice_by_line_range(text, start_line, end_line)
    if error:
        return content, error
    if line_numbers:
        content = format_with_line_numbers(content)
    return truncate_output(content, max_output), None
