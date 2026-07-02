"""PodmanBackend —— 与 DockerBackend 结构一致，CLI 换成 `podman`。

rootless 模式下用户 UID 可能与容器内不一致，如果需要跨用户读写，
在 spec.command 里自己带 `--userns=keep-id` 或者预先配好。
"""

from __future__ import annotations

from .container import ContainerBackend


class PodmanBackend(ContainerBackend):
    def __init__(self) -> None:
        super().__init__(cli="podman", computer_name="Podman 计算节点")
