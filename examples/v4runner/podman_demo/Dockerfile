# PodmanBackend 示例镜像 —— 一个够跑 Python 的最小镜像。
#
# 目的：给 agent 一个隔离的容器电脑跑东西，避免污染宿主机。
# 用法：
#     cd examples/v4runner/podman_demo
#     podman build -t pagent-podman-demo:latest .
#     export DEEPSEEK_API_KEY=...
#     uv run python examples/v4runner/podman_demo/demo.py
#
# 换成 docker 也一样：
#     docker build -t pagent-podman-demo:latest .
#     uv run python examples/v4runner/podman_demo/demo.py --backend docker

FROM python:3.11-slim

# 常用调试工具：curl / procps / 基础 shell 已经在 slim 里。
# 装点顺手的：
# - jq：让 agent 处理 JSON
# - uv：sandbox.describe() 会探 `uv --version`，能用 uv 时 system prompt
#   会告诉 agent 用 `uv venv` 装依赖，避免污染系统 Python
RUN apt-get update \
    && apt-get install -y --no-install-recommends jq curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx

# 让 sandbox 工作目录预建好。agent 视角的 /home/agent 会被门面
# 翻译成宿主 workdir，容器里通过 bind mount 落到同名路径。
RUN mkdir -p /home/agent
WORKDIR /home/agent

CMD ["sleep", "infinity"]
