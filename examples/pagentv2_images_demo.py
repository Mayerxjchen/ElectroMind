"""Pick among candidate images — fake stream, no API key.

User messages may include :class:`~pagentv2.ImageUrl` (multimodal input).
Assistant replies stay plain :class:`~pagentv2.TextChunk` (URLs remain text).

Usage:
    uv run python -m examples.pagentv2_images_demo
"""

import asyncio
import sys

from pagentv2 import Agent, Message, TextChunk, ThinkingChunk

GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"

CANDIDATES = [
    ("方案 A · 山景", "https://cdn.example.com/covers/mountain.jpg"),
    ("方案 B · 夜景", "https://cdn.example.com/covers/city-night.png"),
    ("方案 C · 扁平", "assets/hero-flat.png"),
]

USER_QUESTION = (
    "上面三张候选封面，哪张最适合科技博客？"
    "逐张简评，最后明确推荐一张（写出对应链接或文件名）。"
)

FAKE_ANSWER_DELTAS = [
    ("thinking", "任务：科技博客封面，不是旅游/美食。先定评判维度："),
    ("thinking", "科技感、留白、标题区、色彩是否偏冷/中性、是否过于具象。"),
    ("thinking", "A 山景：自然、宁静，联想户外而非技术；绿色占比高，偏温暖。"),
    ("thinking", "B 夜景：城市灯光、纵深、冷色多，最接近 SaaS/技术媒体气质。"),
    ("thinking", "C 扁平 PNG：干净、现代，但像素材演示图，品牌辨识度弱。"),
    (
        "thinking",
        "若头图要压大字，B 暗部多、对比强；A 天空亮区可能吃字；C 中间透明块要避。",
    ),
    ("thinking", "综合：B 最稳。下面正式回答并贴链接。"),
    ("text", "三张对比：\n"),
    ("text", "• A "),
    ("text", "https://cdn.example.com/covers/mountain"),
    ("text", ".jpg 太自然风光；\n"),
    ("text", "• B "),
    ("text", "https://cdn.example.com/covers/city-night.png"),
    ("text", " 夜景霓虹，科技感强；\n"),
    ("text", "• C "),
    ("text", "hero-flat.png"),
    ("text", " 扁平插画，简洁但略素。\n\n"),
    ("text", "推荐：方案 B，最终用 "),
    ("text", "https://cdn.example.com/covers/city-night.png"),
    ("text", " 做封面。"),
]


class FakeStreamChunk:
    def __init__(self, *, content=None, reasoning=None):
        delta = type(
            "Delta",
            (),
            {"content": content, "reasoning_content": reasoning},
        )()
        self.choices = [type("Choice", (), {"delta": delta})()]


class FakeProvider:
    async def complete(self, messages, tools=None, **run_kwargs):
        async def stream():
            for kind, text in FAKE_ANSWER_DELTAS:
                if kind == "thinking":
                    yield FakeStreamChunk(reasoning=text)
                else:
                    yield FakeStreamChunk(content=text)

        return stream()


def use_color() -> bool:
    return sys.stdout.isatty()


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    provider = FakeProvider()
    agent = Agent(
        provider,
        system="你是设计顾问。比较用户给出的图片候选，给出明确推荐。",
    )

    print(f"{BOLD}候选封面{RESET if use_color() else ''}")
    for label, url in CANDIDATES:
        agent.messages += Message.user(f"{label}: {url}")
        agent.messages += Message.user_image(url)
        print(f"  • {label}")
        print(f"    {url}")

    print(f"\n{BOLD}Q:{RESET if use_color() else ''} {USER_QUESTION}")
    if use_color():
        sys.stdout.write(GRAY)
    print("reasoning: ", end="", flush=True)

    answer_started = False
    answer_parts: list[str] = []

    async for msg in agent.arun(USER_QUESTION, return_type="message"):
        chunk = msg.content

        if isinstance(chunk, ThinkingChunk):
            sys.stdout.write(chunk.text)
            sys.stdout.flush()

        elif isinstance(chunk, TextChunk):
            if not answer_started:
                answer_started = True
                if use_color():
                    sys.stdout.write(RESET)
                print("\nanswer: ", end="", flush=True)
            answer_parts.append(chunk.text)
            sys.stdout.write(chunk.text)
            sys.stdout.flush()

    if use_color() and not answer_started:
        sys.stdout.write(RESET)

    print()
    answer = "".join(answer_parts)
    if "city-night.png" in answer:
        print(f"{BOLD}推荐链接在回答正文中（TextChunk）{RESET if use_color() else ''}")
    print(f"\n会话消息数: {len(agent.messages)}")


if __name__ == "__main__":
    asyncio.run(main())
