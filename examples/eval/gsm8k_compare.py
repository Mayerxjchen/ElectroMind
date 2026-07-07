"""GSM8K 小子集 — 对比 SimpleQuestionAnswerRunner vs AgenticRunner(+calc)。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run --with datasets python -m examples.eval.gsm8k_compare
    uv run --with datasets python -m examples.eval.gsm8k_compare --sample hard --limit 30 -v
    uv run --with datasets python -m examples.eval.gsm8k_compare --sample head --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
from dataclasses import dataclass

from pagentv4 import AgenticRunner, RunConfig, SimpleQuestionAnswerRunner, tool

SIMPLE_SYSTEM = (
    "You solve grade-school math word problems. "
    "Think step by step, then reply with the final number only."
)
AGENTIC_SYSTEM = (
    "You solve grade-school math word problems. "
    "Use the calc tool for arithmetic. "
    "Reply with the final number only."
)
QUESTION_SUFFIX = "\n\nGive the final answer as a single number."


@tool()
def calc(expression: str) -> str:
    """Evaluate a Python arithmetic expression.

    Args:
        expression: digits, + - * / ( ) and spaces only.
    """
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        return "error: arithmetic only"
    return str(eval(expression, {"__builtins__": {}}, {}))


@dataclass(frozen=True, slots=True)
class RowScore:
    index: int
    question: str
    gold: str | None
    pred: str | None
    ok: bool


def reasoning_steps(answer: str) -> int:
    chain = answer.split("####")[0]
    return sum(1 for line in chain.strip().splitlines() if line.strip())


def load_dataset_full(split: str):
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit(
            "需要 datasets：uv run --with datasets python -m examples.eval.gsm8k_compare"
        ) from exc
    return load_dataset("openai/gsm8k", "main", split=split)


def select_rows(
    full,
    *,
    limit: int,
    sample: str,
    offset: int,
    seed: int,
):
    size = len(full)
    count = min(limit, size) if limit > 0 else size

    if sample == "head":
        start = offset
        end = min(offset + count, size)
        return full.select(range(start, end)), f"{full.split}[{start}:{end}]"

    if sample == "random":
        rng = random.Random(seed)
        indices = sorted(rng.sample(range(size), count))
        return full.select(indices), f"{full.split} random n={count} seed={seed}"

    scored = [
        (reasoning_steps(row["answer"]), len(row["question"]), index)
        for index, row in enumerate(full)
    ]
    scored.sort(reverse=True)
    indices = [index for _, _, index in scored[:count]]
    avg_steps = sum(s for s, _, _ in scored[:count]) / count if count else 0
    return (
        full.select(indices),
        f"{full.split} hard n={count} avg_steps={avg_steps:.1f}",
    )


def load_rows(split: str, limit: int, *, sample: str, offset: int, seed: int):
    full = load_dataset_full(split)
    rows, label = select_rows(
        full, limit=limit, sample=sample, offset=offset, seed=seed
    )
    return rows, label


def gold_number(answer: str) -> str | None:
    if "####" not in answer:
        return None
    return answer.split("####")[-1].strip().replace(",", "")


def predicted_number(text: str) -> str | None:
    numbers = re.findall(r"-?\d+", text.replace(",", ""))
    return numbers[-1] if numbers else None


def score_row(index: int, question: str, gold_answer: str, pred_text: str) -> RowScore:
    truth = gold_number(gold_answer)
    guess = predicted_number(pred_text)
    ok = truth is not None and guess is not None and guess == truth
    return RowScore(index=index, question=question, gold=truth, pred=guess, ok=ok)


def clip(text: str, limit: int = 100) -> str:
    one_line = text.replace("\n", " ")
    return one_line if len(one_line) <= limit else one_line[: limit - 3] + "..."


def print_progress(
    label: str,
    index: int,
    total: int,
    *,
    phase: str,
    result: RowScore | None = None,
    answer: str = "",
    verbose: bool = False,
) -> None:
    if phase == "start":
        print(f"  [{label}] {index}/{total} running ...", flush=True)
        if verbose:
            assert result is not None
            print(f"       Q: {clip(result.question)}", flush=True)
        return

    assert result is not None
    mark = "ok" if result.ok else "FAIL"
    print(
        f"  [{label} {mark}] {index}/{total} gold={result.gold} pred={result.pred}",
        flush=True,
    )
    if verbose and answer:
        print(f"       A: {clip(answer, 200)}", flush=True)


async def eval_simple(rows, *, verbose: bool) -> list[RowScore]:
    runner = SimpleQuestionAnswerRunner(
        RunConfig(system=SIMPLE_SYSTEM, max_turns=1),
    )
    results: list[RowScore] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        placeholder = RowScore(
            index=index, question=row["question"], gold=None, pred=None, ok=False
        )
        print_progress(
            "simple", index, total, phase="start", result=placeholder, verbose=verbose
        )
        prompt = row["question"] + QUESTION_SUFFIX
        ans = await runner.run(prompt)
        result = score_row(index, row["question"], row["answer"], ans)
        results.append(result)
        print_progress(
            "simple",
            index,
            total,
            phase="done",
            result=result,
            answer=ans,
            verbose=verbose,
        )
    return results


async def eval_agentic(rows, *, verbose: bool) -> list[RowScore]:
    runner = AgenticRunner(
        RunConfig(system=AGENTIC_SYSTEM, max_turns=6),
        tools=[calc],
    )
    results: list[RowScore] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        placeholder = RowScore(
            index=index, question=row["question"], gold=None, pred=None, ok=False
        )
        print_progress(
            "agentic", index, total, phase="start", result=placeholder, verbose=verbose
        )
        prompt = row["question"] + QUESTION_SUFFIX
        ans = await runner.run(prompt, tools=[calc])
        result = score_row(index, row["question"], row["answer"], ans)
        results.append(result)
        print_progress(
            "agentic",
            index,
            total,
            phase="done",
            result=result,
            answer=ans,
            verbose=verbose,
        )
    return results


def summarize(name: str, results: list[RowScore]) -> str:
    correct = sum(int(r.ok) for r in results)
    total = len(results)
    pct = correct / total if total else 0.0
    return f"{name}: {correct}/{total} = {pct:.1%}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare SimpleQuestionAnswerRunner vs AgenticRunner on GSM8K"
    )
    parser.add_argument("--split", default="test", choices=("train", "test"))
    parser.add_argument(
        "--limit", type=int, default=20, help="subset size (default 20)"
    )
    parser.add_argument(
        "--sample",
        default="hard",
        choices=("hard", "random", "head"),
        help="hard=多步推理题(默认), random=随机, head=前 N 题(偏简单)",
    )
    parser.add_argument("--offset", type=int, default=0, help="head 模式起始下标")
    parser.add_argument("--seed", type=int, default=0, help="random 模式种子")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="also print question snippet and model answer",
    )
    return parser.parse_args()


async def main() -> None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    args = parse_args()
    rows, subset_label = load_rows(
        args.split,
        args.limit,
        sample=args.sample,
        offset=args.offset,
        seed=args.seed,
    )
    print(f"GSM8K {subset_label}\n")

    print("Running SimpleQuestionAnswerRunner ...")
    simple = await eval_simple(rows, verbose=args.verbose)
    print()

    print("Running AgenticRunner (+ calc) ...")
    agentic = await eval_agentic(rows, verbose=args.verbose)
    print()

    print(summarize("SimpleQuestionAnswerRunner", simple))
    print(summarize("AgenticRunner (+calc)     ", agentic))

    failed_both = [
        (s, a) for s, a in zip(simple, agentic, strict=True) if not s.ok and not a.ok
    ]
    if failed_both:
        print("\nBoth failed:")
        for s, _ in failed_both:
            print(f"  #{s.index} gold={s.gold}  Q: {clip(s.question, 80)}")


if __name__ == "__main__":
    asyncio.run(main())
