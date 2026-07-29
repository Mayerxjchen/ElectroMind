import pytest

from electromind.paths import reset_home

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
def isolate_electromind_home(tmp_path, monkeypatch):
    """默认 ``~/.electromind/*`` 落到测试临时目录，避免污染真实 home。"""
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def reset_active_home():
    """清空进程级 electromind home，避免用例间 activate_home 泄漏。"""
    reset_home()
    yield
    reset_home()
