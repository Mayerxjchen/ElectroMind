from __future__ import annotations

import argparse
import os
import tempfile
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from electromind.ithread import SubAgentSpec
from electromind.paths import (
    HOME_CONFIG_NAME,
    LEGACY_HOME_CONFIG_NAME,
    LEGACY_LOCAL_CONFIG_NAME,
    LOCAL_CONFIG_NAME,
    activate_home,
    bundled_default_config,
    default_electromind_home,
    find_home_config,
    home_config_path,
)
from electromind.tools import HARNESS_WEB_TOOL_NAMES

from .cli_parser import build_parser  # noqa: F401  (旧调用兼容：config.build_parser)
from .exitcodes import EXIT_CLI

# CLI 任务模式 → 沙箱 session_mode（write-capable 值是 "agent"，CLI 的 "run" 映射过去）。
SESSION_MODE_TO_SPEC = {"ask": "ask", "plan": "plan", "run": "agent"}
SESSION_MODE_VALUES = ("ask", "plan", "run", "agent", "review")

# 包内唯一内置默认配置（src/electromind/resources/default-config.toml，随 wheel 打包）。
BUNDLED_CONFIG = bundled_default_config()
CONFIG_FILENAMES = (HOME_CONFIG_NAME,)
# 用户级 home 下的配置路径（生产模式默认）。
USER_CONFIG_PATH = f"~/.electromind/{HOME_CONFIG_NAME}"
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
    # None 表示未在配置文件显式配置，回退到默认（web 工具）。
    agent_tools: tuple[str, ...] | None = None
    # 命名子 agent：冻结进新 thread.toml 的 [sub.<name>]。None = 未配置。
    subs: dict[str, SubAgentSpec] | None = None
    user_label: str | None = None
    assistant_label: str | None = None
    permission_mode: str | None = None
    # --resume without ID → interactive picker; resolved in main()
    resume_interactive: bool = False
    execution_mode: str | None = None  # local | sandbox | ssh
    # 任务模式：ask | plan | run（冻结进 thread.toml 的 [agent] session_mode，
    # run → "agent"，即具备写能力的沙箱模式）。
    session_mode: str | None = None
    # --inline：交互不进入 alternate screen，保留终端 scrollback
    inline: bool = False

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

        未在配置文件显式配置时默认给全套 web 工具（保持既有行为，只是从静默
        挂载改成显式冻结）。显式配了（含空表）就照配置来。
        """
        if self.agent_tools is None:
            return HARNESS_WEB_TOOL_NAMES
        return self.agent_tools

    def resolved_skill_dirs(self) -> tuple[str, ...]:
        """把 ``[skills] roots`` 展开成冻结进 thread.toml 的 ``[agent] skills``。

        ``roots`` 就是完整扫描列表，不隐式追加任何目录：写了才扫，删了就没有。
        ``{electromind_home}``（兼容旧写法 ``{home}``）展开成当前生效的 electromind 数据根
        （prod/dev/ELECTROMIND_HOME 由 activate_home 决定），让模板不必写死绝对路径。
        """
        electromind_home = str(default_electromind_home())
        return tuple(
            root.replace("{electromind_home}", electromind_home).replace(
                "{home}", electromind_home
            )
            for root in self.resolved_skill_roots()
        )

    def resolved_user_label(self) -> str:
        label = (self.user_label or "you").strip()
        return label or "you"

    def resolved_assistant_label(self) -> str:
        label = (self.assistant_label or "electromind").strip()
        return label or "electromind"

    def resolved_permission_mode(self) -> str:
        """prompt | auto-safe | auto。

        auto-safe 与 auto 保持区分：auto-safe 只自动放行后端判定为安全的操作，
        其余仍走审批；auto（--yolo/--auto 遗留语义）全部放行。
        """
        mode = (self.permission_mode or "prompt").strip().lower()
        return mode if mode in ("prompt", "auto-safe", "auto") else "prompt"

    def permission_auto(self) -> bool:
        """完全自动（--yolo/--auto 遗留语义）：全部放行。"""
        return self.resolved_permission_mode() == "auto"

    def permission_auto_safe(self) -> bool:
        """auto-safe：只自动放行后端判定为安全的操作。"""
        return self.resolved_permission_mode() == "auto-safe"

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
        # 全局 config.toml 里留空的语义仍是"用 cwd"，只是解析点前置到冻结时。
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
        # 把 harness 工具白名单与额外 skills 目录冻结进新 thread.toml。
        # [agent] skills 作为 legacy 兼容入口；项目 skills 自动发现由
        # thread.spec.project_path 驱动，不再依赖此配置。
        kwargs["agent_tools"] = self.resolved_agent_tools()
        kwargs["skills"] = self.resolved_skill_dirs()
        if self.subs:
            kwargs["subs"] = dict(self.subs)
        if self.session_mode is not None:
            kwargs["session_mode"] = SESSION_MODE_TO_SPEC.get(
                self.session_mode, self.session_mode
            )
        return kwargs


def load_toml(path: Path | str) -> dict:
    with Path(path).open("rb") as fp:
        return tomllib.load(fp)


@dataclass(slots=True)
class Settings:
    """文件来源配置（User / Project / Local scope；CLI-5 引入多 scope 合并）。

    只承载持久化字段；每次运行的 CLI 参数属于 ``RunOptions``，两者合并成
    ``ReplConfig`` 供下游（REPL / wire / http）使用。
    """

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
    agent_tools: tuple[str, ...] | None = None
    subs: dict[str, SubAgentSpec] | None = None
    user_label: str | None = None
    assistant_label: str | None = None
    permission_mode: str | None = None
    execution_mode: str | None = None  # sandbox | local | ssh（CLI 面为 --target）
    session_mode: str | None = None  # ask | plan | run

    def to_repl_config(self) -> ReplConfig:
        return ReplConfig(
            model=self.model,
            api_key=self.api_key,
            provider_base_url=self.provider_base_url,
            max_turns=self.max_turns,
            runner_location=self.runner_location,
            backend=self.backend,
            image=self.image,
            container_ttl=self.container_ttl,
            command_policy=self.command_policy,
            sandbox_tools=self.sandbox_tools,
            project_path=self.project_path,
            ssh_host=self.ssh_host,
            ssh_config=self.ssh_config,
            ssh_workdir=self.ssh_workdir,
            skill_roots=self.skill_roots,
            agent_tools=self.agent_tools,
            subs=self.subs,
            user_label=self.user_label,
            assistant_label=self.assistant_label,
            permission_mode=self.permission_mode,
            execution_mode=self.execution_mode,
            session_mode=self.session_mode,
        )


def parse_settings(data: dict) -> Settings:
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
            raise ValueError(
                f"runner.location: 非法值 {runner_location!r}；"
                f"应为 {list(RUNNER_LOCATIONS)}"
            )
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

    sub_block = data.get("sub")
    subs: dict[str, SubAgentSpec] | None
    if sub_block is None:
        subs = None
    elif not isinstance(sub_block, dict):
        raise ValueError("[sub] must be a table of [sub.<name>] entries")
    else:
        parsed: dict[str, SubAgentSpec] = {}
        for name, spec in sub_block.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("[sub.<name>] name must be a non-empty string")
            if not isinstance(spec, dict):
                raise ValueError(f"[sub.{name}] must be a table")
            parsed[name] = SubAgentSpec.from_dict(spec)
        subs = parsed

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
        if permission_mode not in ("prompt", "auto", "auto-safe"):
            raise ValueError(
                f"permission.mode: 非法值 {permission_mode!r}；"
                "应为 'prompt' | 'auto' | 'auto-safe'"
            )

    execution = data.get("execution", {})
    execution_mode = execution.get("mode")
    if execution_mode is not None:
        if not isinstance(execution_mode, str):
            raise ValueError("execution.mode must be a string")
        execution_mode = execution_mode.strip().lower()
        if execution_mode not in ("local", "sandbox", "ssh"):
            raise ValueError(
                f"execution.mode: 非法值 {execution_mode!r}；应为 'local' | 'sandbox' | 'ssh'"
            )

    session_mode = execution.get("session_mode")
    if session_mode is not None:
        if not isinstance(session_mode, str):
            raise ValueError("execution.session_mode must be a string")
        session_mode = session_mode.strip().lower()
        if session_mode not in SESSION_MODE_VALUES:
            raise ValueError(
                f"execution.session_mode: 非法值 {session_mode!r}；"
                f"应为 {list(SESSION_MODE_VALUES)}"
            )

    return Settings(
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
        subs=subs,
        user_label=user_label,
        assistant_label=assistant_label,
        permission_mode=permission_mode,
        execution_mode=execution_mode,
        session_mode=session_mode,
    )


def parse_repl_config(data: dict) -> ReplConfig:
    """兼容旧调用：文件解析结果直接转为运行时 ReplConfig。"""
    return parse_settings(data).to_repl_config()


def find_project_config(workdir: str | None = None) -> Path | None:
    """当前 cwd 若为项目模式，返回其配置文件（``<project>/.electromind/config.toml``）。"""
    return find_home_config(workdir)


def find_user_config(workdir: str | None = None) -> Path | None:
    """当前生效 home 下的 ``config.toml``；不存在则返回 None。"""
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


# ---------------------------------------------------------------------------
# 多 scope 配置（CLI-5）：User < Project < Local < CLI
# ---------------------------------------------------------------------------

# Settings 字段 → 配置文件点分键（config sources / get/set 用）
SETTINGS_FIELD_KEYS: dict[str, str] = {
    "model": "provider.model",
    "api_key": "provider.api_key",
    "provider_base_url": "provider.base_url",
    "max_turns": "runner.max_turns",
    "runner_location": "runner.location",
    "backend": "sandbox.backend",
    "image": "sandbox.container.image",
    "container_ttl": "sandbox.container.container_ttl",
    "command_policy": "sandbox.command_policy",
    "sandbox_tools": "sandbox.tools",
    "project_path": "project.local.path",
    "ssh_host": "sandbox.ssh.host",
    "ssh_config": "sandbox.ssh.config_path",
    "ssh_workdir": "sandbox.ssh.workdir",
    "skill_roots": "skills.roots",
    "agent_tools": "agent.tools",
    "user_label": "repl.user_label",
    "assistant_label": "repl.assistant_label",
    "permission_mode": "permission.mode",
    "execution_mode": "execution.mode",
    "session_mode": "execution.session_mode",
}

TRUSTED_FILE_NAME = "trusted.json"

# RunOptions 字段 → 配置键（config sources 标注 CLI 覆盖用）
RUN_OPTIONS_FIELD_KEYS: dict[str, str] = {
    "mode": "execution.session_mode",
    "target": "execution.mode",
    "permission_mode": "permission.mode",
    "model": "provider.model",
    "project": "project.local.path",
    "max_iterations": "runner.max_turns",
    "allowed_tools": "agent.tools",
    "disallowed_tools": "agent.tools",
    "ssh_host": "sandbox.ssh.host",
    "ssh_config": "sandbox.ssh.config_path",
}


@dataclass(slots=True)
class SettingsSource:
    """一个配置作用域：scope 名 + 文件路径 + 解析出的 Settings。"""

    scope: str  # user | project | local | cli
    path: Path
    settings: Settings


def find_project_root(workdir: str | None = None) -> Path | None:
    """从 workdir 向上找项目根：含 ``.git/`` 或 ``.electromind/`` 的目录。"""
    start = Path(workdir or os.getcwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").is_dir() or (candidate / ".electromind").is_dir():
            return candidate
    return None


# -- Workspace Trust -----------------------------------------------------


def trusted_file(home: Path | None = None) -> Path:
    return (home or default_electromind_home()) / TRUSTED_FILE_NAME


def _load_trusted(home: Path | None = None) -> dict:
    path = trusted_file(home)
    if not path.is_file():
        return {}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def is_project_trusted(project_root: Path | None, home: Path | None = None) -> bool:
    """项目是否已信任（信任标记存用户 home 的 trusted.json）。"""
    if project_root is None:
        return True
    return bool(_load_trusted(home).get(str(project_root.resolve())))


def trust_project(project_root: Path | None, home: Path | None = None) -> None:
    if project_root is None:
        return
    data = _load_trusted(home)
    data[str(project_root.resolve())] = True
    path = trusted_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def untrust_project(project_root: Path | None, home: Path | None = None) -> None:
    if project_root is None:
        return
    data = _load_trusted(home)
    data.pop(str(project_root.resolve()), None)
    import json

    trusted_file(home).write_text(json.dumps(data, indent=2), encoding="utf-8")


# -- 分层加载 -------------------------------------------------------------


def load_settings_sources(
    workdir: str | None = None,
    *,
    config_path: Path | str | None = None,
    include_project: bool = True,
) -> list[SettingsSource]:
    """按优先级从低到高加载各作用域：Default → User → Project → Local → CLI(--config)。

    - Default：包内唯一内置默认 ``src/electromind/resources/default-config.toml``
      ——最低合并层。部分用户配置省略的字段从这里继承（如默认 skill roots），
      而不是回落到空值
    - User：当前 home 的 ``config.toml``（缺失则从包内默认物化；旧名
      ``electromind.toml`` 一次性改名继承）
    - Project：``<project_root>/.electromind/config.toml``（仅存在时；与 home
      同目录时跳过——dev 模式 home 就是项目目录）
    - Local：``<project_root>/.electromind/config.local.toml``（仅存在时）
    - CLI：``--config <file>`` 显式覆盖
    """
    sources: list[SettingsSource] = [
        SettingsSource(
            "default",
            bundled_default_config(),
            load_config_file(bundled_default_config()),
        )
    ]

    user_path = ensure_home_config(workdir)
    sources.append(SettingsSource("user", user_path, load_config_file(user_path)))

    if include_project:
        root = find_project_root(workdir)
        if root is not None:
            # dev 模式等：项目 .electromind 就是 home → 不重复加载
            project_path = _adopt_legacy(
                root / ".electromind" / HOME_CONFIG_NAME, LEGACY_HOME_CONFIG_NAME
            )
            if project_path.is_file() and project_path.resolve() != user_path.resolve():
                sources.append(
                    SettingsSource(
                        "project", project_path, load_config_file(project_path)
                    )
                )
            local_path = _adopt_legacy(
                root / ".electromind" / LOCAL_CONFIG_NAME, LEGACY_LOCAL_CONFIG_NAME
            )
            if local_path.is_file() and local_path.resolve() != user_path.resolve():
                sources.append(
                    SettingsSource("local", local_path, load_config_file(local_path))
                )

    if config_path is not None:
        explicit = Path(config_path).expanduser()
        if not explicit.is_file():
            raise FileNotFoundError(f"config not found: {explicit}")
        sources.append(SettingsSource("cli", explicit, load_config_file(explicit)))

    return sources


def merge_settings(
    sources: list[SettingsSource],
) -> tuple[Settings, dict[str, str]]:
    """合并各作用域；返回 (Settings, {field: scope})。

    高优先级作用域的已设字段覆盖低优先级；来源记录每个最终字段来自哪个 scope。
    """
    merged = Settings()
    provenance: dict[str, str] = {}
    for source in sources:
        for field in Settings.__dataclass_fields__:
            value = getattr(source.settings, field)
            if value is None:
                continue
            setattr(merged, field, value)
            provenance[field] = source.scope
    return merged, provenance


def _atomic_write_text(target: Path, content: str) -> bool:
    """同目录临时文件完整写入（flush + fsync）后 no-replace 原子发布。

    关键不变量：**目标路径从出现的那一刻起就是完整内容**。先写临时文件（写完
    才 fsync 落盘），再 ``os.link`` 把临时文件发布为最终文件名——link 在目标
    已存在时原子失败（``FileExistsError``），绝无覆盖窗口，也不存在「半截 TOML
    可见」的读取窗口。返回 True = 本调用发布了内容；False = 目标已被并发进程
    创建（以对方为准）。临时文件在两种结局下都被清理。

    - 临时文件名由 ``tempfile.mkstemp`` 生成（O_EXCL 保证唯一）：同进程多线程
      并发不会争用同一名字；
    - 硬链不受支持的文件系统上 **fail-closed**：保留临时文件并抛错，绝不回退
      到会覆盖并发创建的用户配置的 ``os.rename``。
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.tmp", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    try:
        os.link(str(tmp), str(target))
        os.unlink(str(tmp))
        return True
    except FileExistsError:
        os.unlink(str(tmp))
        return False
    except OSError as exc:
        # 文件系统不支持硬链：无真正的 no-replace 原语可用。fail-closed——
        # 保留临时文件便于诊断 / 恢复，绝不 rename 覆盖并发创建的用户配置。
        raise OSError(
            f"无法原子发布配置 {target}：文件系统不支持硬链；"
            f"临时内容保留在 {tmp}（请手动处理）"
        ) from exc


def _adopt_legacy(target: Path, legacy_name: str) -> Path:
    """一次性迁移：新名缺失且旧名文件存在时，把旧文件改名继承（不产生第二事实源）。

    旧名 ``electromind.toml`` / ``electromind.local.toml`` 是改名前的配置文件名；
    迁移只在目标文件不存在时发生，之后全链路只认新名。

    全程 no-replace：
    - 主路径 ``os.link`` + ``os.unlink``：link 在目标已存在时原子失败
      （``FileExistsError``），没有「先检查再 move」的覆盖窗口；legacy 是完整
      文件，link 后目标从出现起就是完整内容；
    - 硬链不受支持的文件系统（如部分网络盘）回退为 ``_atomic_write_text``
      （临时文件 + fsync + no-replace 发布），同样无覆盖窗口、无半写可见——
      并发下目标已被创建则以新文件为准，旧文件保留（已不再被读取）。
    """
    if target.is_file():
        return target
    legacy = target.with_name(legacy_name)
    if not legacy.is_file():
        return target
    try:
        os.link(str(legacy), str(target))
    except FileExistsError:
        # 并发下目标已被创建 → 以新文件为准，旧文件不动（已不再被读取）。
        return target
    except OSError:
        # 不支持硬链 → 临时文件 + fsync + no-replace 发布。
        if _atomic_write_text(target, legacy.read_text(encoding="utf-8")):
            try:
                os.unlink(str(legacy))
            except OSError:
                pass
        # 发布失败（目标已被并发创建）→ 旧文件保留，不再被读取。
    else:
        try:
            os.unlink(str(legacy))
        except OSError:
            pass  # 迁移已生效；旧文件残留无副作用（不再被读取）。
    return target


def ensure_home_config(workdir: str | None = None) -> Path:
    """定位当前 home 的 ``config.toml``；不存在就从包内默认物化一份写盘。

    home 由入口的 ``activate_home`` 决定：``--dev`` → ``<root>/.electromind``，否则
    ``~/.electromind``。种子取包内唯一内置默认
    ``src/electromind/resources/default-config.toml``（随 wheel 打包）；若存在旧名
    ``electromind.toml`` 则先改名继承，不重复物化。

    物化用「临时文件完整写入（flush+fsync）+ no-replace 原子发布」：并发首次
    启动时只有一个进程发布成功，目标文件从出现起就是完整内容——既不会覆盖
    另一个进程刚写好的配置，也不会让并发读取方看到空文件或半截 TOML。
    """
    target = _adopt_legacy(home_config_path(workdir), LEGACY_HOME_CONFIG_NAME)
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(target, BUNDLED_CONFIG.read_text(encoding="utf-8"))
    return target


def load_config(
    *,
    config_path: Path | str | None = None,
    workdir: str | None = None,
) -> ReplConfig:
    """按多 scope 加载配置：Default → User → Project → Local → CLI(--config)。

    未受信任的 Project 作用域不加载（fail-closed）。未设字段回落 ReplConfig
    自身默认（与模板一致），因此手删部分字段的 home 配置仍可正常工作。
    """
    root = find_project_root(workdir)
    include_project = is_project_trusted(root)
    sources = load_settings_sources(
        workdir, config_path=config_path, include_project=include_project
    )
    settings, _provenance = merge_settings(sources)
    return settings.to_repl_config()


def refresh_provider_from_disk(
    config: ReplConfig, *, workdir: str | None = None
) -> ReplConfig:
    """从当前 home 的 ``config.toml`` 刷新 provider 字段。

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


@dataclass(slots=True)
class RunOptions:
    """CLI 单次调用参数（优先级：CLI > Local > Project > User > 内置默认）。

    只承载每次运行相关的字段；持久化字段在 ``Settings``（文件）里。
    """

    prompt: tuple[str, ...] = ()
    thread_id: str | None = None
    continue_last: bool = False
    resume: str | None = None
    resume_interactive: bool = False
    print_mode: bool = False
    mode: str | None = None  # ask | plan | run
    target: str | None = None  # sandbox | local | ssh
    permission_mode: str | None = None
    model: str | None = None
    project: str | None = None
    add_dirs: tuple[str, ...] = ()
    max_iterations: int | None = None
    allowed_tools: tuple[str, ...] | None = None
    disallowed_tools: tuple[str, ...] | None = None
    no_session_persistence: bool = False
    no_color: bool = False
    quiet: bool = False
    verbose: bool = False
    debug: bool = False
    log_file: str | None = None
    input_format: str = "text"
    output_format: str = "text"
    blocking: bool = False
    inline: bool = False
    deprecated_auto: bool = False
    wire: bool = False
    http: bool = False
    host: str = "127.0.0.1"
    port: int = 8848
    backend: str | None = None
    ssh_host: str | None = None
    ssh_config: str | None = None
    config: str | None = None
    dev: str | None = None

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "RunOptions":
        return cls(
            prompt=tuple(getattr(args, "prompt", ()) or ()),
            thread_id=args.thread_id,
            continue_last=bool(getattr(args, "continue_last", False)),
            resume=getattr(args, "resume", None),
            resume_interactive=getattr(args, "resume", None) == "",
            print_mode=bool(getattr(args, "print_mode", False)),
            mode=args.mode,
            target=args.target or args.execution_mode,
            permission_mode=args.permission_mode,
            model=args.model,
            project=args.project,
            add_dirs=tuple(args.add_dir or ()),
            max_iterations=args.max_iterations,
            allowed_tools=tuple(args.allowed_tools or ()) or None,
            disallowed_tools=tuple(args.disallowed_tools or ()) or None,
            no_session_persistence=args.no_session_persistence,
            no_color=args.no_color,
            quiet=args.quiet,
            verbose=args.verbose,
            debug=args.debug,
            log_file=args.log_file,
            input_format=args.input_format,
            output_format=args.output_format,
            blocking=args.blocking,
            inline=bool(getattr(args, "inline", False)),
            deprecated_auto=bool(getattr(args, "deprecated_auto", False)),
            wire=args.wire,
            http=args.http,
            host=args.host,
            port=args.port,
            backend=args.backend,
            ssh_host=args.ssh_host,
            ssh_config=args.ssh_config,
            config=args.config,
            dev=args.dev,
        )

    def apply_to(self, config: ReplConfig) -> ReplConfig:
        """把 CLI 参数叠加到文件配置上；None/False 字段不覆盖。"""
        fields: dict = {}
        if self.thread_id:
            fields["thread_id"] = self.thread_id
        if self.blocking:
            fields["blocking"] = True
        if self.inline:
            fields["inline"] = True
        if self.mode:
            fields["session_mode"] = self.mode
        if self.permission_mode:
            fields["permission_mode"] = self.permission_mode
        if self.deprecated_auto:
            fields["permission_mode"] = "auto"
        if self.target:
            fields["execution_mode"] = self.target
        if self.backend:
            fields["backend"] = self.backend
        if self.project:
            # 归一化成绝对路径：thread.toml 存字面量，相对路径 resume 时会随 cwd 漂移。
            fields["project_path"] = os.path.abspath(os.path.expanduser(self.project))
        if self.model:
            fields["model"] = self.model
        if self.max_iterations is not None:
            fields["max_turns"] = self.max_iterations
        if self.ssh_host:
            fields["ssh_host"] = self.ssh_host
        if self.ssh_config:
            fields["ssh_config"] = self.ssh_config
        if self.allowed_tools is not None:
            fields["agent_tools"] = self.allowed_tools
        if self.disallowed_tools:
            current = config.resolved_agent_tools()
            fields["agent_tools"] = tuple(
                tool for tool in current if tool not in self.disallowed_tools
            )
        return replace(config, **fields) if fields else config


def config_from_args(args: argparse.Namespace) -> ReplConfig:
    """兼容旧调用：Settings（文件）与 RunOptions（CLI）合并成 ReplConfig。"""
    if getattr(args, "dev", None) is not None:
        activate_home("dev", args.dev)
    else:
        activate_home("prod")
    config = load_config(config_path=args.config)
    config = RunOptions.from_args(args).apply_to(config)

    # --continue: find latest session for current project
    if getattr(args, "continue_last", False):
        from app.sessions import find_latest_session

        latest = find_latest_session()
        if latest:
            config = replace(config, thread_id=latest.id)
        else:
            # 验收 G-9：参数/配置错误 → exit 2（SystemExit 带字符串会退成 1）
            import sys

            print("没有找到可恢复的会话", file=sys.stderr)
            raise SystemExit(EXIT_CLI)

    # --resume <id>: direct resume by thread ID
    if getattr(args, "resume", None) is not None and args.resume != "":
        from app.sessions import find_session_by_id

        session = find_session_by_id(args.resume)
        if session is None:
            import sys

            print(f"会话不存在: {args.resume}", file=sys.stderr)
            raise SystemExit(EXIT_CLI)
        config = replace(config, thread_id=args.resume)

    # --resume without ID: interactive picker (deferred to main())
    if getattr(args, "resume", None) == "":
        config = replace(config, resume_interactive=True)

    return config
