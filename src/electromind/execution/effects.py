"""ToolEffect — 工具副作用声明（M4 §9.1）。

- 未声明 Effect 的工具不能注册到正式 Runner（``assert_effects_declared``）。
- Approval 和调度策略根据 Effect 判断，而不是仅根据工具名称。
- Effect 进入 Tool Schema 或运行时元数据。
"""

from __future__ import annotations

from enum import StrEnum

from ..core.tool import FunctionTool


class ToolEffect(StrEnum):
    PURE = "pure"  # 无副作用（纯计算）
    READ_WORKSPACE = "read_workspace"  # 只读工作区
    WRITE_WORKSPACE = "write_workspace"  # 写工作区
    READ_HOST = "read_host"  # 只读宿主
    WRITE_HOST = "write_host"  # 写宿主
    NETWORK = "network"  # 网络访问
    EXECUTE = "execute"  # 执行命令（shell 可动任何东西）
    SUBMIT_EXTERNAL = "submit_external"  # 外部提交（job/上传）
    DESTRUCTIVE = "destructive"  # 破坏性（删除/覆盖/格式化）


class ToolRegistrationError(ValueError):
    """未声明 Effect 的工具进入正式 Runner。"""


def assert_effects_declared(tools: list[FunctionTool]) -> None:
    """正式 Runner 注册门：每个工具必须有 Effect 声明。"""
    missing = [t.name for t in tools if t.effect is None]
    if missing:
        raise ToolRegistrationError(
            f"以下工具未声明 effect，不能注册到正式 Runner: {sorted(missing)}"
        )


# 内置工具名 → Effect 静态表（工厂未显式声明时按名补全）
BUILTIN_TOOL_EFFECTS: dict[str, ToolEffect] = {
    # sandbox 工具
    "read_file": ToolEffect.READ_WORKSPACE,
    "list_dir": ToolEffect.READ_WORKSPACE,
    "list_host_files": ToolEffect.READ_HOST,
    "write_file": ToolEffect.WRITE_WORKSPACE,
    "str_replace": ToolEffect.WRITE_WORKSPACE,
    "copy_from_host": ToolEffect.WRITE_WORKSPACE,  # 读宿主 + 写工作区，取更重者
    "copy_to_host": ToolEffect.WRITE_HOST,  # 写宿主 artifacts/
    "run_command": ToolEffect.EXECUTE,
    # harness 工具
    "web_search": ToolEffect.NETWORK,
    "fetch_url": ToolEffect.NETWORK,
    "use_skill": ToolEffect.PURE,
    "delegate_to_subagent": ToolEffect.PURE,  # 委派本身无外部副作用
}


def effect_for_name(name: str) -> ToolEffect | None:
    """按工具名取内置 Effect 声明（未知名返回 None）。"""
    return BUILTIN_TOOL_EFFECTS.get(name)


def apply_builtin_effects(tools: list[FunctionTool]) -> list[FunctionTool]:
    """为未声明 effect 的内置工具补全声明（返回新列表，不原地改）。"""
    resolved: list[FunctionTool] = []
    for tool in tools:
        if tool.effect is not None:
            resolved.append(tool)
            continue
        builtin = BUILTIN_TOOL_EFFECTS.get(tool.name)
        resolved.append(tool.with_effect(builtin) if builtin is not None else tool)
    return resolved


# 风险分类（M4 §9.4）：Effect → 基础风险
EFFECT_RISK: dict[ToolEffect, str] = {
    ToolEffect.PURE: "low",
    ToolEffect.READ_WORKSPACE: "low",
    ToolEffect.READ_HOST: "low",
    ToolEffect.WRITE_WORKSPACE: "medium",
    ToolEffect.NETWORK: "medium",
    ToolEffect.EXECUTE: "high",
    ToolEffect.WRITE_HOST: "high",
    ToolEffect.SUBMIT_EXTERNAL: "high",
    ToolEffect.DESTRUCTIVE: "critical",
}


def risk_of_effect(effect: ToolEffect) -> str:
    return EFFECT_RISK.get(effect, "medium")
