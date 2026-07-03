from __future__ import annotations

import argparse
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

BUNDLED_CONFIG = Path(__file__).with_name("pagent.toml")
CONFIG_FILENAMES = ("pagent.toml",)


@dataclass(slots=True)
class ReplConfig:
    thread_id: str | None = None
    model: str | None = None
    api_key: str | None = None
    provider_base_url: str | None = None
    max_turns: int | None = None
    backend: str | None = None
    image: str | None = None
    container_ttl: int | None = None
    command_policy: str | None = None
    ssh_host: str | None = None
    ssh_config: str | None = None
    ssh_workdir: str | None = None
    skill_roots: tuple[str, ...] | None = None

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
    skills = data.get("skills", {})

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

    return ReplConfig(
        model=model,
        api_key=api_key,
        provider_base_url=base_url,
        max_turns=max_turns,
        backend=sandbox.get("backend"),
        image=image,
        container_ttl=container_ttl,
        command_policy=command_policy,
        ssh_host=ssh.get("host"),
        ssh_config=ssh.get("config_path"),
        ssh_workdir=ssh.get("workdir"),
        skill_roots=skill_roots,
    )


def find_project_config(workdir: str | None = None) -> Path | None:
    root = Path(workdir or os.getcwd())
    for name in CONFIG_FILENAMES:
        path = root / name
        if path.is_file():
            return path
    dotted = root / ".pagent" / "config.toml"
    if dotted.is_file():
        return dotted
    return None


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
    layers: list[ReplConfig] = []

    if BUNDLED_CONFIG.is_file():
        layers.append(load_config_file(BUNDLED_CONFIG))

    explicit = Path(config_path).expanduser() if config_path else None
    if explicit:
        if not explicit.is_file():
            raise FileNotFoundError(f"config not found: {explicit}")
        layers.append(load_config_file(explicit))
    else:
        env_path = os.environ.get("PAGENT_CONFIG")
        if env_path:
            path = Path(env_path).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"PAGENT_CONFIG not found: {path}")
            layers.append(load_config_file(path))
        else:
            project_path = find_project_config(workdir)
            if project_path:
                layers.append(load_config_file(project_path))

    merged = ReplConfig()
    for layer in layers:
        merged = merge_config(merged, layer)
    return merged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="pagent interactive REPL")
    parser.add_argument(
        "--config",
        default=None,
        help="config file (default: ./pagent.toml over bundled defaults)",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="resume thread; omit to create thread-<timestamp>",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> ReplConfig:
    config = load_config(config_path=args.config)
    if args.thread_id:
        config = replace(config, thread_id=args.thread_id)
    return config
