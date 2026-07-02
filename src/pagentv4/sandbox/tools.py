"""电脑能力 → Agent 工具适配层。

把一个已经启动的 Sandbox 转成 8 个 agent 工具：
- run_command / read_file / write_file / str_replace / list_dir
- list_host_files / copy_from_host / copy_to_host

工具都是 async 闭包，捕获 sandbox 引用；这就是「agent 与电脑的绑定关系」。
面向 agent 的措辞里避免出现 sandbox / backend 之类的工程词。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..core.tool import FunctionTool
from .text import prepare_read_file_output

if TYPE_CHECKING:
    from .sandbox import Sandbox


DEFAULT_READ_MAX_OUTPUT = 200_000


def build_sandbox_tools(sandbox: Sandbox) -> list[FunctionTool]:
    return [
        make_run_command(sandbox),
        make_read_file(sandbox),
        make_write_file(sandbox),
        make_str_replace(sandbox),
        make_list_dir(sandbox),
        make_list_host_files(sandbox),
        make_copy_from_host(sandbox),
        make_copy_to_host(sandbox),
    ]


def make_run_command(sandbox: Sandbox) -> FunctionTool:
    async def run_command(command: str, timeout: float | None = None) -> str:
        result = await sandbox.commands.run(command, timeout=timeout)
        return json.dumps(
            {
                "ok": result.ok,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
            }
        )

    return FunctionTool(
        name="run_command",
        description=(
            "在工作目录里执行任意 shell 命令。"
            "返回 JSON：{ok, exit_code, stdout, stderr, timed_out, ...}。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令（通过 /bin/sh -c 解释）。",
                },
                "timeout": {
                    "type": "number",
                    "description": "可选：整条命令的最长运行时间（秒）。",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        func=run_command,
    )


def make_read_file(sandbox: Sandbox) -> FunctionTool:
    async def read_file(
        path: str,
        line_numbers: bool = False,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        content = await sandbox.files.read_text(path)
        output, error = prepare_read_file_output(
            content,
            line_numbers=line_numbers,
            start_line=start_line,
            end_line=end_line,
            max_output=DEFAULT_READ_MAX_OUTPUT,
        )
        if error:
            return json.dumps({"ok": False, "path": path, "error": error})
        return output

    return FunctionTool(
        name="read_file",
        description=(
            "读取文件内容。line_numbers=True 时返回带行号的内容（方便配合 str_replace）；"
            "大文件用 start_line/end_line 按行范围读取（1 起始，闭区间）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径（相对工作目录）。",
                },
                "line_numbers": {
                    "type": "boolean",
                    "description": "是否输出行号，默认 false。",
                },
                "start_line": {
                    "type": "integer",
                    "description": "起始行号（1 起始，闭区间）。",
                    "minimum": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": "结束行号（闭区间）。",
                    "minimum": 1,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        func=read_file,
    )


def make_write_file(sandbox: Sandbox) -> FunctionTool:
    async def write_file(path: str, content: str) -> str:
        await sandbox.files.write(path, content)
        return f"wrote {path}"

    return FunctionTool(
        name="write_file",
        description="写入文件（自动创建父目录）。整个文件都会被覆盖。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径（相对工作目录）。",
                },
                "content": {"type": "string", "description": "要写入的完整文本。"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        func=write_file,
    )


def make_str_replace(sandbox: Sandbox) -> FunctionTool:
    async def str_replace(
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        result = await sandbox.files.str_replace(
            path,
            old_string,
            new_string,
            replace_all=replace_all,
        )
        return json.dumps(result, ensure_ascii=False)

    return FunctionTool(
        name="str_replace",
        description=(
            "在文件中把 old_string 替换成 new_string。"
            "默认只替换唯一匹配；出现多次时把 replace_all 设为 true。"
            "old_string 必须与文件内容完全一致（含缩进/换行），"
            "建议先用 read_file(line_numbers=True) 复制原文本。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径（相对工作目录）。",
                },
                "old_string": {
                    "type": "string",
                    "description": "要被替换掉的原文本（需精确匹配）。",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新文本。",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "old_string 在文件中多次出现时才设为 true。",
                },
            },
            "required": ["path", "old_string", "new_string"],
            "additionalProperties": False,
        },
        func=str_replace,
    )


def make_list_dir(sandbox: Sandbox) -> FunctionTool:
    async def list_dir(path: str = ".") -> str:
        entries = await sandbox.files.list(path)
        return json.dumps(
            [
                {"name": entry.name, "is_dir": entry.is_dir, "size": entry.size}
                for entry in entries
            ]
        )

    return FunctionTool(
        name="list_dir",
        description="查看工作目录下的文件。返回 JSON 数组：[{name, is_dir, size}]。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "子目录路径，默认当前工作目录。",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        func=list_dir,
    )


def make_copy_from_host(sandbox: Sandbox) -> FunctionTool:
    async def copy_from_host(host_path: str, dest: str = ".") -> str:
        placed = await sandbox.copy_from_host(host_path, dest=dest)
        return f"copied user file into workspace at {placed}"

    return FunctionTool(
        name="copy_from_host",
        description=(
            "把用户目录里的文件复制到工作目录，方便进一步处理。"
            "如果不知道文件在哪里，先用 list_host_files 找。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "host_path": {
                    "type": "string",
                    "description": "用户目录里的路径（相对用户目录）。",
                },
                "dest": {
                    "type": "string",
                    "description": "工作目录里的目标子目录，默认工作目录根。",
                },
            },
            "required": ["host_path"],
            "additionalProperties": False,
        },
        func=copy_from_host,
    )


def make_copy_to_host(sandbox: Sandbox) -> FunctionTool:
    async def copy_to_host(source: str, host_dir: str | None = None) -> str:
        placed = await sandbox.copy_to_host(source, host_dir)
        return f"delivered file to user at {placed}"

    return FunctionTool(
        name="copy_to_host",
        description=(
            "把工作目录里的一个文件交付给用户。"
            f"默认放到用户目录下的 `{sandbox.ARTIFACTS_DIRNAME}/` 输出目录；"
            "需要放到别的子目录时才传 host_dir。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "要交付的文件在工作目录中的路径。",
                },
                "host_dir": {
                    "type": "string",
                    "description": (
                        "可选：用户目录下的目标子目录，"
                        f"默认 `{sandbox.ARTIFACTS_DIRNAME}/`。"
                    ),
                },
            },
            "required": ["source"],
            "additionalProperties": False,
        },
        func=copy_to_host,
    )


def make_list_host_files(sandbox: Sandbox) -> FunctionTool:
    async def list_host_files(path: str = "", depth: int = 1) -> str:
        result = sandbox.list_host_files(path, depth=depth)
        return json.dumps(result, ensure_ascii=False)

    return FunctionTool(
        name="list_host_files",
        description=(
            "查看用户目录里的文件，用于定位用户提到的文件位置。"
            "返回 JSON：{ok, path, entries[]}。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "用户目录下的子路径，空字符串表示用户目录本身。",
                },
                "depth": {
                    "type": "integer",
                    "description": "递归深度 1..3，默认 1（只列直接子项）。",
                    "minimum": 1,
                    "maximum": 3,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        func=list_host_files,
    )
