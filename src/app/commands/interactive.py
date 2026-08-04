"""交互模式命令：``electromind [PROMPT]`` / ``-c`` / ``-r``。

负责交互入口的应用逻辑（resume 选择器、API Key 引导、初始 prompt 注入），
把最终 ReplConfig 交给 REPL 层（app.repl / app.concurrent_repl）。
"""

from __future__ import annotations

import asyncio
import sys

from app.config import ReplConfig, RunOptions, load_config, replace
from app.exitcodes import EXIT_CLI, EXIT_PROVIDER
from electromind.paths import HOME_CONFIG_NAME, LOCAL_CONFIG_NAME


def refresh_after_setup(config: ReplConfig, options: RunOptions) -> ReplConfig:
    """setup 写盘后重新加载文件配置，保留已解析的 thread_id。"""
    thread_id = config.thread_id
    fresh = load_config(config_path=options.config)
    fresh = options.apply_to(fresh)
    if thread_id:
        fresh = replace(fresh, thread_id=thread_id)
    return fresh


def _ensure_project_trust(config: ReplConfig, options: RunOptions) -> ReplConfig:
    """Workspace Trust：项目含 Project/Local 配置且未信任时提示；拒绝则保持跳过。

    返回重新加载后的配置（信任后 project scope 生效）。
    """
    from app.config import (
        find_project_root,
        is_project_trusted,
        load_config,
        trust_project,
    )

    root = find_project_root()
    if root is None or is_project_trusted(root):
        return config
    project_cfg = root / ".electromind" / HOME_CONFIG_NAME
    local_cfg = root / ".electromind" / LOCAL_CONFIG_NAME
    if not project_cfg.is_file() and not local_cfg.is_file():
        return config

    if not sys.stdin.isatty():
        print(
            f"未信任的项目 {root}：跳过其配置（fail-closed；"
            "electromind config trust 可启用）",
            file=sys.stderr,
        )
        return config

    print(
        f"项目 {root} 包含 Project/Local 配置。首次启用前需要信任（"
        "权限规则可能来自克隆的仓库）。",
        file=sys.stderr,
    )
    try:
        answer = input("信任此项目并应用其配置？[y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    if answer not in ("y", "yes", "是"):
        print("已跳过项目配置。", file=sys.stderr)
        return config

    trust_project(root)
    print(f"已信任 {root}。", file=sys.stderr)
    fresh = load_config(config_path=options.config)
    from app.config import replace

    # 保留 config_from_args 已解析的会话选择（--continue/--resume/picker）
    fields: dict = {
        "thread_id": config.thread_id,
        "resume_interactive": config.resume_interactive,
    }
    # 新合并未提供的 provider 字段保留旧值（如仅存在于旧配置对象的情况）
    if fresh.api_key is None:
        fields["api_key"] = config.api_key
    if fresh.model is None:
        fields["model"] = config.model
    if fresh.provider_base_url is None:
        fields["provider_base_url"] = config.provider_base_url
    fresh = replace(fresh, **fields)
    return options.apply_to(fresh)


def run(config: ReplConfig, options: RunOptions) -> int:
    """启动交互 REPL。返回进程退出码（由调用方 SystemExit）。"""
    from app.sessions import interactive_session_picker, list_sessions

    config = _ensure_project_trust(config, options)

    # --resume without ID → 交互式会话选择器
    if config.resume_interactive:
        sessions = list_sessions()
        if not sessions:
            print("没有可恢复的会话", file=sys.stderr)
            return EXIT_CLI
        chosen = interactive_session_picker(sessions)
        if chosen is None:
            return 0
        config = replace(config, thread_id=chosen, resume_interactive=False)

    # 缺 API Key：TTY 下引导写入 ~/.electromind；非 TTY 明确失败（exit 3）
    if not config.resolved_api_key():
        from app.setup import interactive_setup

        if not sys.stdin.isatty():
            print(
                "需要 API Key：运行交互式 electromind 完成 setup，"
                "或写入 ~/.electromind/config.toml，或 export DEEPSEEK_API_KEY",
                file=sys.stderr,
            )
            return EXIT_PROVIDER
        interactive_setup()
        config = refresh_after_setup(config, options)

    from app.repl import run_repl

    initial_prompt = " ".join(options.prompt).strip() or None
    color = False if options.no_color else None
    try:
        code = asyncio.run(
            run_repl(
                config,
                color=color,
                initial_prompt=initial_prompt,
                no_session_persistence=options.no_session_persistence,
            )
        )
    except KeyboardInterrupt:
        from app.terminal import emit

        emit()
        return 0
    return code
