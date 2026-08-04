"""service 命令：daemon start/status/stop/logs 生命周期。"""

from __future__ import annotations

from app.commands import service as service_cmd
from app.exitcodes import EXIT_CLI, EXIT_OK


def _pid() -> int | None:
    return service_cmd._read_pid()


def test_status_not_running(capsys):
    assert service_cmd.run(["status"]) == EXIT_OK
    assert "未运行" in capsys.readouterr().out


def test_start_status_stop_lifecycle(capsys, monkeypatch):
    """真实 daemon：start（随机端口）→ status → stop。"""
    # 隔离 home 保证 PID 文件位置可预期（conftest 已隔离 HOME）
    import random

    port = 19000 + random.randint(0, 500)
    try:
        code = service_cmd.run(["start", "--port", str(port)])
        assert code == EXIT_OK, capsys.readouterr().err
        assert str(port) in capsys.readouterr().out  # 端口透传生效
        pid = _pid()
        assert pid is not None and service_cmd._alive(pid)

        assert service_cmd.run(["status"]) == EXIT_OK
        assert "运行中" in capsys.readouterr().out

        # 健康检查就绪
        import urllib.request

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=2
        ) as resp:
            assert resp.status == 200
    finally:
        if _pid() is not None:
            service_cmd.run(["stop"])

    assert service_cmd.run(["status"]) == EXIT_OK
    assert "未运行" in capsys.readouterr().out


def test_stop_without_pid(capsys):
    assert service_cmd.run(["stop"]) == EXIT_OK
    assert "未运行" in capsys.readouterr().out


def test_logs_missing_file(capsys):
    assert service_cmd.run(["logs"]) == EXIT_CLI
    assert "日志不存在" in capsys.readouterr().err


def test_start_twice_rejects(capsys):
    """已在运行时 start → 明确报错（不启动第二个实例）。"""
    import random

    port = 19500 + random.randint(0, 400)
    try:
        assert service_cmd.run(["start", "--port", str(port)]) == EXIT_OK
        code = service_cmd.run(["start", "--port", str(port)])
        assert code == EXIT_CLI
        assert "已在运行" in capsys.readouterr().err
    finally:
        if _pid() is not None:
            service_cmd.run(["stop"])
