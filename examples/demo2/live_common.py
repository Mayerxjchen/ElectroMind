"""Shared setup for ``examples/demo2/cli.py`` (LiveAgent + duplex bus)."""

import sys
from pathlib import Path

_EXAMPLES = Path(__file__).resolve().parent.parent
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

import cli_common as _base  # noqa: E402

from pagent import DEFAULT_TOOLS, DeepSeek, Session, bash, readfile  # noqa: E402
from pagent_live import LiveAgent, ask_user  # noqa: E402

CYAN = _base.CYAN
DIM = _base.DIM
GREEN = _base.GREEN
RED = _base.RED
RESET = _base.RESET
YELLOW = _base.YELLOW
require_api_key = _base.require_api_key
show_context = _base.show_context
spinner = _base.spinner

LIVE_TOOLS = [*DEFAULT_TOOLS, readfile, bash, ask_user]


def live_system_prompt(workspace: str) -> str:
    return (
        f"You are a helpful assistant.\nWorkspace root: {workspace}\n"
        "Tools: readfile, bash (ls only), ask_user.\n"
        "ask_user: only when you are blocked without a fact/preference/approval only the "
        "human can give; one question per call; never for demos or chit-chat.\n"
        "readfile: paths under the workspace; max 500 code points per call, use offset "
        "to continue.\n"
        "bash: whitelisted ls only; paths must stay in the workspace.\n"
    )


def make_live_agent(workspace: str) -> LiveAgent:
    return LiveAgent(
        llm=DeepSeek("deepseek-v4-flash"),
        session=Session(live_system_prompt(workspace)),
        tools=LIVE_TOOLS,
        max_turns=12,
    )


def print_banner(*, model_id, cwd, tools_count):
    _base.print_banner(
        model_id=model_id,
        cwd=cwd,
        tools_count=tools_count,
        subtitle="demo2: LiveAgent + duplex bus",
    )
