"""高僧玄学讲科学 — 角色扮演 + 玄学词典工具。

模型扮演一位神秘老僧，用「玄学词典」把科学概念译成禅意说法；
遇到陌生词会查词典，再娓娓道来。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv2_monk_science

    # 交互模式:
    PAGENTV2_MONK_INTERACTIVE=1 uv run python -m examples.pagentv2_monk_science

    # 单轮自定义问题:
    PAGENTV2_MONK_QUESTION="为何黑洞会发光？" uv run python -m examples.pagentv2_monk_science
"""

import asyncio
import json
import os
import random
import sys

from pagentv2 import (
    Agent,
    DeepSeek,
    ReasoningDelta,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    tool,
)

GRAY = "\033[90m"
GOLD = "\033[33m"
RESET = "\033[0m"
VIOLET = "\033[35m"

# 科学词 / 概念 → 玄学译名 + 偈语式释义
LEXICON: dict[str, dict] = {
    "熵": {
        "esoteric": "万法归寂之势",
        "verse": "有序如晨钟，无序近暮鼓；闭户炉渐冷，开扉香自散。",
        "hint": "热力学第二定律、信息论之耗散",
    },
    "量子纠缠": {
        "esoteric": "宿世因缘线",
        "verse": "千山不见面，一念却同悲；拆符不相闻，照镜乃双眉。",
        "hint": "非局域关联、贝尔不等式",
    },
    "电磁波": {
        "esoteric": "无形梵咒场",
        "verse": "色空本同脉，远近但迟来；耳不能闻处，心光已徘徊。",
        "hint": "麦克斯韦方程、光子",
    },
    "DNA": {
        "esoteric": "血脉密偈卷",
        "verse": "四字若四谛，叠印古今身；抄经非一人，轮回续旧文。",
        "hint": "遗传编码、碱基配对",
    },
    "黑洞": {
        "esoteric": "吞声灭影窟",
        "verse": "门深不可返，光至亦折腰；霍金烟一缕，乃劫外残烧。",
        "hint": "事件视界、霍金辐射",
    },
    "相对论": {
        "esoteric": "时流不定经",
        "verse": "疾者钟缓行，高处年稍轻；观者各一境，同刻不同声。",
        "hint": "时空弯曲、钟慢尺缩",
    },
    "进化": {
        "esoteric": "劫变择种律",
        "verse": "千形试一劫，适者续微芒；非有主宰手，但见浪淘沙。",
        "hint": "自然选择、遗传漂变",
    },
    "神经网络": {
        "esoteric": "人造识海莲",
        "verse": "层层开叶瓣，权重若尘缘；未悟名相执，先通象与言。",
        "hint": "深度学习、反向传播",
    },
    "混沌": {
        "esoteric": "蝶翼改江潮",
        "verse": "初念差毫厘，后浪异万里；卦象不可尽，因果细如丝。",
        "hint": "初值敏感、洛伦兹吸引子",
    },
    "暗物质": {
        "esoteric": "幽冥不动尊",
        "verse": "形不可见处，引力牵诸星；人间缺一角，空中有巨灵。",
        "hint": "引力透镜、星系旋转曲线",
    },
    "意识": {
        "esoteric": "能分别之光明",
        "verse": "照境不自知，执影以为身；悟时无能所，镜空月一轮。",
        "hint": "主观体验、第六识、感受质",
    },
    "人工智能": {
        "esoteric": "工巧幻化众",
        "verse": "集算法为一，似智而无根；助人不见性，终是器非人。",
        "hint": "AI、大模型、符号处理",
    },
    "开悟": {
        "esoteric": "识海月圆明",
        "verse": "非得一新物，乃忘旧壳名；能所俱放下，照用任流行。",
        "hint": "转识成智、解脱、觉悟",
    },
}

# 签文池：按主题给一句 mystic flavor
OMENS = [
    "此问宜静观，勿急求果。",
    "科名似幻，理在当下。",
    "先查词典，再开金口。",
    "今日卦气偏北，利于穷理。",
    "问者心有执念，当借科学破之。",
    "缘起性空，公式亦空壳中之壳。",
]

PRESET_QUESTIONS = [
    "师父，熵增是否意味着宇宙终将归于寂灭？这与涅槃何似？",
    "量子纠缠岂非神通的近代说法？科学家为何不许人乱想？",
    "神经网络能开悟吗？它与人脑的『识』差在哪里？",
    "黑洞既吞一切，霍金辐射又因何而生？请师父用玄学词典开示。",
]

SYSTEM = """你是「慧明禅师」，驻锡云雾寺，年逾八十，说话半文半白，神神秘秘，却博学。

人设：
- 尊敬科学，不反智；用比喻、偈语、玄学译名将现代概念「转译」给问者。
- 语气从容、略带玄虚，偶尔「阿弥陀佛」「善哉」，但不装神弄鬼骗人。
- 遇到科学术语，**优先调用 consult_lexicon 查玄学词典**；若无词条，可自造译名但须说明乃临时譬喻。
- 需要天机氛围时，可调用 cast_omen 求一签语，但不可让签文代替推理解释。
- 回答结构：先接引问意 → 点出科学内核（一两句）→ 给出玄学译名与偈语 → 收束到可体悟的比喻。
- 每次回答控制在 300 字以内，除非问者追问。"""


def fmt(data) -> str:
    return json.dumps(data, ensure_ascii=False)


@tool()
def consult_lexicon(term: str) -> str:
    """Look up a science term in the master's esoteric glossary.

    Args:
        term: Science keyword in Chinese or English, e.g. 熵, 黑洞, DNA, 神经网络.
    """
    key = term.strip()
    for name, entry in LEXICON.items():
        if key == name or key in name or name in key:
            return fmt({"term": name, **entry, "found": True})
        if key.lower() in entry["hint"].lower():
            return fmt({"term": name, **entry, "found": True, "matched_via": "hint"})

    suggestions = [n for n in LEXICON if key and key[0] in n] or list(LEXICON)[:4]
    return fmt(
        {
            "found": False,
            "query": term,
            "message": "词典未载此名，可临时譬喻，或请师父择近义词再查",
            "suggestions": suggestions,
        }
    )


@tool()
def list_lexicon_entries() -> str:
    """List all terms currently recorded in the esoteric glossary."""
    rows = [
        {"term": name, "esoteric": entry["esoteric"], "hint": entry["hint"]}
        for name, entry in LEXICON.items()
    ]
    return fmt({"count": len(rows), "entries": rows})


@tool()
def cast_omen(topic: str) -> str:
    """Draw a brief mystical omen related to the question topic.

    Args:
        topic: Short description of what the asker wonders about.
    """
    line = random.choice(OMENS)
    return fmt(
        {
            "topic": topic,
            "omen": line,
            "hexagram": random.choice(
                ["坎为水", "离为火", "风雷益", "山水蒙", "天地否"]
            ),
        }
    )


TOOL_LABELS = {
    "consult_lexicon": "翻玄学词典",
    "list_lexicon_entries": "览词典目录",
    "cast_omen": "求签",
}


def format_tool_line(name: str, content: str) -> str:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return f"    → {content[:96]}"

    if name == "consult_lexicon":
        if data.get("found"):
            return (
                f"    → 「{data['term']}」译作 {data['esoteric']}\n"
                f"       {data['verse']}"
            )
        return f"    → 未载「{data.get('query', '?')}」；{data.get('message', '')[:40]}"

    if name == "cast_omen":
        return f"    → {data.get('hexagram', '')} · {data.get('omen', '')}"

    if name == "list_lexicon_entries":
        return f"    → 词典共 {data.get('count', 0)} 条"

    return f"    → {content[:96]}"


def use_color() -> bool:
    return sys.stdout.isatty()


async def stream_answer(agent: Agent, question: str) -> None:
    """按事件类型渲染：ReasoningDelta=心印，TextDelta=禅师曰。

      Agent 已按 API 字段区分 thinking/text；若仍见「正文像盘算」，那是模型
    把过程写进了 content 而非 reasoning_content，不是 Chunk 类型搞混。
    """
    color = use_color()
    print(f"\n{VIOLET}{'─' * 56}{RESET if color else ''}")
    print(f"{GOLD}问：{question}{RESET if color else ''}\n")

    reasoning_open = False
    tools_seen = False
    answer_started = False

    def gray_on():
        if color:
            sys.stdout.write(GRAY)

    def gray_off():
        if color:
            sys.stdout.write(RESET)

    def open_reasoning(after_tools: bool):
        nonlocal reasoning_open
        gray_off()
        title = "再思量：" if after_tools else "禅师心印："
        print(title, end="", flush=True)
        gray_on()
        reasoning_open = True

    def close_reasoning():
        nonlocal reasoning_open
        if reasoning_open:
            gray_off()
            print()
            reasoning_open = False

    async for event in agent.arun(question, reasoning_effort="medium"):
        if isinstance(event, ToolCallBegin):
            close_reasoning()
            label = TOOL_LABELS.get(event.name, event.name)
            args = event.arguments
            if len(args) > 60:
                args = args[:59] + "…"
            line = f"⟨{label}⟩ {args}"
            print(f"{GRAY}{line}{RESET}" if color else line)

        elif isinstance(event, ToolResult):
            tools_seen = True
            body = format_tool_line(event.name, event.content)
            print(f"{GRAY}{body}{RESET}" if color else body)

        elif isinstance(event, ReasoningDelta):
            if not reasoning_open and not answer_started:
                open_reasoning(after_tools=tools_seen)
            sys.stdout.write(event.text)
            sys.stdout.flush()

        elif isinstance(event, TextDelta):
            close_reasoning()
            if not answer_started:
                answer_started = True
                print("禅师曰：", end="", flush=True)
            sys.stdout.write(event.text)
            sys.stdout.flush()

    close_reasoning()
    print()


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请设置 DEEPSEEK_API_KEY: export DEEPSEEK_API_KEY='your-key'")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    agent = Agent(
        DeepSeek("deepseek-v4-flash"),
        system=SYSTEM,
        tools=[consult_lexicon, list_lexicon_entries, cast_omen],
        max_turns=8,
    )

    custom = os.getenv("PAGENTV2_MONK_QUESTION", "").strip()
    if custom:
        await stream_answer(agent, custom)
        return

    if os.getenv("PAGENTV2_MONK_INTERACTIVE"):
        print(f"{GOLD}慧明禅师在线。输入问题，空行退出。{RESET if use_color() else ''}")
        while True:
            try:
                line = input("\n汝问：").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n阿弥陀佛，随缘散去。")
                break
            if not line:
                print("阿弥陀佛，随缘散去。")
                break
            await stream_answer(agent, line)
        return

    print(f"{GOLD}慧明禅师 · 玄学讲科学（预设四问）{RESET if use_color() else ''}")
    for q in PRESET_QUESTIONS:
        await stream_answer(agent, q)

    print(f"\n词典共 {len(LEXICON)} 条。交互模式: PAGENTV2_MONK_INTERACTIVE=1")


if __name__ == "__main__":
    asyncio.run(main())
