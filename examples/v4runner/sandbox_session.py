"""v4 Runner.session — 造 sandbox → 造 agent → 绑工具 → 跑 → 关。

演示 pagentv4 的一站式编排：一个 Sandbox 就是 agent 的伴身电脑，
`Runner.session()` 会自动在电脑上挂好工具（run_command / read_file /
write_file / list_dir / upload / download），跑完自动关机。

默认用 `workspace_id="default"` 让工作目录落到项目下的
`.pagent/workspaces/default/`；换 id 或换目录都能持久化不同的会话。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.v4runner.sandbox_session
    uv run python -m examples.v4runner.sandbox_session --workspace-id demo
    uv run python -m examples.v4runner.sandbox_session --workdir ./scratch
"""

import argparse
import asyncio
import os
import sys

from pagentv4 import (
    DeepSeek,
    ReasoningDelta,
    Runner,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)
from pagentv4.sandbox import resolve_workdir

CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"

QUESTION = (
    "在 /home/agent 下创建 notes.md，内容是三条关于尾递归的要点，每条一行。"
    "写完用 list_dir 看一下当前目录，再用 read_file 把 notes.md 读回来确认。"
    "最后一句总结你做了什么。"
)


def use_color() -> bool:
    return sys.stdout.isatty()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace-id",
        default="default",
        help="沙箱 workspace 名，落到 <cwd>/.pagent/workspaces/<id>/",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="沙箱工作目录绝对路径；给了这个就忽略 --workspace-id",
    )
    parser.add_argument(
        "--model",
        default="deepseek-v4-flash",
        help="DeepSeek 模型名",
    )
    return parser.parse_args()


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    args = parse_args()
    workspace_id = None if args.workdir else args.workspace_id
    workdir = resolve_workdir(workspace_id=workspace_id, workdir=args.workdir)
    color = use_color()

    print(f"sandbox workdir: {workdir}")
    print(f"Q: {QUESTION}\n")

    provider = DeepSeek(args.model)
    runner = Runner()
    in_reasoning = False

    async for event in runner.session(
        provider,
        QUESTION,
        system="你是一个乐于使用工具的助手；操作前先想清楚，答案要简短。",
        workspace_id=workspace_id,
        workdir=args.workdir,
    ):
        if isinstance(event, TurnBegin):
            head = f"── turn {event.turn} 开始 ──"
            print(f"{DIM}{head}{RESET}" if color else head)
            in_reasoning = False

        elif isinstance(event, ReasoningDelta):
            if not in_reasoning:
                in_reasoning = True
                if color:
                    sys.stdout.write(DIM)
                sys.stdout.write("reasoning: ")
            sys.stdout.write(event.text)
            sys.stdout.flush()

        elif isinstance(event, ToolCallBegin):
            if in_reasoning and color:
                sys.stdout.write(RESET)
            in_reasoning = False
            line = f"tool → {event.name}({event.arguments})"
            print(f"{CYAN}{line}{RESET}" if color else line)

        elif isinstance(event, ToolResult):
            body = event.content.replace("\n", " ")
            if len(body) > 160:
                body = body[:160] + "…"
            if event.ok:
                print(f"  {GREEN}ok{RESET}: {body}" if color else f"  ok: {body}")
            else:
                print(f"  {RED}fail{RESET}: {body}" if color else f"  fail: {body}")

        elif isinstance(event, TextDelta):
            if in_reasoning:
                if color:
                    sys.stdout.write(RESET)
                print()
                in_reasoning = False
            sys.stdout.write(event.text)
            sys.stdout.flush()

        elif isinstance(event, TurnEnd):
            if in_reasoning and color:
                sys.stdout.write(RESET)
            in_reasoning = False
            reason = f" ({event.stop_reason})" if event.stopped else ""
            tail = f"── turn {event.turn} 结束{reason} ──"
            print(f"\n{DIM}{tail}{RESET}" if color else f"\n{tail}")

    notes_path = os.path.join(workdir, "notes.md")
    if os.path.isfile(notes_path):
        print(f"\n落盘的 notes.md → {notes_path}")


if __name__ == "__main__":
    asyncio.run(main())
