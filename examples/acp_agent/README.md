# pagent ACP agent

Run [pagent](https://github.com/SyncLionPaw/pagent) as an [Agent Client Protocol](https://agentclientprotocol.com/) agent so editors like **Zed** or **JetBrains** can orchestrate it over stdio.

## Setup

```bash
export DEEPSEEK_API_KEY="your-key"
uv sync --group dev --extra acp --extra search
```

Tools: `readfile`, `grep_code`, `glob_paths`, `bash` (ls only), `web_search`, `calc`, `clock`, `region`.

## Run (stdio)

```bash
uv run python examples/acp_agent/main.py
```

The process reads JSON-RPC from stdin and writes to stdout. Do not print debug output to stdout — use stderr.

## Zed

Add to `~/.config/zed/settings.json` (adjust paths):

```json
{
  "agent_servers": {
    "pagent": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/pagent",
        "python",
        "examples/acp_agent/main.py"
      ],
      "env": {
        "DEEPSEEK_API_KEY": "your-key"
      }
    }
  }
}
```

Open the Agents panel, pick **pagent**, and start a session.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEEPSEEK_API_KEY` | — | Required API key |
| `PAGENT_ACP_MODEL` | `deepseek-v4-flash` | Model name |
| `PAGENT_ACP_MAX_TURNS` | `12` | Tool loop limit |
| `PAGENT_ACP_SYSTEM_PROMPT_FILE` | — | Optional markdown file appended to the built-in system prompt |

Built-in prompt lives in `examples/acp_agent/prompt.py` (`acp_system_prompt`). Edit that file for project-wide behavior, or use `PAGENT_ACP_SYSTEM_PROMPT_FILE` for personal overrides without changing the repo.

## Custom agent

Reuse the adapter in your own script:

```python
import asyncio
from pagent import Agent, LLM, Session
from pagent_acp import PagentACPAgent, run_stdio

def make_agent(cwd: str) -> Agent:
    return Agent(llm=LLM("gpt-4o-mini"), session=Session("You are helpful."), tools=[])

asyncio.run(run_stdio(make_agent))
```

## Mapping

| pagent event | ACP `session/update` |
|--------------|----------------------|
| `TextDelta` | `agent_message_chunk` |
| `ReasoningDelta` | `agent_thought_chunk` |
| `ToolCallBegin` | `tool_call` (in_progress) |
| `ToolResult` | `tool_call_update` (completed / failed) |

Inbound cancel uses ACP `session/cancel` → cancels the in-flight `prompt` task.
