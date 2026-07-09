# pagent app 默认 agent 镜像 —— Alpine + uv(Python) + Node。
#
# 不用 python:* 基础镜像，避免系统 Python 与 uv 重复；Python 由 uv 安装。
# Alpine 比 Debian slim 小很多；Node 走 apk（比 nvm 更瘦，无版本切换）。
# 预装：curl、jq、git、uv、node/npm。
#
# 注意：musl 环境，少数带 glibc 二进制的 wheel 可能不兼容。
#
# 用法：
#     docker build -t pagent:latest -f src/app/Dockerfile src/app
#     # 或
#     cd src/app && docker build -t pagent:latest .
#
# bundled pagent.toml 默认 backend=podman, image=pagent:latest

FROM alpine:3.21

ARG PYTHON_VERSION=3.12

RUN apk add --no-cache \
        bash \
        ca-certificates \
        curl \
        git \
        jq \
        nodejs \
        npm \
        tar \
        xz

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx

ENV UV_PYTHON_PREFERENCE=only-managed
RUN uv python install "$PYTHON_VERSION" \
    && ln -sf "$(uv python find "$PYTHON_VERSION")" /usr/local/bin/python3 \
    && ln -sf python3 /usr/local/bin/python \
    && uv cache clean \
    && rm -rf /root/.cache

RUN mkdir -p /home/agent
WORKDIR /home/agent

CMD ["sleep", "infinity"]
