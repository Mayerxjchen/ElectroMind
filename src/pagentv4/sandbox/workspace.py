"""Workspace 解析：workspace_id ↔ 宿主 workdir。

规则：
- 显式 workdir：直接使用（转成绝对路径），负责创建目录。
- 显式 workspace_id：映射到 <cwd>/.pagent/workspaces/<id>，同名沙箱共享目录。
- 都不给：拒绝，避免一次性沙箱丢数据。
- 两者都给：workdir 优先，workspace_id 忽略。

默认根路径可用环境变量 PAGENT_WORKSPACES_DIR 覆盖。
"""

from __future__ import annotations

import os
import re

WORKSPACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")


def default_workspaces_root() -> str:
    override = os.environ.get("PAGENT_WORKSPACES_DIR")
    if override:
        return os.path.abspath(override)
    return os.path.join(os.getcwd(), ".pagent", "workspaces")


def resolve_workdir(*, workspace_id: str | None, workdir: str | None) -> str:
    if workdir is not None:
        resolved = os.path.abspath(workdir)
        os.makedirs(resolved, exist_ok=True)
        return resolved

    if workspace_id is None:
        raise ValueError("must provide either workspace_id or workdir")

    if not WORKSPACE_ID_PATTERN.match(workspace_id):
        raise ValueError(
            f"invalid workspace_id: {workspace_id!r}; "
            "must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}"
        )

    resolved = os.path.join(default_workspaces_root(), workspace_id)
    os.makedirs(resolved, exist_ok=True)
    return resolved
