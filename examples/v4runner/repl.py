"""v4 REPL —— 交互式对话，一个 thread_id 就是一台伴身电脑 + 一段对话历史。

一个 thread 绑死三件事：沙箱配置（spec.json）、消息历史（messages.jsonl）、
文件工作目录（workspace/），全部落在 `<cwd>/.pagent/threads/<thread_id>/` 里。

围绕 thread 你能做的就四件事：

- **建**：不带 `--thread-id` 直接跑，自动生成 `thread-<时间戳>`，
  用命令行写 spec.json 冻结、开 sandbox。
- **在里面干活**：接着聊、让 agent 跑工具；消息进 messages.jsonl，文件进 workspace/。
  带 `--thread-id foo` 就续上——sandbox 按 spec 重建，历史全部读回来。
- **停**：`/exit` 或 Ctrl-D，sandbox 关掉，thread 原样留在磁盘等下次。
- **切到另一条**：换个 `--thread-id`，或不带参数再跑一次新建一条，各自独立的
  spec / 消息 / workspace。

spec.json 首次写完就冻结：后续带同一个 `--thread-id` 只从 spec.json 读，命令行覆盖会被
忽略并在启动横幅提示。想改配置就手改 spec.json，或新建一条 thread。

`Runner.session()` 每次都会造一个 Sandbox 又关掉；REPL 场景要在多轮之间保留 sandbox
和消息，所以这里显式持有：Sandbox 只造一次，`sandbox.describe()` 讲清它有哪些工具，
`sandbox.tools()` 把工具挂给 Agent；Skills 默认从 `PAGENT_SKILLS_DIR` +
`./.pagent/skills/` + `~/.pagent/skills/` 加载，`--skills-dir` 可再补自定义路径。

内置命令：
    /exit  或  /quit    退出
    /pwd                打印 sandbox 宿主目录
    /ls                 列 sandbox home 下的文件
    /skills             列出当前加载的 skill
    /history            打印当前 messages 摘要

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.v4runner.repl                    # 新建一条 thread
    uv run python -m examples.v4runner.repl --thread-id demo   # 续上 demo
    uv run python -m examples.v4runner.repl --backend podman \\
        --image pagent-podman-demo:latest --container-ttl 600
    uv run python -m examples.v4runner.repl --backend ssh --ssh-host my-server
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

from pagentv4 import (
    Agent,
    DeepSeek,
    JsonlConversationStore,
    Messages,
    ReasoningDelta,
    Runner,
    Sandbox,
    SkillRegistry,
    SshConnection,
    TextDelta,
    Thread,
    ToolCallBegin,
    ToolResult,
    build_skills_system_prompt,
    make_use_skill_tool,
)

CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
RED = "\033[31m"
BLUE = "\033[34m"
RESET = "\033[0m"

EXTRA_SYSTEM = "你是 pagent 。回答简短直接。"


def use_color() -> bool:
    return sys.stdout.isatty()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--thread-id",
        default=None,
        help="续上已有 thread；落在 <cwd>/.pagent/threads/<id>/。"
        "不传就新建一条 thread-<时间戳>",
    )
    parser.add_argument(
        "--skills-dir",
        action="append",
        default=[],
        help="额外的 skill 根目录，可传多次；默认路径仍会加载",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="DeepSeek 模型名（首次冻结时写入 spec；后续无视）",
    )
    parser.add_argument(
        "--system",
        default=None,
        help="追加到 sandbox 自描述后面的 system prompt 补充（首次冻结时写入 spec）",
    )
    parser.add_argument(
        "--backend",
        default=None,
        choices=["local", "docker", "podman", "ssh"],
        help="sandbox 后端；docker/podman 需要 --image，ssh 需要 --ssh-host",
    )
    parser.add_argument(
        "--image",
        default=None,
        help="容器镜像；docker/podman backend 必填",
    )
    parser.add_argument(
        "--container-ttl",
        type=int,
        default=None,
        help="容器寿命秒数；防止宿主 kill -9 后残留容器，默认无限期",
    )
    parser.add_argument(
        "--ssh-host",
        default=None,
        help="ssh backend 的 ~/.ssh/config 别名；--backend ssh 必填",
    )
    parser.add_argument(
        "--ssh-config",
        default=None,
        help="ssh_config 路径，默认 ~/.ssh/config",
    )
    parser.add_argument(
        "--ssh-workdir",
        default=None,
        help="ssh backend 的远端工作目录，默认 ~/agent",
    )
    return parser.parse_args()


def overrides_from_args(args) -> dict:
    """把命令行里显式给的字段拼成 dict；只装用户真的传过的键。"""
    kwargs: dict = {}
    if args.backend is not None:
        kwargs["backend"] = args.backend
    if args.image is not None:
        kwargs["image"] = args.image
    if args.container_ttl is not None:
        kwargs["container_ttl_seconds"] = args.container_ttl
    if args.ssh_host is not None:
        kwargs["ssh_host"] = args.ssh_host
    if args.ssh_config is not None:
        kwargs["ssh_config"] = args.ssh_config
    if args.ssh_workdir is not None:
        kwargs["ssh_workdir"] = args.ssh_workdir
    if args.model is not None:
        kwargs["model"] = args.model
    if args.system is not None:
        kwargs["system"] = args.system
    return kwargs


async def build_sandbox(thread: Thread) -> Sandbox:
    """按 thread.spec 造 sandbox；workdir 直接落到 <thread>/workspace/。"""
    spec = thread.spec
    workdir = str(thread.workspace_path)

    if spec.backend == "local":
        return await Sandbox.create(backend="local", workdir=workdir)

    if spec.backend in ("docker", "podman"):
        if not spec.image:
            raise SystemExit(f"--backend {spec.backend} 需要 --image <镜像>")
        return await Sandbox.create(
            backend=spec.backend,
            workdir=workdir,
            image=spec.image,
            container_ttl_seconds=spec.container_ttl_seconds,
        )

    if not spec.ssh_host:
        raise SystemExit("--backend ssh 需要 --ssh-host <ssh_config alias>")
    conn = SshConnection.from_ssh_config(
        spec.ssh_host,
        config_path=spec.ssh_config,
        workdir=spec.ssh_workdir,
    )
    return await Sandbox.create(
        backend="ssh",
        workdir=workdir,
        connection=conn.to_dict(),
    )


async def render_events(runner, agent, user_input, messages, color, conversation_id):
    in_reasoning = False
    async for event in runner.arun(
        agent, user_input, messages, conversation_id=conversation_id
    ):
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


async def prompt(color) -> str | None:
    marker = f"{BLUE}you>{RESET} " if color else "you> "
    try:
        return await asyncio.to_thread(input, marker)
    except (EOFError, KeyboardInterrupt):
        return None


async def handle_command(cmd, sandbox, messages, skills) -> bool:
    """内置命令。返回 True 表示要退出 REPL。"""
    if cmd in ("/exit", "/quit"):
        return True
    if cmd == "/pwd":
        print(sandbox.workdir)
        return False
    if cmd == "/ls":
        entries = await sandbox.files.list(sandbox.home)
        for entry in entries:
            tag = "d" if entry.is_dir else "f"
            print(f"  {tag} {entry.name}")
        return False
    if cmd == "/skills":
        if not skills.names():
            print("(no skills loaded)")
            return False
        for skill in skills.list():
            print(f"  {skill.name}: {skill.description}")
        return False
    if cmd == "/history":
        for message in messages.data:
            preview = str(message.content)[:80].replace("\n", " ")
            print(f"  [{message.role}] {preview}")
        return False
    print(f"unknown command: {cmd}")
    return False


async def main():
    args = parse_args()
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    color = use_color()

    thread_id = args.thread_id or f"thread-{datetime.now():%Y%m%d-%H%M%S}"

    thread = Thread.open(thread_id, overrides=overrides_from_args(args))
    verb = "created" if thread.created else "resumed"
    print(f"{verb} thread {thread.id!r}  ->  {thread.root}")
    if thread.ignored_overrides:
        print(
            f"note: 现有 spec.json 冻结中，命令行以下字段被忽略："
            f"{', '.join(thread.ignored_overrides)}"
            f"（改配置请手改 spec.json，或不带 --thread-id 新建一条 thread）"
        )

    sandbox = await build_sandbox(thread)
    store = JsonlConversationStore(root=thread.root)

    extra_system = thread.spec.system or EXTRA_SYSTEM
    model_name = thread.spec.model or "deepseek-v4-flash"

    skills = SkillRegistry.from_defaults(*args.skills_dir)
    mount = await sandbox.install_skills(skills) if skills.names() else {}
    tools = list(sandbox.tools())
    if skills.names():
        tools.append(make_use_skill_tool(skills, mount))

    computer_desc = await sandbox.describe()
    skills_prompt = build_skills_system_prompt(skills, mount)
    system_prompt = "\n".join(
        part for part in (computer_desc, skills_prompt, extra_system) if part
    )

    messages = Messages()
    conversation_id = thread.messages_conversation_id
    for message in store.load(conversation_id).data:
        messages += message

    print(f"sandbox backend: {thread.spec.backend}")
    print(f"sandbox workdir: {sandbox.workdir}")
    print(f"agent home:      {sandbox.home}")
    print(f"skills:          {', '.join(skills.names()) or '(none)'}")
    print("commands: /exit /pwd /ls /skills /history")
    print()

    provider = DeepSeek(model_name)
    agent = Agent(provider, system=system_prompt, tools=tools, max_turns=12)
    runner = Runner(store=store)

    try:
        while True:
            line = await prompt(color)
            if line is None:
                print()
                break
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                if await handle_command(line, sandbox, messages, skills):
                    break
                continue
            await render_events(runner, agent, line, messages, color, conversation_id)
    finally:
        await sandbox.close()


if __name__ == "__main__":
    asyncio.run(main())
