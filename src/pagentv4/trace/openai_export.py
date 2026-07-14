"""把 pagent 轨迹（messages.jsonl）导出为 OpenAI Chat Completions messages。"""

from __future__ import annotations

import argparse
import json
import sys

from .io import load_messages


def messages_to_openai_json(source: str, *, compact: bool = False) -> str:
    payload = load_messages(source).to_openai()
    return json.dumps(payload, ensure_ascii=False, indent=None if compact else 2)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pagent-openai",
        description="Convert pagent messages.jsonl (or thread id) to OpenAI chat messages JSON.",
    )
    parser.add_argument(
        "source",
        help="messages.jsonl path, thread id under .pagent/threads/, or - for stdin JSONL",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="minified JSON (default: indented)",
    )
    args = parser.parse_args(argv)
    sys.stdout.write(messages_to_openai_json(args.source, compact=args.compact))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
