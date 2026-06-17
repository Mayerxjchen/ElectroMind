"""Pick a cover from several image URLs (live API).

DeepSeek Chat Completions is **text-only** (no ``image_url`` parts). This demo
passes each candidate as label + URL + short description, then asks the model
to compare and **paste URLs** in the answer.

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv2_pick_image

    PAGENTV2_REASONING_EFFORT=high uv run python -m examples.pagentv2_pick_image

Offline multimodal input smoke: ``uv run python -m examples.pagentv2_images_demo``
"""

import asyncio
import os
import sys

from pagentv2 import Agent, DeepSeek, Message, ReasoningDelta, TextDelta, reply_text

# label, url, text description (model cannot see pixels on DeepSeek)
CANDIDATES = [
    (
        "A · 山景湖水",
        "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/Fronalpstock_lake.jpg/640px-Fronalpstock_lake.jpg",
        "远景雪山与高山湖，开阔天空，绿色山坡，偏自然旅行杂志。",
    ),
    (
        "B · 城市夜景",
        "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6e/Golde33443.jpg/640px-Golde33443.jpg",
        "河畔城市夜景，暖色灯光倒映水面，建筑轮廓，偏都市/金融氛围。",
    ),
    (
        "C · 极简静物",
        "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/320px-PNG_transparency_demonstration_1.png",
        "PNG 透明背景上的彩色骰子，像格式演示图，构图简单、留白多。",
    ),
]

QUESTION = (
    "上面三张是博客封面候选（A/B/C），你只能根据文字描述和链接来比较。"
    "请先在心里逐张分析：主体、色调、构图、信息密度、是否像科技博客，"
    "以及首页头图叠标题时的可读性。推理要充分。"
    "正式回答：逐张简评；提到某张图必须写完整 https 链接；"
    "最后一行「推荐链接：」+ 一个 URL。"
)

SYSTEM = (
    "你是视觉设计顾问。用户给出图片的文字描述与 URL（你看不到像素）。"
    "先在推理里做多维度比较，再下结论；引用图时写完整 URL。"
)

REASONING_EFFORT = os.getenv("PAGENTV2_REASONING_EFFORT", "high")

GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"


def use_color() -> bool:
    return sys.stdout.isatty()


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit(
            "Please set DEEPSEEK_API_KEY: export DEEPSEEK_API_KEY='your-key'"
        )

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    agent = Agent(DeepSeek("deepseek-v4-flash"), system=SYSTEM)

    print(
        f"{BOLD}候选（文本 + URL，无 image_url 多模态）{RESET if use_color() else ''}"
    )
    for label, url, desc in CANDIDATES:
        agent.messages += Message.user(f"{label}\n链接: {url}\n描述: {desc}")
        print(f"  • {label}")
        print(f"    {url}")
        print(f"    {desc}")

    print(f"\n{BOLD}Q:{RESET if use_color() else ''} {QUESTION}")
    if use_color():
        sys.stdout.write(GRAY)
    print("reasoning: ", end="", flush=True)

    answer_started = False

    async for event in agent.arun(QUESTION, reasoning_effort=REASONING_EFFORT):
        if isinstance(event, ReasoningDelta):
            sys.stdout.write(event.text)
            sys.stdout.flush()

        elif isinstance(event, TextDelta):
            if not answer_started:
                answer_started = True
                if use_color():
                    sys.stdout.write(RESET)
                print("\nanswer: ", end="", flush=True)
            sys.stdout.write(event.text)
            sys.stdout.flush()

    if use_color() and not answer_started:
        sys.stdout.write(RESET)
    print()

    answer = reply_text(list(agent.messages))
    if "http" not in answer:
        print("（模型未在正文里输出可识别的 http 链接）")

    print(f"\n会话消息数: {len(agent.messages)}")


if __name__ == "__main__":
    asyncio.run(main())
