"""v4 子 agent 委派（delegate）—— 本分支的核心能力验收。

范式：委派返回。主 agent 把可隔离的子任务交给命名子 agent，子 agent 在同一个
Runner 的一帧新上下文里独立跑完，把最终答复作为工具结果交回主 agent。主 agent
全程不退出，delegate 对它就是一次普通工具调用。

配置驱动：子 agent 写在 thread.toml 的 ``[sub.<name>]``，并在 ``[agent] tools`` 列出
``delegate_to_subagent`` 才启用。这里用 overrides 等价地注入这份配置，走的是主流程
（``Runner.create`` → ``assemble_run_resources``）自动挂载的同一条路径：

    [agent]
    tools = ["delegate_to_subagent"]

    [sub.researcher]
    system = "你是技术调研员，只输出要点"

    [sub.writer]
    system = "你是科普作者，把要点写成短文"

主 agent 拿到的是统一的 ``delegate_to_subagent`` 工具：一个工具，按 ``type`` 选子
agent（不是一个子 agent 一个工具名）。

子 agent 的内部事件不会冒泡到主事件流（run_sub_agent 只取最终答复）。所以这里分两层
观察委派效果：
1. 主事件流里的 ToolCallBegin / ToolResult —— 看到 delegate_to_subagent 被调用、拿回答复。
2. 跑完后回读 store 里的子对话 messages.sub.<name>.<seq> —— 看到每个子 agent 各自
   实际写了什么。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv4.runner.delegate
"""

import asyncio
import os
import sys
from datetime import datetime

from pagentv4 import (
    DeepSeek,
    Runner,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)
from pagentv4.core.message import TextChunk
from pagentv4.ithread import SubAgentSpec

CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"

QUESTION = (
    "帮我写一段面向初学者的科普短文，讲清楚 Rust 的所有权（ownership）机制。"
    "你自己不要直接写，先把调研交给 researcher，再把成文交给 writer，最后综述定稿。"
)

# 等价于 thread.toml 的 [sub.researcher] / [sub.writer]。
SUBS = {
    "researcher": SubAgentSpec(
        system="你是技术调研员。只输出 3-5 条要点，每条一行，聚焦事实，不写正文、不寒暄。",
    ),
    "writer": SubAgentSpec(
        system=(
            "你是科普作者。根据给到的要点写一段 150 字以内、面向初学者的通顺短文，"
            "不要用列表，只输出正文。"
        ),
    ),
}


def use_color() -> bool:
    return sys.stdout.isatty()


async def run_main_stream(runner: Runner, color: bool) -> None:
    """跑主 agent，实时观察 delegate_to_subagent 的调用与回收。"""
    in_text = False
    async for event in runner.run(QUESTION):
        if isinstance(event, TurnBegin):
            print(
                f"{DIM if color else ''}── turn {event.turn} ──{RESET if color else ''}"
            )
            in_text = False

        elif isinstance(event, ToolCallBegin):
            in_text = False
            arrow = f"委派 → {event.name}"
            detail = event.arguments.replace("\n", " ")
            print(
                f"{CYAN}{arrow}{RESET}  {DIM}{detail}{RESET}"
                if color
                else f"{arrow}  {detail}"
            )

        elif isinstance(event, ToolResult):
            mark = "ok" if event.ok else "fail"
            body = event.content.replace("\n", " ")
            print(f"  {GREEN if color else ''}{mark} ← {body}{RESET if color else ''}")

        elif isinstance(event, TextDelta):
            if not in_text:
                in_text = True
                sys.stdout.write(
                    f"\n{YELLOW if color else ''}主 agent：{RESET if color else ''}"
                )
            sys.stdout.write(event.text)
            sys.stdout.flush()

        elif isinstance(event, TurnEnd):
            in_text = False
            print()


def replay_sub_conversations(runner: Runner, color: bool) -> None:
    """回读子对话落盘：主事件流看不到的子 agent 实际产出，都在这里。"""
    main_id = runner.thread.messages_conversation_id
    sub_prefix = f"{main_id}.sub."
    sub_ids = sorted(cid for cid in runner.store.list() if cid.startswith(sub_prefix))

    if not sub_ids:
        print(
            f"\n{DIM if color else ''}（未发生委派：主 agent 没有调用子 agent）{RESET if color else ''}"
        )
        return

    print(
        f"\n{DIM if color else ''}══ 子 agent 各自的完整答复（回读子对话落盘）══{RESET if color else ''}"
    )
    for cid in sub_ids:
        name = cid[len(sub_prefix) :].rsplit(".", 1)[0]
        messages = runner.store.load(cid)
        answer = "".join(
            m.content.text
            for m in messages.data
            if m.role == "assistant" and isinstance(m.content, TextChunk)
        )
        header = f"[{name}]"
        print(
            f"\n{CYAN if color else ''}{header}{RESET if color else ''} {answer.strip()}"
        )


async def main() -> None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    color = use_color()
    thread_id = f"delegate-demo-{datetime.now():%Y%m%d-%H%M%S}"
    runner = await Runner.create(
        thread_id,
        DeepSeek("deepseek-v4-flash"),
        overrides={
            "backend": "none",
            # 列出 delegate_to_subagent + 配 subs，主流程即自动挂载委派工具。
            "agent_tools": ("delegate_to_subagent",),
            "subs": SUBS,
        },
        extra_system=(
            "你是项目负责人，手上有 researcher 和 writer 两个子 agent。"
            "遇到可拆分的任务时，用 delegate_to_subagent 工具把子任务分派下去（按 type 选人），"
            "自己只做规划与综述。"
        ),
    )

    print(f"Q: {QUESTION}\n")
    try:
        await run_main_stream(runner, color)
        replay_sub_conversations(runner, color)
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
