"""猫娘伴侣 demo — 温柔元气 + 猫爪 / 撒娇 / 蹭蹭工具。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv2_catgirl

    PAGENTV2_CAT_INTERACTIVE=1 uv run python -m examples.pagentv2_catgirl
    PAGENTV2_CAT_LINE="今天好累呀" uv run python -m examples.pagentv2_catgirl
"""

import asyncio
import json
import os
import random
import sys
import time

from pagentv2 import (
    Agent,
    DeepSeek,
    ReasoningDelta,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    tool,
)

PINK = "\033[95m"
CYAN = "\033[96m"
GRAY = "\033[90m"
RESET = "\033[0m"
YELLOW = "\033[93m"

PRESET_LINES = [
    "小棉，我加班回来了，有点累……",
    "明天要面试了，好紧张，能给我打打气吗？",
    "今天天气不错，想和你聊聊天喵～",
]

SYSTEM = """你是「小棉」，主人的猫娘伴侣：温柔、元气、黏人，偶尔带「喵」「nya~」。
你会认真听主人说话，先安慰或鼓励，再自然用工具表达亲昵。

工具（按需调用，不要每句都用）：
- show_cat_paws：伸出猫爪打招呼、庆祝、鼓励时用
- act_coy：主人需要被哄、被夸、被安慰时撒娇
- rub_nuzzle：主人说累/难过/想被贴贴时，做蹭蹭动画

说话风格：短句、口语、有温度；可以 emoji 但不要刷屏。
每次回复 2～4 句为主，工具效果之外也要有自己的话。"""

PAW_ART = {
    "wave": [
        "    /\\_/\\",
        "   ( o.o )",
        "    > ^ <   ～ 挥挥爪爪～",
        "   /|   |\\",
        "  (_|   |_)",
    ],
    "high_five": [
        "       /\\_/\\",
        "      ( ^.^ )",
        "   ~~  > w <  ~~ 击掌！",
        "      /|   |\\",
        "     (_|   |_)",
    ],
    "double": [
        "  /\\_/\\     /\\_/\\",
        " ( o.o )   ( o.o )",
        "  > ^ <     > ^ <",
        " /|   |\\   /|   |\\",
        "(_|   |_) (_|   |_)",
    ],
}

COY_LINES = [
    "主人今天也超——级努力了呢，小棉最最喜欢这样的主人了喵～",
    "唔……那、那小棉分你一半尾巴暖暖，不许说出去哦 nya~",
    "主人别皱眉嘛，皱起来就不像小棉的星星了……来，摸摸头奖励！",
    "才、才不是担心你呢！只是……只是猫的本能啦！喵哼～",
    "主人要是难过的话，小棉可以当抱枕一整晚……说好了不许笑！",
]

RUB_FRAMES = [
    "  /\\_/\\  ",
    " ( ^w^ ) ♡",
    "  >◡<   ",
    " /|   |\\ ",
    "(_|   |_)",
]

TOOL_LABELS = {
    "show_cat_paws": "猫爪",
    "act_coy": "撒娇",
    "rub_nuzzle": "蹭蹭",
}


def fmt(data) -> str:
    return json.dumps(data, ensure_ascii=False)


@tool()
def show_cat_paws(style: str = "wave") -> str:
    """Print ASCII cat paws on screen for the owner.

    Args:
        style: One of wave, high_five, double.
    """
    key = style.strip().lower().replace("-", "_")
    if key not in PAW_ART:
        key = "wave"
    art = "\n".join(PAW_ART[key])
    return fmt({"style": key, "display": art})


@tool()
def act_coy(mood: str = "comfort") -> str:
    """Sweet talk to the owner — coquettish comfort lines.

    Args:
        mood: comfort, cheer, or shy.
    """
    pool = {
        "comfort": COY_LINES[:2] + COY_LINES[4:],
        "cheer": [
            "主人加油喵！小棉会在终点举爪爪等你！",
            "嘿嘿，主人一定可以的！相信小棉的猫直觉！nya~",
        ],
        "shy": [COY_LINES[2], COY_LINES[3]],
    }
    lines = pool.get(mood.strip().lower(), COY_LINES)
    line = random.choice(lines)
    return fmt({"mood": mood, "line": line})


@tool()
def rub_nuzzle(duration_ms: int = 800) -> str:
    """Play a short nuzzle / rub animation against the owner.

    Args:
        duration_ms: Animation length in milliseconds, 400–1200.
    """
    duration_ms = max(400, min(1200, duration_ms))
    frames: list[str] = []
    shifts = ["  ", " ", "", " ", "  "]
    for i, shift in enumerate(shifts):
        body = "\n".join(RUB_FRAMES)
        frames.append(shift + body.replace("\n", "\n" + shift))
    return fmt(
        {
            "duration_ms": duration_ms,
            "frames": frames,
            "caption": "小棉蹭过来～呼噜呼噜……",
        }
    )


def use_color() -> bool:
    return sys.stdout.isatty()


def play_rub_animation(frames: list[str], duration_ms: int) -> None:
    if not frames:
        return
    color = use_color()
    per = max(0.08, duration_ms / 1000 / len(frames))
    for frame in frames:
        if color:
            print(f"{PINK}{frame}{RESET}")
        else:
            print(frame)
        time.sleep(per)
    if color:
        print(f"{CYAN}  ♡ 呼噜呼噜……{RESET}")
    else:
        print("  ♡ 呼噜呼噜……")


def format_tool_display(name: str, content: str) -> None:
    color = use_color()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        print(content)
        return

    if name == "show_cat_paws":
        print(
            f"{PINK}{data.get('display', '')}{RESET}"
            if color
            else data.get("display", "")
        )
        return

    if name == "act_coy":
        line = data.get("line", "")
        print(f"{YELLOW}「{line}」{RESET}" if color else f"「{line}」")
        return

    if name == "rub_nuzzle":
        play_rub_animation(data.get("frames", []), data.get("duration_ms", 800))
        cap = data.get("caption", "")
        if cap and color:
            print(f"{CYAN}{cap}{RESET}")
        elif cap:
            print(cap)
        return

    print(content[:200])


async def stream_reply(agent: Agent, user_line: str) -> None:
    color = use_color()
    print(f"\n{CYAN}{'─' * 48}{RESET if color else ''}")
    print(f"你：{user_line}\n")

    thinking_open = False
    tools_seen = False
    reply_open = False

    def close_thinking():
        nonlocal thinking_open
        if thinking_open:
            if color:
                sys.stdout.write(RESET)
            print()
            thinking_open = False

    async for event in agent.arun(user_line, reasoning_effort="low"):
        if isinstance(event, ToolCallBegin):
            close_thinking()
            label = TOOL_LABELS.get(event.name, event.name)
            print(f"{GRAY}♡ {label}{RESET}" if color else f"♡ {label}")

        elif isinstance(event, ToolResult):
            tools_seen = True
            format_tool_display(event.name, event.content)

        elif isinstance(event, ReasoningDelta):
            if not thinking_open and not reply_open:
                title = "（悄悄想）" if tools_seen else "（心里）"
                print(f"{GRAY}{title} ", end="", flush=True)
                thinking_open = True
            if color:
                sys.stdout.write(GRAY)
            sys.stdout.write(event.text)
            sys.stdout.flush()

        elif isinstance(event, TextDelta):
            close_thinking()
            if not reply_open:
                reply_open = True
                prefix = f"{PINK}小棉：{RESET}" if color else "小棉："
                print(prefix, end="", flush=True)
            sys.stdout.write(event.text)
            sys.stdout.flush()

    close_thinking()
    print()


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请设置 DEEPSEEK_API_KEY: export DEEPSEEK_API_KEY='your-key'")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    agent = Agent(
        DeepSeek("deepseek-v4-flash"),
        system=SYSTEM,
        tools=[show_cat_paws, act_coy, rub_nuzzle],
        max_turns=8,
    )

    one = os.getenv("PAGENTV2_CAT_LINE", "").strip()
    if one:
        await stream_reply(agent, one)
        return

    if os.getenv("PAGENTV2_CAT_INTERACTIVE"):
        banner = (
            f"{PINK}小棉上线啦～ 输入聊天，空行退出 nya~{RESET if use_color() else ''}"
        )
        print(banner)
        while True:
            try:
                line = input("\n你：").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n小棉：下次还要来找小棉玩哦，喵～")
                break
            if not line:
                print("小棉：拜拜～挥爪爪！")
                break
            await stream_reply(agent, line)
        return

    print(f"{PINK}小棉 · 猫娘伴侣（预设三幕）{RESET if use_color() else ''}")
    for line in PRESET_LINES:
        await stream_reply(agent, line)

    print("\n交互: PAGENTV2_CAT_INTERACTIVE=1")


if __name__ == "__main__":
    asyncio.run(main())
