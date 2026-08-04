"""执行模式解析器测试：默认 sandbox、显式 local、容器回退、旧配置迁移、错误处理。"""

from __future__ import annotations

import pytest

from electromind.execution import resolve_execution
from electromind.execution.probe import ContainerRuntimeProbe, RuntimeProbeResult
from electromind.execution.resolver import (
    ContainerRuntimeUnavailableError,
    ExecutionResolutionError,
    InvalidExecutionModeError,
    InvalidSandboxBackendError,
)


def _probe_docker_ok() -> ContainerRuntimeProbe:
    class _P(ContainerRuntimeProbe):
        def probe(self, runtime):
            if runtime == "docker":
                return RuntimeProbeResult(
                    runtime="docker",
                    usable=True,
                    executable_found=True,
                    service_reachable=True,
                    error_code=None,
                    message="ok",
                )
            return RuntimeProbeResult(
                runtime="podman",
                usable=False,
                executable_found=False,
                service_reachable=False,
                error_code="not_found",
                message="nope",
            )

    return _P()


def _probe_none() -> ContainerRuntimeProbe:
    class _P(ContainerRuntimeProbe):
        def probe(self, runtime):
            return RuntimeProbeResult(
                runtime=runtime,
                usable=False,
                executable_found=False,
                service_reachable=False,
                error_code="not_found",
                message="nope",
            )

    return _P()


# --- 默认行为 ---


def test_default_mode_is_sandbox():
    """有 Docker 时默认 sandbox 成功。"""
    r = resolve_execution(runtime_probe=_probe_docker_ok())
    assert r.mode == "sandbox"
    assert r.resolved_backend == "docker"
    assert r.isolated


def test_default_mode_fails_when_no_container():
    """无 Docker/Podman 时默认 sandbox 抛出错误。"""
    with pytest.raises(ContainerRuntimeUnavailableError):
        resolve_execution(runtime_probe=_probe_none())


# --- local 模式 ---


def test_local_mode():
    r = resolve_execution("local")
    assert r.mode == "local"
    assert r.resolved_backend == "local"
    assert not r.isolated
    assert r.warning is not None


# --- sandbox 模式 ---


def test_sandbox_docker_first():
    r = resolve_execution("sandbox", runtime_probe=_probe_docker_ok())
    assert r.resolved_backend == "docker"
    assert r.isolated


def test_sandbox_no_container_throws():
    with pytest.raises(ContainerRuntimeUnavailableError):
        resolve_execution("sandbox", runtime_probe=_probe_none())


def test_sandbox_explicit_docker():
    r = resolve_execution(
        "sandbox", sandbox_backend="docker", runtime_probe=_probe_docker_ok()
    )
    assert r.resolved_backend == "docker"


def test_explicit_podman_fails_when_unavailable():
    with pytest.raises(ContainerRuntimeUnavailableError):
        resolve_execution(
            "sandbox", sandbox_backend="podman", runtime_probe=_probe_none()
        )


# --- ssh 模式 ---


def test_ssh_mode():
    r = resolve_execution("ssh", ssh_config={"host": "hpc.example.com"})
    assert r.mode == "ssh"
    assert r.resolved_backend == "ssh"
    assert not r.isolated


def test_ssh_without_host_throws():
    with pytest.raises(ExecutionResolutionError):
        resolve_execution("ssh", ssh_config={"port": 22})


def test_ssh_with_host_succeeds():
    r = resolve_execution("ssh", ssh_config={"host": "hpc.example.com"})
    assert r.mode == "ssh"
    assert r.resolved_backend == "ssh"


def test_invalid_sandbox_backend_throws():
    with pytest.raises(InvalidSandboxBackendError):
        resolve_execution(
            "sandbox", sandbox_backend="local", runtime_probe=_probe_docker_ok()
        )


# --- 无效输入抛出错误 ---


def test_invalid_mode_throws():
    with pytest.raises(InvalidExecutionModeError):
        resolve_execution("garbage")


# --- 旧配置迁移 ---


def test_legacy_produces_warning_when_no_explicit_mode():
    r = resolve_execution(
        legacy_backend="local",
        legacy_command_policy="open",
        runtime_probe=_probe_docker_ok(),
    )
    assert r.mode == "sandbox"
    assert any(d.code == "legacy_execution_config" for d in r.diagnostics)


def test_legacy_not_triggered_when_mode_is_set():
    r = resolve_execution("local", legacy_backend="container")
    assert not any(d.code == "legacy_execution_config" for d in r.diagnostics)


# --- to_dict ---


def test_to_dict():
    r = resolve_execution("local")
    d = r.to_dict()
    assert d["mode"] == "local"
    assert d["resolved_backend"] == "local"
    assert isinstance(d["isolated"], bool)
