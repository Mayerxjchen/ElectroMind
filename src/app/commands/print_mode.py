"""``-p`` 非交互模式：经 EmbeddedAgentClient 走 Harness 生命周期。

- prompt 来源：位置参数 > stdin 管道（text 输入时 prepend 到 prompt 前）
- 输出：text（仅最终结果）| json（结构化结果）| stream-json（每行一个 v2 事件）
- 非 TTY：无 ANSI、无动画；需要审批的工具直接拒绝并返回 exit 4
- stdout 只出结果/事件；进度与诊断走 stderr
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace

from app.config import ReplConfig, RunOptions, refresh_provider_from_disk
from app.exitcodes import (
    EXIT_CANCELLED,
    EXIT_CLI,
    EXIT_EXECUTION,
    EXIT_OK,
    EXIT_PERMISSION,
    EXIT_PROVIDER,
)
from app.output.json import write_json_result
from app.output.stream_json import StreamJsonWriter
from app.output.text import write_text_result
from electromind.paths import HOME_CONFIG_NAME, LOCAL_CONFIG_NAME

from ..client import EmbeddedAgentClient
from ..render import format_tool_call
from ..tool_permit import parse_permit_answer

TEXT_ITEM = "item-text"


# ---------------------------------------------------------------------------
# Prompt / stdin
# ---------------------------------------------------------------------------


def _read_stdin_if_piped() -> str:
    if sys.stdin.isatty():
        return ""
    try:
        return sys.stdin.read()
    except OSError:
        return ""


def _resolve_prompt(options: RunOptions) -> tuple[str | None, list[str]]:
    """返回 (prompt, stream_json_inputs)。

    - text 输入：位置参数 + stdin 合并成一个 prompt（stdin 在前）。
    - stream-json 输入：**绝不在此整读 stdin**（复验 P0-3）——stdin 由
      ``_stream_stdin_lines`` 逐行流式消费；位置参数作为首个输入。
    """
    prompt = " ".join(options.prompt).strip()

    if options.input_format == "stream-json":
        if prompt:
            return None, [json.dumps({"prompt": prompt})]
        return None, []  # 真实输入来自流式迭代器

    stdin_data = _read_stdin_if_piped()
    if stdin_data and stdin_data.strip():
        prompt = f"{stdin_data.rstrip()}\n\n{prompt}" if prompt else stdin_data.strip()
    return (prompt, []) if prompt else (None, [])


async def _stream_stdin_lines():
    """流式消费 stdin 行（不整读到 EOF）；结束返回 None。"""
    import threading

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _produce() -> None:
        try:
            for line in sys.stdin:
                loop.call_soon_threadsafe(queue.put_nowait, line)
        except Exception:
            pass
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_produce, daemon=True).start()
    while True:
        line = await queue.get()
        if line is None:
            break
        yield line
        await asyncio.sleep(0)  # 让 Run 事件循环有机会推进


def _fail(message: str) -> None:
    print(message, file=sys.stderr)


def _warn_untrusted_project() -> None:
    """非 TTY / 自动化：未信任项目配置已跳过（fail-closed），明确提示。"""
    from app.config import find_project_root, is_project_trusted

    root = find_project_root()
    if root is None or is_project_trusted(root):
        return
    if (root / ".electromind" / HOME_CONFIG_NAME).is_file() or (
        root / ".electromind" / LOCAL_CONFIG_NAME
    ).is_file():
        print(
            f"[config] 未信任的项目 {root}：已跳过其配置；"
            "electromind config trust 可启用",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# 事件收集器
# ---------------------------------------------------------------------------


class _PrintSink:
    """客户端事件 → 结果收集 / stream-json 透传 / 审批响应。"""

    def __init__(self, *, tty: bool, quiet: bool) -> None:
        self.text_parts: list[str] = []
        self.stop_reason = ""
        self.permission_denied = False
        self.run_id = ""
        self.done = asyncio.Event()
        self._tty = tty
        self._quiet = quiet
        self._client: EmbeddedAgentClient | None = None

    def handle(self, line: dict) -> None:
        method = line.get("method", "")
        params = line.get("params", {}) or {}
        if method == "run/started":
            self.run_id = str(params.get("run_id", ""))
        elif method == "item/delta" and params.get("kind") == "text":
            self.text_parts.append(str(params.get("text", "")))
        elif method == "item/started" and params.get("kind") == "tool":
            if not self._quiet:
                print(
                    f"[tool] {format_tool_call(params.get('name', ''), params.get('arguments', ''))}",
                    file=sys.stderr,
                )
        elif method == "approval/requested":
            self._respond_approval(params)
        elif method == "run/completed":
            self.stop_reason = str(params.get("stop_reason", "completed"))
            self.done.set()

    # -- 审批 -----------------------------------------------------------

    def _respond_approval(self, params: dict) -> None:
        if not self._tty:
            # 非 TTY 无法审批 → 明确拒绝并记录（exit 4）
            self.permission_denied = True
            print(
                f"[权限] 拒绝 {params.get('name', '')}（非 TTY 无法审批），任务可能不完整",
                file=sys.stderr,
            )
            asyncio.create_task(self._resolve(params, approved=False))
        else:
            asyncio.create_task(self._prompt_and_resolve(params))

    async def _resolve(self, params: dict, *, approved: bool) -> None:
        client = self._client
        if client is None:
            return
        await client.resolve_approval(
            str(params.get("thread_id", "")),
            str(params.get("run_id", "")),
            str(params.get("approval_id", "")),
            approved,
            tool_call_id=str(params.get("tool_call_id", "")),
        )

    async def _prompt_and_resolve(self, params: dict) -> None:
        from ..render import DIM, YELLOW, c
        from ..terminal import emit, emit_prompt

        emit(
            c(
                f"审批 {params.get('name', '')}：{params.get('summary', '')} [y/N]",
                YELLOW,
                on=True,
            )
        )
        while True:
            line = await asyncio.to_thread(emit_prompt, "permit> ")
            answer = parse_permit_answer(line)
            if answer is None:
                emit(c("输入 y 批准 / n 拒绝", DIM, on=True))
                continue
            await self._resolve(params, approved=answer)
            return


def _exit_for(stop_reason: str, permission_denied: bool) -> int:
    if permission_denied:
        return EXIT_PERMISSION
    if stop_reason == "cancelled":
        return EXIT_CANCELLED
    if stop_reason in ("max_turns", "error"):
        return EXIT_EXECUTION
    return EXIT_OK


def _status_for(exit_code: int) -> str:
    return {
        EXIT_OK: "completed",
        EXIT_PERMISSION: "permission_denied",
        EXIT_CANCELLED: "cancelled",
        EXIT_EXECUTION: "failed",
    }.get(exit_code, "interrupted")


def _parse_stream_line(raw: str) -> str | None:
    """解析一行 stream-json 输入（{"prompt": ...}）；非法/缺字段 → None。"""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        _fail(f"stream-json 输入不是合法 JSON 行: {raw[:80]}")
        return None
    text = str(payload.get("prompt") or payload.get("text") or "")
    if not text.strip():
        _fail("stream-json 输入行缺少 prompt 字段")
        return None
    return text


async def _run_one(
    client: EmbeddedAgentClient,
    sink: _PrintSink,
    thread_id: str,
    config: ReplConfig,
    options: RunOptions,
    text: str,
) -> int:
    """执行单个 Run 并输出该 Run 的结果（json/text）。"""
    from electromind.harness.identity import new_request_id

    sink.text_parts = []
    sink.stop_reason = ""
    sink.permission_denied = False
    sink.done = asyncio.Event()

    await client.send_input(
        thread_id,
        text,
        delivery="auto",
        request_id=new_request_id(),
        mode=config.session_mode or "run",
    )
    await sink.done.wait()

    code = _exit_for(sink.stop_reason, sink.permission_denied)
    result = "".join(sink.text_parts).strip()
    if options.output_format == "json":
        write_json_result(
            {
                "status": _status_for(code),
                "thread_id": thread_id,
                "run_id": sink.run_id,
                "result": result,
                "usage": {},
                "artifacts": [],
            }
        )
    elif options.output_format == "text":
        write_text_result(result, color=sys.stdout.isatty() and not options.no_color)
    return code


async def run(config: ReplConfig, options: RunOptions) -> int:
    prompt, stream_inputs = _resolve_prompt(options)
    if options.input_format == "stream-json" and not stream_inputs:
        # 复验 P0-3：无位置参数时，输入来自 stdin 流式迭代器；
        # 仅当 stdin 也是 TTY（无管道输入）才判缺输入。
        if sys.stdin.isatty():
            _fail("--input-format stream-json 需要 stdin 提供 NDJSON 命令流")
            return EXIT_CLI
    if prompt is None and options.input_format == "text":
        _fail(
            '缺少 prompt：请提供任务文本（electromind -p "..."）或通过 stdin 管道输入'
        )
        return EXIT_CLI
    if not config.resolved_api_key():
        _fail(
            "需要 API Key：写入 ~/.electromind/config.toml 或 export DEEPSEEK_API_KEY"
        )
        return EXIT_PROVIDER
    config = refresh_provider_from_disk(config)

    _warn_untrusted_project()

    from ..repl import open_runner

    tty = sys.stdin.isatty() and sys.stdout.isatty()
    writer = StreamJsonWriter() if options.output_format == "stream-json" else None
    sink = _PrintSink(tty=tty, quiet=options.quiet)
    from datetime import datetime

    thread_id = config.thread_id or f"thread-{datetime.now():%Y%m%d-%H%M%S}"

    async def runner_factory(tid: str):
        return await open_runner(replace(config, thread_id=tid))

    def route(line: dict) -> None:
        if writer is not None:
            writer.write_line(line)
        sink.handle(line)

    client = EmbeddedAgentClient(
        runner_factory,
        config=config,
        event_sink=route,
        persist_meta=not options.no_session_persistence,
    )
    sink._client = client

    exit_code = EXIT_OK
    try:
        if options.input_format == "stream-json":
            # 流式 stdin：逐行消费，不整读到 EOF（验收 G-10）
            for task in stream_inputs:  # 位置参数作为首个输入
                text = _parse_stream_line(task)
                if text is None:
                    return EXIT_CLI
                code = await _run_one(client, sink, thread_id, config, options, text)
                if code != EXIT_OK:
                    exit_code = code
            async for raw in _stream_stdin_lines():
                text = _parse_stream_line(raw)
                if text is None:
                    continue  # 非法行跳过，流继续
                code = await _run_one(client, sink, thread_id, config, options, text)
                if code != EXIT_OK and exit_code == EXIT_OK:
                    exit_code = code
        else:
            code = await _run_one(client, sink, thread_id, config, options, prompt)
            exit_code = code
    finally:
        await client.close()
    return exit_code
