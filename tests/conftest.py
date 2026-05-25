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
