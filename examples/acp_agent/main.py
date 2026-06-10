"""Run pagent as an ACP agent over stdio (Zed, JetBrains, VS Code, etc.).

Usage (from repo root):

    export DEEPSEEK_API_KEY="your-key"
    uv sync --group dev --extra acp --extra search
    uv run python examples/acp_agent/main.py

Optional:
    PAGENT_ACP_SYSTEM_PROMPT_FILE=~/.pagent-acp-prompt.md  # append custom instructions

Zed settings (~/.config/zed/settings.json):

    {
      "agent_servers": {
        "pagent": {
          "command": "uv",
          "args": ["run", "--directory", "/path/to/pagent", "python", "examples/acp_agent/main.py"],
          "env": { "DEEPSEEK_API_KEY": "..." }
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_ACP_DIR = Path(__file__).resolve().parent
if str(_ACP_DIR) not in sys.path:
    sys.path.insert(0, str(_ACP_DIR))

from prompt import load_system_prompt
from tools import calc, glob_paths, grep_code

from pagent import Agent, DeepSeek, Session, bash, clock, readfile, region, web_search
from pagent_acp import run_stdio

TOOLS = [
    readfile,
    grep_code,
    glob_paths,
    bash,
    web_search,
    calc,
    clock,
    region,
]


def make_agent(cwd: str) -> Agent:
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is required", file=sys.stderr)
        raise SystemExit(1)

    os.chdir(cwd)

    model = os.getenv("PAGENT_ACP_MODEL", "deepseek-v4-flash")
    tool_names = [t.name for t in TOOLS]
    system = load_system_prompt(
        cwd,
        tools=tool_names,
        extra_file=os.getenv("PAGENT_ACP_SYSTEM_PROMPT_FILE"),
    )
    return Agent(
        llm=DeepSeek(model),
        session=Session(system),
        tools=TOOLS,
        max_turns=int(os.getenv("PAGENT_ACP_MAX_TURNS", "12")),
    )


def main() -> None:
    asyncio.run(run_stdio(make_agent))


if __name__ == "__main__":
    main()
