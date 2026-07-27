from __future__ import annotations

import argparse
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from pagentv4.paths import (
    activate_home,
    default_pagent_home,
    find_home_config,
    home_config_path,
)
from pagentv4.tools import HARNESS_WEB_TOOL_NAMES

BUNDLED_CONFIG = Path(__file__).with_name("pagent.toml")
CONFIG_FILENAMES = ("pagent.toml",)
# 兼容旧名：用户级 home 下的配置路径（未解析项目模式时）。
USER_CONFIG_PATH = "~/.pagent/pagent.toml"
# runner 进程自身跑在哪：local = 用户电脑（当前唯一支持）；cloud = 云端 pod（保留，未接线）。
RUNNER_LOCATIONS = ("local", "cloud")


@dataclass(slots=True)
class ReplConfig:
    thread_id: str | None = None
    blocking: bool = False
    model: str | None = None
    api_key: str | None = None
    provider_base_url: str | None = None
    max_turns: int | None = None
    runner_location: str | None = None
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
    # 主 agent 的进程内（harness）工具白名单，冻结进新 thread.toml 的 [agent] tools。
    # None 表示未在 pagent.toml 显式配置，回退到默认（web 工具）。
    agent_tools: tuple[str, ...] | None = None
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
        return self.max_turns if self.max_turns is not None else 24

    def resolved_runner_location(self) -> str:
        return self.runner_location if self.runner_location is not None else "local"

    def resolved_model(self) -> str:
        return self.model or "deepseek-v4-flash"

    def resolved_skill_roots(self) -> tuple[str, ...]:
        return self.skill_roots or ()

    def resolved_agent_tools(self) -> tuple[str, ...]:
        """冻结进 thread.toml 的 [agent] tools 白名单。

        未在 pagent.toml 显式配置时默认给全套 web 工具（保持既有行为，只是从静默
        挂载改成显式冻结）。显式配了（含空表）就照配置来。
        """
        if self.agent_tools is None:
            return HARNESS_WEB_TOOL_NAMES
        return self.agent_tools

    def resolved_skill_dirs(self) -> tuple[str, ...]:
        """把 ``[skills] roots`` 展开成冻结进 thread.toml 的 ``[agent] skills``。

        ``roots`` 就是完整扫描列表，不隐式追加任何目录：写了才扫，删了就没有。
        其中 ``{home}`` 占位符展开成当前生效的 pagent home（prod/dev/PAGENT_HOME
        由 home 激活决定），让模板不必写死绝对路径。
        """
        home = str(default_pagent_home())
        return tuple(
            root.replace("{home}", home) for root in self.resolved_skill_roots()
        )

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
        # project_path 是本次会话冻结进 thread.toml 的 host_root：留空时在这里
        # 解析成启动时的 cwd 绝对路径，让 thread.toml 写具体值（resume 不漂移）。
        # 全局 pagent.toml 里留空的语义仍是"用 cwd"，只是解析点前置到冻结时。
        if self.project_path is not None and self.project_path != "":
            kwargs["project_path"] = os.path.abspath(
                os.path.expanduser(self.project_path)
            )
        else:
            kwargs["project_path"] = os.path.abspath(os.getcwd())
        if self.ssh_config is not None:
            kwargs["ssh_config"] = self.ssh_config
        if self.ssh_host is not None and self.ssh_host != "":
            kwargs["ssh_host"] = self.ssh_host
        if self.ssh_workdir is not None:
            kwargs["ssh_workdir"] = self.ssh_workdir
        if self.model is not None:
            kwargs["model"] = self.model
        # SSOT：把 harness 工具白名单与 skills 目录冻结进新 thread.toml，
        # 让 [agent] tools / [agent] skills 成为运行时唯一事实来源。
        kwargs["agent_tools"] = self.resolved_agent_tools()
        kwargs["skills"] = self.resolved_skill_dirs()
        return kwargs


def load_toml(path: Path) -> dict:
    with path.open("rb") as fp:
        return tomllib.load(fp)


def parse_repl_config(data: dict) -> ReplConfig:
    provider = data.get("provider", {})
    sandbox = data.get("sandbox", {})
    sandbox_container = sandbox.get("container", {})
    sandbox_ssh = sandbox.get("ssh", {})
    project = data.get("project", {})
    skills = data.get("skills", {})
    agent = data.get("agent", {})
    repl = data.get("repl", {})
    runner = data.get("runner", {})
    permission = data.get("permission", {})

    max_turns = runner.get("max_turns")
    if max_turns is not None and not isinstance(max_turns, int):
        raise ValueError("runner.max_turns must be an integer")

    runner_location = runner.get("location")
    if runner_location == "":
        runner_location = None
    if runner_location is not None:
        if not isinstance(runner_location, str):
            raise ValueError("runner.location must be a string")
        if runner_location not in RUNNER_LOCATIONS:
            raise ValueError(f"runner.location must be one of {list(RUNNER_LOCATIONS)}")
        if runner_location == "cloud":
            raise NotImplementedError(
                "runner.location = 'cloud' 尚未支持；云端 pod 形态待实现，当前只支持 'local'"
            )

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

    image = sandbox_container.get("image")
    if image == "":
        image = None

    command_policy = sandbox.get("command_policy")
    if command_policy is not None and not isinstance(command_policy, str):
        raise ValueError("sandbox.command_policy must be a string")
    if command_policy == "":
        command_policy = None

    container_ttl = sandbox_container.get("container_ttl")
    if container_ttl is not None and not isinstance(container_ttl, int):
        raise ValueError("sandbox.container.container_ttl must be an integer")

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

    # [project] 按 runner.location 分子表：local 绑用户目录(host_root)，
    # cloud 绑云端资源。location=cloud 已在上面 NotImplementedError 挡住，
    # 故这里只解析 [project.local]；[project.cloud] 是模板里的语义锚点。
    if "path" in project:
        raise ValueError(
            "顶层 [project] path 已废弃；改用 [project.local] path（按 runner.location 分模式）"
        )
    project_local = project.get("local", {})
    if not isinstance(project_local, dict):
        raise ValueError("[project.local] must be a table")
    project_path = project_local.get("path")
    if project_path is not None and not isinstance(project_path, str):
        raise ValueError("project.local.path must be a string")
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

    agent_tools_cfg = agent.get("tools")
    agent_tools: tuple[str, ...] | None
    if agent_tools_cfg is None:
        agent_tools = None
    elif isinstance(agent_tools_cfg, list):
        if not all(isinstance(item, str) for item in agent_tools_cfg):
            raise ValueError("agent.tools must be a list of strings")
        agent_tools = tuple(item for item in agent_tools_cfg if item.strip())
    else:
        raise ValueError("agent.tools must be a list of strings")

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
        runner_location=runner_location,
        backend=sandbox.get("backend"),
        image=image,
        container_ttl=container_ttl,
        command_policy=command_policy,
        sandbox_tools=sandbox_tools,
        project_path=project_path,
        ssh_host=sandbox_ssh.get("host"),
        ssh_config=sandbox_ssh.get("config_path"),
        ssh_workdir=sandbox_ssh.get("workdir"),
        skill_roots=skill_roots,
        agent_tools=agent_tools,
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


def ensure_home_config(workdir: str | None = None) -> Path:
    """定位当前 home 的 ``pagent.toml``；不存在就从包内模板物化一份写盘。

    home 由入口的 ``activate_home`` 决定：``--dev`` → ``<root>/.pagent``，否则
    ``~/.pagent``。种子取已打包的 ``src/app/pagent.toml``（``src/template`` 不进
    wheel，安装版机器上没有），两份解析结果由测试锁死一致。
    """
    existing = find_home_config(workdir)
    if existing:
        return existing
    target = home_config_path(workdir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(BUNDLED_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def load_config(
    *,
    config_path: Path | str | None = None,
    workdir: str | None = None,
) -> ReplConfig:
    """从单一来源加载配置：当前 home 的 ``pagent.toml``（缺失则先从模板物化）。

    ``--config <file>`` 若传入，作为显式覆盖再叠一层。未设字段回落 ReplConfig
    自身默认（与模板一致），因此手删部分字段的 home 配置仍可正常工作。
    """
    source = ensure_home_config(workdir)
    config = load_config_file(source)

    if config_path is not None:
        explicit = Path(config_path).expanduser()
        if not explicit.is_file():
            raise FileNotFoundError(f"config not found: {explicit}")
        config = merge_config(config, load_config_file(explicit))

    return config


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
        "--yolo",
        action="store_true",
        help="危险工具自动审批（等同 [permission] mode=auto）；--yolo 为别名",
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
        "--http",
        action="store_true",
        help="HTTP 后端模式：POST /command 收命令，GET /events 出 SSE 事件流（对齐 wire）",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="--http 监听地址（默认 127.0.0.1）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8848,
        help="--http 监听端口（默认 8848）",
    )
    parser.add_argument(
        "--backend",
        choices=("local", "container", "docker", "podman", "ssh"),
        default=None,
        help="覆盖 sandbox backend",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="绑定本次会话的用户目录（host_root）；存为绝对路径，避免 resume 漂移",
    )
    parser.add_argument(
        "--dev",
        nargs="?",
        const=".",
        default=None,
        metavar="ROOT",
        help="开发模式：数据落到 <ROOT>/.pagent（默认 ./.pagent）；不带则生产模式用 ~/.pagent",
    )
    parser.add_argument("--ssh-host", default=None, help="覆盖 SSH Host 别名")
    parser.add_argument("--ssh-config", default=None, help="覆盖 SSH config 路径")
    return parser


def config_from_args(args: argparse.Namespace) -> ReplConfig:
    if getattr(args, "dev", None) is not None:
        activate_home("dev", args.dev)
    else:
        activate_home("prod")
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
        # 归一化成绝对路径：thread.toml 存字面量，相对路径 resume 时会随 cwd 漂移。
        fields["project_path"] = os.path.abspath(os.path.expanduser(args.project))
    if args.ssh_host:
        fields["ssh_host"] = args.ssh_host
    if args.ssh_config:
        fields["ssh_config"] = args.ssh_config
    if fields:
        config = replace(config, **fields)
    return config
