"""并发 REPL — patch_stdout 底栏固定输入，run 中 steer / cancel。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.app.concurrent_repl
    uv run pagent
"""

from app.concurrent_repl import main

if __name__ == "__main__":
    main()
