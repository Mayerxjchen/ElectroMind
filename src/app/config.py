from __future__ import annotations

import argparse
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from pagentv4.paths import find_home_config

BUNDLED_CONFIG = Path(__file__).with_name("pagent.toml")
CONFIG_FILENAMES = ("pagent.toml",)
# 兼容旧名：用户级 home 下的配置路径（未解析项目模式时）。
USER_CONFIG_PATH = "~/.pagent/pagent.toml"


@dataclass(slots=True)
class ReplConfig:
    thread_id: str | None = None
    blocking: bool = False
    model: str | None = None
    api_key: str | None = None
    provider_base_url: str | None = None
    max_turns: int | None = None
    backend: str | None = None
    image: str | None = None
    container_ttl: int | None = None
    command_policy: str | None = None
    sandbox_tools: tuple[str, ...] | None = None
    project_path: str | None = None
    ssh_host: str | None = None
    ssh_config: str | None = None
    ssh_workdir: str | None = None
    skill_roots: tuple[str, ...] | None = None
    user_label: str | None = None
    assistant_label: str | None = None
    permission_mode: str | None = None

    def resolved_api_key(self) -> str | None:
        if self.api_key and self.api_key.strip():
            return self.api_key.strip()
        env = os.getenv("DEEPSEEK_API_KEY")
        if env and env.strip():
            return env.strip()
        return None

    def resolved_max_turns(self) -> int:
        return self.max_turns if self.max_turns is not None else 12

    def resolved_model(self) -> str:
        return self.model or "deepseek-v4-flash"

    def resolved_skill_roots(self) -> tuple[str, ...]:
        return self.skill_roots or ()

    def resolved_user_label(self) -> str:
        label = (self.user_label or "you").strip()
        return label or "you"

    def resolved_assistant_label(self) -> str:
        label = (self.assistant_label or "pagent").strip()
        return label or "pagent"

    def resolved_permission_mode(self) -> str:
        mode = (self.permission_mode or "prompt").strip().lower()
        return mode if mode in ("prompt", "auto") else "prompt"

    def permission_auto(self) -> bool:
        return self.resolved_permission_mode() == "auto"

    def thread_overrides(self) -> dict:
        kwargs: dict = {}
        if self.backend is not None:
            kwargs["backend"] = self.backend
        if self.image is not None and self.image != "":
            kwargs["image"] = self.image
        if self.container_ttl is not None:
            kwargs["container_ttl_seconds"] = self.container_ttl or None
        if self.command_policy is not None:
            kwargs["command_policy"] = self.command_policy
        if self.sandbox_tools is not None:
            kwargs["sandbox_tools"] = self.sandbox_tools
        if self.project_path is not None and self.project_path != "":
            kwargs["project_path"] = self.project_path
        if self.ssh_config is not None:
            kwargs["ssh_config"] = self.ssh_config
        if self.ssh_host is not None and self.ssh_host != "":
            kwargs["ssh_host"] = self.ssh_host
        if self.ssh_workdir is not None:
            kwargs["ssh_workdir"] = self.ssh_workdir
        if self.model is not None:
            kwargs["model"] = self.model
        return kwargs


def load_toml(path: Path) -> dict:
    with path.open("rb") as fp:
        return tomllib.load(fp)


def parse_repl_config(data: dict) -> ReplConfig:
    provider = data.get("provider", {})
    sandbox = data.get("sandbox", {})
    ssh = data.get("ssh", {})
    project = data.get("project", {})
    skills = data.get("skills", {})
    repl = data.get("repl", {})
    permission = data.get("permission", {})

    max_turns = data.get("max_turns")
    if max_turns is not None and not isinstance(max_turns, int):
        raise ValueError("max_turns must be an integer")

    model = provider.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("provider.model must be a string")

    api_key = provider.get("api_key")
    if api_key is not None and not isinstance(api_key, str):
        raise ValueError("provider.api_key must be a string")
    if api_key == "":
        api_key = None

    base_url = provider.get("base_url")
    if base_url is not None and not isinstance(base_url, str):
        raise ValueError("provider.base_url must be a string")
    if base_url == "":
        base_url = None

    image = sandbox.get("image")
    if image == "":
        image = None

    command_policy = sandbox.get("command_policy")
    if command_policy is not None and not isinstance(command_policy, str):
        raise ValueError("sandbox.command_policy must be a string")
    if command_policy == "":
        command_policy = None

    container_ttl = sandbox.get("container_ttl")
    if container_ttl is not None and not isinstance(container_ttl, int):
        raise ValueError("sandbox.container_ttl must be an integer")

    tools = sandbox.get("tools")
    sandbox_tools: tuple[str, ...] | None
    if tools is None:
        sandbox_tools = None
    elif isinstance(tools, list):
        if not all(isinstance(item, str) for item in tools):
            raise ValueError("sandbox.tools must be a list of strings")
        sandbox_tools = tuple(item for item in tools if item.strip())
    else:
        raise ValueError("sandbox.tools must be a list of strings")

    project_path = project.get("path")
    if project_path is not None and not isinstance(project_path, str):
        raise ValueError("project.path must be a string")
    if project_path == "":
        project_path = None

    roots = skills.get("roots")
    skill_roots: tuple[str, ...] | None
    if roots is None:
        skill_roots = None
    elif isinstance(roots, str):
        skill_roots = (roots,) if roots.strip() else ()
    elif isinstance(roots, list):
        if not all(isinstance(item, str) for item in roots):
            raise ValueError("skills.roots must be a string or list of strings")
        skill_roots = tuple(item for item in roots if item.strip())
    else:
        raise ValueError("skills.roots must be a string or list of strings")

    user_label = repl.get("user_label")
    if user_label is not None and not isinstance(user_label, str):
        raise ValueError("repl.user_label must be a string")
    if user_label == "":
        user_label = None

    assistant_label = repl.get("assistant_label")
    if assistant_label is not None and not isinstance(assistant_label, str):
        raise ValueError("repl.assistant_label must be a string")
    if assistant_label == "":
        assistant_label = None

    permission_mode = permission.get("mode")
    if permission_mode is not None:
        if not isinstance(permission_mode, str):
            raise ValueError("permission.mode must be a string")
        permission_mode = permission_mode.strip().lower()
        if permission_mode not in ("prompt", "auto"):
            raise ValueError("permission.mode must be 'prompt' or 'auto'")

    return ReplConfig(
        model=model,
        api_key=api_key,
        provider_base_url=base_url,
        max_turns=max_turns,
        backend=sandbox.get("backend"),
        image=image,
        container_ttl=container_ttl,
        command_policy=command_policy,
        sandbox_tools=sandbox_tools,
        project_path=project_path,
        ssh_host=ssh.get("host"),
        ssh_config=ssh.get("config_path"),
        ssh_workdir=ssh.get("workdir"),
        skill_roots=skill_roots,
        user_label=user_label,
        assistant_label=assistant_label,
        permission_mode=permission_mode,
    )


def find_project_config(workdir: str | None = None) -> Path | None:
    """当前 cwd 若为项目模式，返回其配置文件（含遗留 ``./pagent.toml``）。"""
    return find_home_config(workdir)


def find_user_config(workdir: str | None = None) -> Path | None:
    """当前生效 home 下的 ``pagent.toml``；不存在则返回 None。"""
    return find_home_config(workdir)


def load_config_file(path: Path) -> ReplConfig:
    return parse_repl_config(load_toml(path))


def merge_config(base: ReplConfig, override: ReplConfig) -> ReplConfig:
    fields = {}
    for name in ReplConfig.__dataclass_fields__:
        value = getattr(override, name)
        if value is None:
            continue
        fields[name] = value
    return replace(base, **fields)


def load_config(
    *,
    config_path: Path | str | None = None,
    workdir: str | None = None,
) -> ReplConfig:
    """合并配置层，后层覆盖前层：

    1. 包内默认 ``src/app/pagent.toml``
    2. 当前 pagent home 的 ``pagent.toml``（``./.pagent`` 或 ``~/.pagent``，与 thread 同根）
    3. 若传了 ``--config``，再覆盖一层
    """
    layers: list[ReplConfig] = []

    if BUNDLED_CONFIG.is_file():
        layers.append(load_config_file(BUNDLED_CONFIG))

    home_path = find_home_config(workdir)
    if home_path:
        layers.append(load_config_file(home_path))

    if config_path is not None:
        explicit = Path(config_path).expanduser()
        if not explicit.is_file():
            raise FileNotFoundError(f"config not found: {explicit}")
        layers.append(load_config_file(explicit))

    merged = ReplConfig()
    for layer in layers:
        merged = merge_config(merged, layer)
    return merged


def refresh_provider_from_disk(
    config: ReplConfig, *, workdir: str | None = None
) -> ReplConfig:
    """从当前 home 的 ``pagent.toml`` 刷新 provider 字段。

    wire 进程启动时会缓存一份 ReplConfig；宿主（Desktop / VS Code）事后写入
    API Key 时，打开 runner 前调用本函数即可读到新 Key，无需重启进程。
    """
    fresh = load_config(workdir=workdir)
    fields: dict = {}
    if fresh.api_key:
        fields["api_key"] = fresh.api_key
    if fresh.model:
        fields["model"] = fresh.model
    if fresh.provider_base_url:
        fields["provider_base_url"] = fresh.provider_base_url
    if not fields:
        return config
    return replace(config, **fields)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="pagent interactive REPL")
    parser.add_argument(
        "--config",
        default=None,
        help="extra config file over bundled + active home ({./.pagent|~/.pagent}/pagent.toml)",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="resume thread; omit to create thread-<timestamp>",
    )
    parser.add_argument(
        "--blocking",
        action="store_true",
        help="阻塞 REPL：跑完一轮再显示输入（默认 TTY 为底栏固定输入）",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="危险工具自动审批（等同 [permission] mode=auto）",
    )
    parser.add_argument(
        "--permission-mode",
        choices=("prompt", "auto"),
        default=None,
        help="工具审批模式",
    )
    parser.add_argument(
        "--wire",
        action="store_true",
        help="stdio NDJSON 后端模式：stdin 收 JSON 命令，stdout 出事件流（供插件/前端驱动）",
    )
    parser.add_argument(
        "--backend",
        choices=("local", "container", "docker", "podman", "ssh"),
        default=None,
        help="覆盖 sandbox backend",
    )
    parser.add_argument("--project", default=None, help="绑定本次会话的项目目录")
    parser.add_argument("--ssh-host", default=None, help="覆盖 SSH Host 别名")
    parser.add_argument("--ssh-config", default=None, help="覆盖 SSH config 路径")
    return parser


def config_from_args(args: argparse.Namespace) -> ReplConfig:
    config = load_config(config_path=args.config)
    fields: dict = {}
    if args.thread_id:
        fields["thread_id"] = args.thread_id
    if args.blocking:
        fields["blocking"] = True
    if args.permission_mode:
        fields["permission_mode"] = args.permission_mode
    if args.auto:
        fields["permission_mode"] = "auto"
    if args.backend:
        fields["backend"] = args.backend
    if args.project:
        fields["project_path"] = args.project
    if args.ssh_host:
        fields["ssh_host"] = args.ssh_host
    if args.ssh_config:
        fields["ssh_config"] = args.ssh_config
    if fields:
        config = replace(config, **fields)
    return config
