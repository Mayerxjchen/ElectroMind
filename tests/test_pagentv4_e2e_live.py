"""真模型端到端冒烟测试（live）。

与 FakeProvider 的单测互补：这里用真实 DeepSeek 跑一整轮 Runner 闭环——
真模型流式解析 + 真 local sandbox 工具执行 + 真 conversation 落盘——覆盖
单测 stub 掉的「模型自主决策 → tool_call → 拿结果 → 再循环」链路。

默认 skip；设置 ``DEEPSEEK_API_KEY`` 后才会跑::

    DEEPSEEK_API_KEY=sk-... uv run pytest tests/test_pagentv4_e2e_live.py -q

可选环境变量：

- ``PAGENTV4_E2E_MODEL``：模型名（默认 ``deepseek-v4-flash``）。
- ``PAGENTV4_E2E_TIMEOUT``：单轮超时秒数（默认 180）。
"""

from __future__ import annotations

import asyncio
import os

import pytest

from pagentv4 import (
    DeepSeek,
    RunEnd,
    Runner,
    TextDelta,
    ToolCallBegin,
    ToolResult,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY"),
    reason="set DEEPSEEK_API_KEY to run the live end-to-end test",
)


@pytest.mark.asyncio
async def test_live_agent_runs_full_loop_with_sandbox_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    model = os.getenv("PAGENTV4_E2E_MODEL", "deepseek-v4-flash")
    timeout = float(os.getenv("PAGENTV4_E2E_TIMEOUT", "180"))

    runner = await Runner.create(
        "e2e-live",
        DeepSeek(model),
        overrides={"backend": "local"},
        extra_system=(
            "你是 pagent，一台带工作目录的伴身电脑。"
            "收到任务时请使用提供的工具（run_command / write_file / read_file）"
            "实际操作文件来完成，不要只口头回答。"
        ),
        max_turns=8,
    )
    try:
        events = []
        async with asyncio.timeout(timeout):
            async for event in runner.run(
                "请在工作目录创建 hello.txt，内容写 pagent-e2e，然后读出来确认。"
            ):
                events.append(event)
    finally:
        await runner.close()

    # 1) run 正常终止
    run_ends = [e for e in events if isinstance(e, RunEnd)]
    assert run_ends, "run 未产生 RunEnd（未正常终止）"

    # 2) 模型若发起工具调用，loop 必须把每个都执行完（ToolCallBegin ↔ ToolResult 配对）
    begins = [e for e in events if isinstance(e, ToolCallBegin)]
    results = [e for e in events if isinstance(e, ToolResult)]
    assert len(results) == len(begins), (
        f"工具调用 {len(begins)} 个但结果 {len(results)} 个，loop 未完整执行工具"
    )

    # 3) 模型调了工具时，至少有一个成功执行（证明 sandbox 工具链通）
    if begins:
        assert any(r.ok for r in results), "所有工具调用都失败，sandbox 工具链异常"

    # 4) 有产出：调了工具，或给了文本（证明模型流式解析正常）
    assert begins or any(isinstance(e, TextDelta) for e in events), "模型无任何产出"

    # 5) 对话落盘
    assert (tmp_path / ".pagent" / "threads" / "e2e-live" / "messages.jsonl").is_file()
