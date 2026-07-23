"""把 ReplConfig 序列化成给前端展示的 JSON：api_key 脱敏，只回是否已配置。

wire / http 的 ``get_config`` 命令用它下发配置快照，前端据此渲染设置面板；
``set_provider`` 写盘后也回读一份快照确认生效。api_key 从不原样下发。
"""

from __future__ import annotations

from .config import ReplConfig


def mask_api_key(api_key: str | None) -> str:
    """脱敏：只保留尾部 4 位，其余用 * 遮蔽；空则返回空串。"""
    key = (api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 4:
        return "*" * len(key)
    return "*" * (len(key) - 4) + key[-4:]


def config_to_public_dict(config: ReplConfig) -> dict:
    """ReplConfig → 面向前端的字典。api_key 脱敏，附 configured 布尔位。"""
    resolved_key = config.resolved_api_key()
    return {
        "provider": {
            "model": config.resolved_model(),
            "base_url": config.provider_base_url or "",
            "api_key_masked": mask_api_key(resolved_key),
            "api_key_configured": bool(resolved_key),
        },
        "sandbox": {
            "backend": config.backend or "",
            "image": config.image or "",
            "command_policy": config.command_policy or "",
        },
        "runner": {
            "location": config.resolved_runner_location(),
            "max_turns": config.resolved_max_turns(),
        },
        "permission": {
            "mode": config.resolved_permission_mode(),
        },
        "project": {
            "path": config.project_path or "",
        },
    }
