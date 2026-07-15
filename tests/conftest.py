import pytest

PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


@pytest.fixture(autouse=True)
def clear_proxy_env(monkeypatch):
    for name in PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolate_pagent_home(tmp_path, monkeypatch):
    """默认 ``~/.pagent/*`` 落到测试临时目录，避免污染真实 home。"""
    monkeypatch.setenv("HOME", str(tmp_path))
