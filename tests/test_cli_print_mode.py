"""CLI-3 + CLI-4：-p 非交互模式经 EmbeddedAgentClient 走完整 Harness 生命周期。"""

from __future__ import annotations

import json
import sys

import pytest

from app.commands.print_mode import (
    _exit_for,
    _resolve_prompt,
)
from app.config import ReplConfig, RunOptions
from app.exitcodes import (
    EXIT_CANCELLED,
    EXIT_CLI,
    EXIT_EXECUTION,
    EXIT_OK,
    EXIT_PERMISSION,
    EXIT_PROVIDER,
)
from electromind import RunEnd, TextDelta, ToolCallBegin, ToolResult

# ---------------------------------------------------------------------------
# Fakes（须能撑过 client 全链路：snapshot/审批/steer/metainfo）
# ---------------------------------------------------------------------------


class FakeThread:
    def __init__(self, thread_id):
        self.id = thread_id
        self.meta = {}
        self.project_path = ""
        self.spec = None

    def load_metainfo(self):
        return self.meta

    def save_metainfo(self, meta):
        self.meta = meta


class FakeMessages:
    def __init__(self):
        self.data = []


class FakeInbound:
    def __init__(self, runner):
        self.runner = runner

    def permit(self, tool_call_id):
        self.runner.permitted.append(tool_call_id)

    def deny(self, tool_call_id, reason=""):
        self.runner.denied.append((tool_call_id, reason))


class FakeSandbox:
    def __init__(self):
        self.workdir = "/workspace"
        self.backend = None


class FakeRunner:
    """print mode 全链路 runner：事件流 + 审批记录 + metainfo。"""

    def __init__(self, events, thread_id="thread-p1"):
        self.events = events
        self.thread = FakeThread(thread_id)
        self.messages = FakeMessages()
        self.sandbox = FakeSandbox()
        self.agent = None
        self.denied: list[tuple[str, str]] = []
        self.permitted: list[str] = []
        self.steered: list[str] = []
        self.prompts: list[str] = []
        self.closed = False

    async def run(self, prompt):
        self.prompts.append(prompt)
        for event in self.events:
            yield event

    def steer(self, text):
        self.steered.append(text)

    @property
    def inbound(self):
        return FakeInbound(self)

    async def close(self):
        self.closed = True


class FakeStdin:
    def __init__(self, content: str = ""):
        self.content = content

    def isatty(self) -> bool:
        return False

    def read(self) -> str:
        return self.content


def fake_tty(monkeypatch, *, stdin: bool, stdout: bool) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout)


def options(**kwargs) -> RunOptions:
    base = dict(
        output_format="text",
        input_format="text",
        no_color=False,
        quiet=False,
        no_session_persistence=False,
    )
    base.update(kwargs)
    return RunOptions(**base)


def config(**kwargs) -> ReplConfig:
    base = dict(api_key="sk-test-key")
    base.update(kwargs)
    return ReplConfig(**base)


async def run_print(cfg, opts, monkeypatch, tmp_path, runner):
    """run() 全链路：mock open_runner 返回给定 runner。"""
    import app.commands.print_mode as print_mode

    monkeypatch.setenv("ELECTROMIND_HOME", str(tmp_path / "home"))

    async def fake_open(cfg2):
        return runner

    monkeypatch.setattr("app.repl.open_runner", fake_open)
    return await print_mode.run(cfg, opts)


# ---------------------------------------------------------------------------
# text 输出
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_output_writes_final_result_only(capsys, monkeypatch, tmp_path):
    fake_tty(monkeypatch, stdin=False, stdout=False)
    runner = FakeRunner(
        [
            TextDelta("分析"),
            TextDelta("完成"),
            RunEnd(turn=1, stop_reason="no_tool_calls"),
        ]
    )
    code = await run_print(
        config(), options(prompt=("任务",)), monkeypatch, tmp_path, runner
    )
    assert code == EXIT_OK
    assert capsys.readouterr().out == "分析完成\n"
    assert runner.closed is True


@pytest.mark.asyncio
async def test_no_session_persistence_skips_metainfo(capsys, monkeypatch, tmp_path):
    fake_tty(monkeypatch, stdin=False, stdout=False)
    runner = FakeRunner([TextDelta("hi"), RunEnd(turn=1, stop_reason="no_tool_calls")])
    await run_print(
        config(),
        options(prompt=("任务",), no_session_persistence=True),
        monkeypatch,
        tmp_path,
        runner,
    )
    assert runner.thread.meta == {}


# ---------------------------------------------------------------------------
# json 输出
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_json_output_document_shape(capsys, monkeypatch, tmp_path):
    fake_tty(monkeypatch, stdin=False, stdout=False)
    runner = FakeRunner(
        [TextDelta("结果文本"), RunEnd(turn=1, stop_reason="no_tool_calls")]
    )
    code = await run_print(
        config(thread_id="thread-p1"),
        options(prompt=("任务",), output_format="json"),
        monkeypatch,
        tmp_path,
        runner,
    )
    assert code == EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "completed"
    assert doc["thread_id"] == "thread-p1"
    assert doc["run_id"].startswith("run-")
    assert doc["result"] == "结果文本"
    assert doc["usage"] == {}
    assert doc["artifacts"] == []


# ---------------------------------------------------------------------------
# stream-json 输出（CLI-4：事件来自 Harness 客户端，带 envelope）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_json_emits_v2_events(capsys, monkeypatch, tmp_path):
    fake_tty(monkeypatch, stdin=False, stdout=False)
    runner = FakeRunner(
        [
            TextDelta("好"),
            ToolCallBegin("call-1", "web_search", '{"query":"x"}'),
            ToolResult("call-1", "web_search", "{}", ok=True),
            RunEnd(turn=1, stop_reason="no_tool_calls"),
        ]
    )
    code = await run_print(
        config(thread_id="thread-p1"),
        options(prompt=("任务",), output_format="stream-json"),
        monkeypatch,
        tmp_path,
        runner,
    )
    assert code == EXIT_OK
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    methods = [line["method"] for line in lines]
    # input/state(queued) 先于 run/started；run/started 必在，run/completed 收尾
    assert "run/started" in methods
    assert "item/delta" in methods
    assert "item/started" in methods
    assert "item/completed" in methods
    assert methods[-1] == "run/completed"
    # envelope 契约：thread_id/seq 单调、run_id 贯穿、item 事件带 item_id
    for line in lines:
        assert line["params"]["thread_id"] == "thread-p1"
        assert line["params"]["protocol_version"] == 2
        assert line["params"]["event_id"]
    seqs = [line["params"]["seq"] for line in lines]
    assert seqs == sorted(seqs)
    started = next(ln for ln in lines if ln["method"] == "run/started")
    completed = next(ln for ln in lines if ln["method"] == "run/completed")
    assert started["params"]["run_id"] == completed["params"]["run_id"]
    item_lines = [
        ln for ln in lines if ln["method"] in ("item/started", "item/completed")
    ]
    assert all(ln["params"].get("item_id") for ln in item_lines)


# ---------------------------------------------------------------------------
# 权限：非 TTY 明确失败 / auto-safe 风险门
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_tty_permission_denied_exit_4(capsys, monkeypatch, tmp_path):
    fake_tty(monkeypatch, stdin=False, stdout=False)
    runner = FakeRunner(
        [
            ToolCallBegin("call-1", "run_command", '{"command":"rm -rf /"}'),
            ToolResult("call-1", "run_command", '{"ok": false}', ok=False),
            RunEnd(turn=1, stop_reason="no_tool_calls"),
        ]
    )
    code = await run_print(
        config(), options(prompt=("任务",)), monkeypatch, tmp_path, runner
    )
    assert code == EXIT_PERMISSION
    assert "无法审批" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_tty_permission_approves_via_prompt(capsys, monkeypatch, tmp_path):
    fake_tty(monkeypatch, stdin=True, stdout=True)
    prompted: list[str] = []

    async def fake_prompt(self, params):
        prompted.append(params["tool_call_id"])
        await self._resolve(params, approved=True)

    monkeypatch.setattr(
        "app.commands.print_mode._PrintSink._prompt_and_resolve", fake_prompt
    )
    runner = FakeRunner(
        [
            ToolCallBegin("call-1", "run_command", '{"command":"pwd"}'),
            ToolResult("call-1", "run_command", '{"ok": true}', ok=True),
            RunEnd(turn=1, stop_reason="no_tool_calls"),
        ]
    )
    code = await run_print(
        config(), options(prompt=("任务",)), monkeypatch, tmp_path, runner
    )
    assert code == EXIT_OK
    assert prompted == ["call-1"]


@pytest.mark.asyncio
async def test_auto_safe_safe_command_auto_approved(capsys, monkeypatch, tmp_path):
    """auto-safe：后端判定为安全的命令自动放行，不提示也不拒绝。"""
    fake_tty(monkeypatch, stdin=False, stdout=False)
    runner = FakeRunner(
        [
            ToolCallBegin("call-1", "run_command", '{"command":"cat input.inp"}'),
            ToolResult("call-1", "run_command", '{"ok": true}', ok=True),
            RunEnd(turn=1, stop_reason="no_tool_calls"),
        ]
    )
    code = await run_print(
        config(permission_mode="auto-safe"),
        options(prompt=("任务",)),
        monkeypatch,
        tmp_path,
        runner,
    )
    assert code == EXIT_OK
    assert runner.denied == []
    assert runner.permitted == []


@pytest.mark.asyncio
async def test_auto_safe_unsafe_command_non_tty_exit_4(capsys, monkeypatch, tmp_path):
    """auto-safe：危险命令在非 TTY 无法审批 → 明确失败 exit 4。"""
    fake_tty(monkeypatch, stdin=False, stdout=False)
    runner = FakeRunner(
        [
            ToolCallBegin("call-1", "run_command", '{"command":"rm -rf output/"}'),
            ToolResult("call-1", "run_command", '{"ok": false}', ok=False),
            RunEnd(turn=1, stop_reason="no_tool_calls"),
        ]
    )
    code = await run_print(
        config(permission_mode="auto-safe"),
        options(prompt=("任务",)),
        monkeypatch,
        tmp_path,
        runner,
    )
    assert code == EXIT_PERMISSION


@pytest.mark.asyncio
async def test_auto_skips_all_permit(capsys, monkeypatch, tmp_path):
    """auto（遗留 --yolo 语义）：全部放行。"""
    fake_tty(monkeypatch, stdin=False, stdout=False)
    runner = FakeRunner(
        [
            ToolCallBegin("call-1", "run_command", '{"command":"rm -rf output/"}'),
            ToolResult("call-1", "run_command", '{"ok": true}', ok=True),
            RunEnd(turn=1, stop_reason="no_tool_calls"),
        ]
    )
    code = await run_print(
        config(permission_mode="auto"),
        options(prompt=("任务",)),
        monkeypatch,
        tmp_path,
        runner,
    )
    assert code == EXIT_OK
    assert runner.denied == []


# ---------------------------------------------------------------------------
# Exit Code 映射
# ---------------------------------------------------------------------------


def test_exit_code_mapping():
    assert _exit_for("no_tool_calls", False) == EXIT_OK
    assert _exit_for("empty_response", False) == EXIT_OK
    assert _exit_for("cancelled", False) == EXIT_CANCELLED
    assert _exit_for("max_turns", False) == EXIT_EXECUTION
    assert _exit_for("error", False) == EXIT_EXECUTION
    assert _exit_for("no_tool_calls", True) == EXIT_PERMISSION


@pytest.mark.asyncio
async def test_cancelled_stop_reason_exit_6(capsys, monkeypatch, tmp_path):
    fake_tty(monkeypatch, stdin=False, stdout=False)
    runner = FakeRunner([TextDelta("半截"), RunEnd(turn=1, stop_reason="cancelled")])
    code = await run_print(
        config(thread_id="thread-p1"),
        options(prompt=("任务",), output_format="json"),
        monkeypatch,
        tmp_path,
        runner,
    )
    assert code == EXIT_CANCELLED
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "cancelled"


# ---------------------------------------------------------------------------
# prompt / stdin 解析
# ---------------------------------------------------------------------------


def test_resolve_prompt_positional_only(monkeypatch):
    monkeypatch.setattr(sys, "stdin", FakeStdin(content=""))
    prompt, lines = _resolve_prompt(options(prompt=("检查项目",)))
    assert prompt == "检查项目"
    assert lines == []


def test_resolve_prompt_stdin_prepended(monkeypatch):
    monkeypatch.setattr(sys, "stdin", FakeStdin(content="cp2k.out 内容\n"))
    prompt, lines = _resolve_prompt(options(prompt=("分析这个输出",)))
    assert prompt == "cp2k.out 内容\n\n分析这个输出"


def test_resolve_prompt_stdin_only(monkeypatch):
    monkeypatch.setattr(sys, "stdin", FakeStdin(content="只有 stdin\n"))
    prompt, lines = _resolve_prompt(options())
    assert prompt == "只有 stdin"


def test_resolve_prompt_stream_json_positional_only(monkeypatch):
    """stream-json：位置参数作为首个输入；stdin 由流式迭代器消费（不整读）。"""
    monkeypatch.setattr(
        sys, "stdin", FakeStdin(content='{"prompt":"任务一"}\n{"prompt":"任务二"}\n')
    )
    prompt, lines = _resolve_prompt(options(input_format="stream-json"))
    assert prompt is None
    assert lines == []  # stdin 不再被 _resolve_prompt 整读

    prompt, lines = _resolve_prompt(
        options(input_format="stream-json", prompt=("首个",))
    )
    assert prompt is None
    assert json.loads(lines[0])["prompt"] == "首个"  # 位置参数作为首个输入


@pytest.mark.asyncio
async def test_stream_stdin_lines_consumes_lazily(monkeypatch):
    """验收 G-10：stream-json 输入逐行消费，不整读到 EOF。"""
    from app.commands import print_mode

    class FakeStdinIter:
        def __init__(self, lines):
            self._lines = lines
            self.consumed = 0

        def __iter__(self):
            return self

        def __next__(self):
            if not self._lines:
                raise StopIteration
            self.consumed += 1
            return self._lines.pop(0)

    fake = FakeStdinIter(['{"prompt":"任务一"}\n', '{"prompt":"任务二"}\n'])
    monkeypatch.setattr(sys, "stdin", fake)

    collected: list[str] = []
    async for raw in print_mode._stream_stdin_lines():
        collected.append(raw)

    # 逐行产出（生产者线程可略超前，但消费端逐行处理，不等待 EOF）
    assert collected == ['{"prompt":"任务一"}\n', '{"prompt":"任务二"}\n']
    assert fake.consumed == 2


def test_stream_json_never_reads_stdin_upfront(monkeypatch):
    """复验 P0-3：stream-json 主路径不整读 stdin（read 不被调用）。"""
    from app.commands import print_mode

    calls: list[str] = []

    class FakeStdin:
        def isatty(self) -> bool:
            return False

        def read(self) -> str:
            calls.append("read")
            return '{"prompt":"任务一"}\n{"prompt":"任务二"}\n'

    monkeypatch.setattr(sys, "stdin", FakeStdin())
    prompt, lines = print_mode._resolve_prompt(options(input_format="stream-json"))
    assert calls == []  # read 未被调用（stdin 留给流式迭代器）
    assert prompt is None
    assert lines == []


@pytest.mark.asyncio
async def test_stream_json_run_with_piped_stdin(monkeypatch, tmp_path, capsys):
    """复验 P0-3：管道 stdin + stream-json 主路径可执行（不再 exit 2）。"""

    from app.commands import print_mode

    monkeypatch.setenv("ELECTROMIND_HOME", str(tmp_path / "home"))
    runner = FakeRunner(
        [TextDelta("结果"), RunEnd(turn=1, stop_reason="no_tool_calls")]
    )

    async def fake_open(cfg):
        return runner

    monkeypatch.setattr("app.repl.open_runner", fake_open)

    class PipedStdin:
        def __init__(self, lines):
            self._lines = list(lines)
            self.read_calls = 0

        def isatty(self) -> bool:
            return False

        def read(self) -> str:
            self.read_calls += 1
            return ""

        def __iter__(self):
            return self

        def __next__(self):
            if not self._lines:
                raise StopIteration
            return self._lines.pop(0)

    fake = PipedStdin(['{"prompt":"任务一"}\n', '{"prompt":"任务二"}\n'])
    monkeypatch.setattr(sys, "stdin", fake)

    code = await print_mode.run(
        config(thread_id="thread-p1"), options(input_format="stream-json")
    )
    assert code == EXIT_OK
    assert fake.read_calls == 0  # 未整读 stdin
    assert runner.prompts == ["任务一", "任务二"]  # 两行都被流式消费


def test_parse_stream_line():
    from app.commands import print_mode

    assert print_mode._parse_stream_line('{"prompt":"任务"}') == "任务"
    assert print_mode._parse_stream_line('{"text":"备用"}') == "备用"
    assert print_mode._parse_stream_line("not json") is None
    assert print_mode._parse_stream_line('{"noprompt":1}') is None


def test_resolve_prompt_missing_is_none(monkeypatch):
    monkeypatch.setattr(sys, "stdin", FakeStdin(content=""))
    prompt, lines = _resolve_prompt(options())
    assert prompt is None
    assert lines == []


# ---------------------------------------------------------------------------
# run() 顶层：缺 Key / 缺 prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_missing_api_key_returns_provider_code(capsys):
    from app.commands import print_mode

    code = await print_mode.run(config(api_key=None), options(prompt=("任务",)))
    assert code == EXIT_PROVIDER


@pytest.mark.asyncio
async def test_run_missing_prompt_returns_cli_code(capsys):
    from app.commands import print_mode

    code = await print_mode.run(config(), options())
    assert code == EXIT_CLI
