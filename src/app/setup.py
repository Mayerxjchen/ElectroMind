"""首次使用：检测缺失 API Key，引导写入 ``~/.pagent/pagent.toml``。

Setup 收集 provider 三项：

- ``api_key``（必填）
- ``model``（可回车用默认）
- ``base_url``（可留空，走服务商默认 endpoint）
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import USER_CONFIG_PATH, ReplConfig, load_config

USER_CONFIG = Path(USER_CONFIG_PATH).expanduser()
DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(slots=True)
class ProviderSetup:
    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str | None = None


def needs_api_key(config: ReplConfig | None = None) -> bool:
    """当前合并配置下是否还没有可用的 API Key。"""
    cfg = config if config is not None else load_config()
    return not cfg.resolved_api_key()


def toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def upsert_provider_field(text: str, field: str, value: str) -> str:
    """在 toml 文本里写入/更新 ``[provider].<field>``，尽量保留其它内容。"""
    key_line = f'{field} = "{toml_escape(value)}"'
    pattern = rf"(?m)^\s*{re.escape(field)}\s*=\s*.*$"
    if re.search(pattern, text):
        return re.sub(pattern, key_line, text, count=1)

    provider = re.search(r"(?m)^\[provider\]\s*$", text)
    if provider:
        insert_at = provider.end()
        return text[:insert_at] + "\n" + key_line + text[insert_at:]

    suffix = "" if text.endswith("\n") or not text else "\n"
    return text + suffix + f"\n[provider]\n{key_line}\n"


def remove_provider_field(text: str, field: str) -> str:
    """删除 ``[provider]`` 下某字段行（用于清空可选的 base_url）。"""
    return re.sub(rf"(?m)^\s*{re.escape(field)}\s*=\s*.*\n?", "", text)


# 兼容旧测试/调用名。
def upsert_provider_api_key(text: str, api_key: str) -> str:
    return upsert_provider_field(text, "api_key", api_key)


def write_user_provider(setup: ProviderSetup) -> Path:
    """写入 ``~/.pagent/pagent.toml`` 的 provider 段；目录不存在则创建。"""
    key = setup.api_key.strip()
    if not key:
        raise ValueError("api_key 不能为空")
    model = (setup.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = setup.base_url.strip() if setup.base_url else ""

    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if USER_CONFIG.is_file():
        text = USER_CONFIG.read_text(encoding="utf-8")
    else:
        text = (
            "# 用户级 pagent 配置（跨项目）\n"
            "# 合并顺序：bundled < ~/.pagent/pagent.toml < ./pagent.toml < CLI\n"
            "\n"
            "[provider]\n"
        )

    text = upsert_provider_field(text, "api_key", key)
    text = upsert_provider_field(text, "model", model)
    if base_url:
        text = upsert_provider_field(text, "base_url", base_url)
    else:
        text = remove_provider_field(text, "base_url")

    USER_CONFIG.write_text(text, encoding="utf-8")
    try:
        os.chmod(USER_CONFIG, 0o600)
    except OSError:
        pass
    return USER_CONFIG


def write_user_api_key(api_key: str, *, model: str = DEFAULT_MODEL, base_url: str | None = None) -> Path:
    """写入 api_key（及可选 model / base_url）。"""
    return write_user_provider(
        ProviderSetup(api_key=api_key, model=model, base_url=base_url)
    )


def _read_line(prompt: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise
    return value or default


def interactive_setup(*, stream=None) -> Path:
    """终端交互：收集 api_key / model / base_url 并写入用户配置。"""
    out = stream or sys.stderr
    if not sys.stdin.isatty():
        raise SystemExit(
            "需要 API Key：运行交互式 setup，或写入 ~/.pagent/pagent.toml，"
            "或 export DEEPSEEK_API_KEY"
        )

    out.write("未检测到 API Key。首次使用请完成 setup。\n")
    out.write(f"将写入：{USER_CONFIG}\n")
    out.write("api_key 必填；model / base_url 可回车跳过（用默认）。\n")
    try:
        key = getpass.getpass("API Key: ")
        if not key.strip():
            out.write("未输入 Key，已取消。\n")
            raise SystemExit(1)
        model = _read_line("Model", default=DEFAULT_MODEL)
        base_url = _read_line("Base URL（可选，官方 DeepSeek 可留空）", default="")
    except (EOFError, KeyboardInterrupt) as exc:
        out.write("\n已取消 setup。\n")
        raise SystemExit(1) from exc

    path = write_user_provider(
        ProviderSetup(
            api_key=key,
            model=model,
            base_url=base_url or None,
        )
    )
    out.write(f"已保存到 {path}\n")
    return path


def ensure_api_key(config: ReplConfig) -> ReplConfig:
    """若缺 Key 且在 TTY 则跑 setup，然后重新 load 配置。"""
    if not needs_api_key(config):
        return config
    interactive_setup()
    return load_config()
