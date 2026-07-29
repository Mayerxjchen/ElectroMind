"""DockerBackend —— 在 docker 容器里跑命令。

宿主 workdir 通过 `-v <workdir>:<workdir>` bind mount 到容器里的同名路径，
所以文件 API 直接落到宿主机 fs，exec 通过 `docker exec` 落到容器里。

需要用户显式传 `image`（Sandbox.create(image=..., backend="docker")）。
"""

from __future__ import annotations

from .container import ContainerBackend


class DockerBackend(ContainerBackend):
    def __init__(self) -> None:
        super().__init__(cli="docker", computer_name="Docker 计算节点")
