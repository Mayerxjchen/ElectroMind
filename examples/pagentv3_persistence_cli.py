"""pagentv3 interactive CLI — continuous chat with pluggable persistence.

Usage:
    uv run python -m examples.pagentv3_persistence_cli
    uv run python -m examples.pagentv3_persistence_cli --backend sqlite

Requires:
    ollama serve
    ollama pull gemma4

Commands:
    /new               start a new conversation
    /list              list saved conversations
    /list <id|index>   show one conversation's messages
    /load <id|index>   load a saved conversation
    /messages          print persisted Messages in memory
    /exit              quit
"""

import asyncio
from argparse import ArgumentParser, Namespace
from pathlib import Path

from pagentv3 import Agent, JsonlBackend, Ollama, Persistence, SqliteBackend, TextDelta

MODEL_ID = "gemma4"
JSONL_STORE_DIR = Path("data/pagentv3_cli")
SQLITE_DB_PATH = Path("data/pagentv3_cli.db")
SYSTEM_PROMPT = (
    "每次只说一句话，语气冷淡克制，保持礼貌，直接回答用户问题，不辱骂，不拒绝简单任务。"
)
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def parse_args() -> Namespace:
    parser = ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=("jsonl", "sqlite"),
        default="jsonl",
        help="persistence backend",
    )
    return parser.parse_args()


def create_persistence(args: Namespace) -> tuple[Persistence, str, Path]:
    if args.backend == "sqlite":
        db_path = SQLITE_DB_PATH.resolve()
        return Persistence(SqliteBackend(db_path)), "DB path", db_path

    store_dir = JSONL_STORE_DIR.resolve()
    return Persistence(JsonlBackend(store_dir)), "Store dir", store_dir


def make_agent(
    persistence: Persistence,
    conversation_id: str | None = None,
    *,
    with_system: bool = False,
) -> Agent:
    return Agent(
        Ollama(MODEL_ID),
        persistence=persistence,
        conversation_id=conversation_id,
        system=SYSTEM_PROMPT if with_system else None,
    )


def resolve_conversation_id(
    persistence: Persistence,
    value: str,
) -> str | None:
    listed_conversations = persistence.list_conversations()
    conversation_id = value
    if value.isdigit():
        index = int(value) - 1
        if index < 0 or index >= len(listed_conversations):
            return None
        conversation_id = listed_conversations[index]
    if conversation_id not in persistence.list_conversations():
        return None
    return conversation_id


async def stream_once(agent: Agent, user_input: str) -> None:
    printed = False
    async for event in agent.arun(user_input):
        if not isinstance(event, TextDelta):
            continue
        if not printed:
            print(f"{CYAN}Assistant:{RESET} ", end="", flush=True)
            printed = True
        print(event.text, end="", flush=True)
    if not printed:
        print(f"{CYAN}Assistant:{RESET} ", end="", flush=True)
    print()


async def main() -> None:
    args = parse_args()
    persistence, location_name, location_path = create_persistence(args)
    agent = make_agent(persistence, with_system=True)

    print(f"{YELLOW}{location_name}:{RESET} {location_path}")
    print(f"{YELLOW}backend:{RESET} {args.backend}")
    print(f"{YELLOW}conversation_id:{RESET} {agent.conversation_id}")
    print(
        f"{YELLOW}Type /new, /list, /list <id|index>, /load <id|index>, "
        f"/messages, or /exit.{RESET}"
    )

    while True:
        try:
            user_input = input(f"\n{GREEN}You:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{YELLOW}Bye.{RESET}")
            return

        if not user_input:
            continue
        if user_input == "/exit":
            print(f"{YELLOW}Bye.{RESET}")
            return
        if user_input == "/new":
            agent = make_agent(persistence, with_system=True)
            print(f"{YELLOW}conversation_id:{RESET} {agent.conversation_id}")
            continue
        if user_input == "/list":
            listed_conversations = persistence.list_conversations()
            if not listed_conversations:
                print(f"{YELLOW}No saved conversations.{RESET}")
                continue
            print(f"{YELLOW}Saved conversations:{RESET}")
            for index, conversation_id in enumerate(listed_conversations, start=1):
                marker = " *" if conversation_id == agent.conversation_id else ""
                print(f"  {index}. {conversation_id}{marker}")
            continue
        if user_input.startswith("/list "):
            value = user_input.split(None, 1)[1].strip()
            conversation_id = resolve_conversation_id(persistence, value)
            if conversation_id is None:
                print(
                    f"{YELLOW}conversation not found:{RESET} {value}. "
                    "Use /list to see available conversations."
                )
                continue
            print(f"{YELLOW}conversation_id:{RESET} {conversation_id}")
            print(persistence.load_messages(conversation_id))
            continue
        if user_input.startswith("/load"):
            parts = user_input.split(None, 1)
            if len(parts) == 1:
                print(f"{YELLOW}usage:{RESET} /load <conversation_id|index>")
                continue
            value = parts[1].strip()
            conversation_id = resolve_conversation_id(persistence, value)
            if conversation_id is None:
                print(
                    f"{YELLOW}conversation not found:{RESET} {value}. "
                    "Use /list to see available conversations."
                )
                continue
            agent = make_agent(persistence, conversation_id=conversation_id)
            print(f"{YELLOW}loaded conversation_id:{RESET} {agent.conversation_id}")
            continue
        if user_input == "/messages":
            print(agent.messages)
            continue
        if user_input.startswith("/"):
            print(f"{YELLOW}unknown command:{RESET} {user_input}")
            continue

        await stream_once(agent, user_input)


if __name__ == "__main__":
    asyncio.run(main())
