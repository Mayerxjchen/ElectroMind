"""v4 REPL — thin wrapper around `app` (same as `python -m app` / `pagent`).

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.v4runner.repl
    uv run python -m app
    uv run pagent
    uv run python -m examples.v4runner.repl --thread-id demo
"""

from app.repl import main

if __name__ == "__main__":
    main()
