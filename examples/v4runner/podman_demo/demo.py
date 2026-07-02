"""Podman backend demo — 在容器里跑一段真实的 agent 任务。

前置：
    cd examples/v4runner/podman_demo
    podman build -t pagent-podman-demo:latest .
    export DEEPSEEK_API_KEY=<your-key>

跑：
    uv run python examples/v4runner/podman_demo/demo.py
    uv run python examples/v4runner/podman_demo/demo.py --backend docker
    uv run python examples/v4runner/podman_demo/demo.py --image python:3.11-slim

Sandbox 门面把 `/home/agent` 前缀映射到宿主 workdir，容器里通过
`-v <workdir>:<workdir>` bind mount 到同名路径，所以：
- 文件 API 直接落到宿主机文件系统
- exec 走 `podman exec -w <workdir> <cid> <argv>` 在容器里执行

跑完可以到 <cwd>/.pagent/workspaces/podman-demo/ 找 agent 写下的文件。
"""

import argparse
import asyncio
import os
import sys

from pagentv4 import (
    DeepSeek,
    ReasoningDelta,
    Runner,
    Sandbox,
    TextDelta,
    ToolCallBegin,
    ToolResult,
)

CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"

QUESTION = (
    "先跑 `python -c 'import sys, platform; print(sys.version); print(platform.platform())'` "
    "确认你在容器里；然后在 /home/agent 下写一个 fib.py，"
    "内容是打印 fibonacci 前 10 项；跑一下确认输出正确，最后一句总结你做了什么。"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        default="podman",
        choices=("podman", "docker"),
        help="容器 CLI；默认 podman",
    )
    parser.add_argument(
        "--image",
        default="pagent-podman-demo:latest",
        help="容器镜像 tag；默认用同目录 Dockerfile 构建的 pagent-podman-demo:latest",
    )
    parser.add_argument(
        "--workspace-id",
        default="podman-demo",
        help="沙箱 workspace 名，落到 <cwd>/.pagent/workspaces/<id>/",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=600,
        help=(
            "容器寿命（秒）；到期主进程 sleep 自然退出 + --rm 会自动清掉；"
            "宿主进程 kill -9 也不会遗留容器。传 0 关掉即用 sleep infinity。"
        ),
    )
    parser.add_argument(
        "--model",
        default="deepseek-v4-flash",
        help="DeepSeek 模型名",
    )
    return parser.parse_args()


def use_color() -> bool:
    return sys.stdout.isatty()


async def render(runner, agent, question, messages):
    color = use_color()
    in_reasoning = False
    async for event in runner.arun(agent, question, messages):
        if isinstance(event, ReasoningDelta):
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
                print()
            in_reasoning = False
            line = f"tool → {event.name}({event.arguments})"
            print(f"{CYAN}{line}{RESET}" if color else line)
        elif isinstance(event, ToolResult):
            body = event.content.replace("\n", " ")
            if len(body) > 200:
                body = body[:200] + "…"
            mark = "ok" if event.ok else "fail"
            palette = GREEN if event.ok else RED
            print(f"  {palette}{mark}{RESET}: {body}" if color else f"  {mark}: {body}")
        elif isinstance(event, TextDelta):
            if in_reasoning:
                if color:
                    sys.stdout.write(RESET)
                print()
                in_reasoning = False
            sys.stdout.write(event.text)
            sys.stdout.flush()
    if in_reasoning and color:
        sys.stdout.write(RESET)
    print()


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    args = parse_args()

    from pagentv4 import Agent, Messages

    sandbox = await Sandbox.create(
        backend=args.backend,
        image=args.image,
        workspace_id=args.workspace_id,
        container_ttl_seconds=args.ttl or None,
    )
    try:
        print(f"backend:         {args.backend}")
        print(f"image:           {args.image}")
        print(f"sandbox workdir: {sandbox.workdir}")
        print(f"agent home:      {sandbox.home}")
        ttl_str = f"{args.ttl}s" if args.ttl else "infinity"
        print(f"container ttl:   {ttl_str}")
        print(f"Q: {QUESTION}\n")

        system_prompt = await sandbox.describe()
        agent = Agent(
            DeepSeek(args.model),
            system=system_prompt,
            tools=list(sandbox.tools()),
            max_turns=12,
        )
        runner = Runner()
        await render(runner, agent, QUESTION, Messages())
    finally:
        await sandbox.close()


if __name__ == "__main__":
    asyncio.run(main())
