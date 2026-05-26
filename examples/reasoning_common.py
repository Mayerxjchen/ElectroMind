"""Shared setup for reasoning examples."""

import os
import sys

from pagent import Agent, DeepSeek, Session

QUESTION_EN = (
    "Three boxes are labeled Apples, Oranges, and Apples+Oranges. "
    "Each label is wrong. You may open one box and see one fruit. "
    "Which single box should you open to deduce all correct labels? "
    "Explain your reasoning step by step, then give the box name."
)

QUESTION_ZH = (
    "鸡兔同笼：一个笼子里有鸡和兔，从上面数共 35 个头，从下面数共 94 只脚。"
    "问鸡、兔各有多少只？请分步推理（可设未知数列方程），最后给出答案。"
)

QUESTION = QUESTION_EN

DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"


def use_color():
    return sys.stdout.isatty()


def require_api_key():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit(
            "Please set DEEPSEEK_API_KEY: export DEEPSEEK_API_KEY='your-key'"
        )


def pick_question(argv: list[str]) -> tuple[str, bool]:
    zh = "--zh" in argv
    return (QUESTION_ZH if zh else QUESTION_EN), zh


def make_agent(*, zh: bool = False) -> Agent:
    system = (
        "你是一个乐于推理的助手，解答时请先思考再给出结论。"
        if zh
        else "You are a helpful assistant."
    )
    return Agent(
        DeepSeek("deepseek-v4-flash"),
        Session(system),
        tools=[],
        max_turns=2,
    )
