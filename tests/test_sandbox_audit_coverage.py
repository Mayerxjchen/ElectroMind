"""Coverage + 行为：sandbox/audit.py（append-only 审计日志）。

覆盖 AuditLog.record / read / count_since 的正常与错误路径
（文件缺失、损坏 JSON、写失败不阻塞操作），补足 A+ v1.0 真实覆盖率。
"""

from __future__ import annotations

from electromind.sandbox.audit import AuditEntry, AuditLog


def _entry(timestamp: float = 100.0, **kw) -> AuditEntry:
    base = dict(
        timestamp=timestamp,
        thread_id="t1",
        operation="command_exec",
        target="ls -la",
        autonomy="auto-safe",
        session_mode="agent",
        backend="local",
        isolated=False,
        outcome="allowed",
    )
    base.update(kw)
    return AuditEntry(**base)


class TestAuditLog:
    def test_record_and_read_roundtrip(self, tmp_path):
        log = AuditLog(tmp_path)
        log.record(_entry(timestamp=1.0))
        log.record(_entry(timestamp=2.0, operation="file_write", target="/a"))
        entries = log.read()
        assert len(entries) == 2
        assert entries[0]["timestamp"] == 1.0
        assert entries[1]["operation"] == "file_write"

    def test_read_missing_file_returns_empty(self, tmp_path):
        log = AuditLog(tmp_path / "nope")
        assert log.read() == []

    def test_read_skips_corrupt_lines(self, tmp_path):
        log = AuditLog(tmp_path)
        log.record(_entry(timestamp=1.0))
        path = log._path
        with path.open("a", encoding="utf-8") as f:
            f.write("{corrupt json\n")
        entries = log.read()
        assert [e["timestamp"] for e in entries] == [1.0]

    def test_read_limit(self, tmp_path):
        log = AuditLog(tmp_path)
        for i in range(5):
            log.record(_entry(timestamp=float(i)))
        entries = log.read(limit=2)
        assert len(entries) == 2
        assert entries[-1]["timestamp"] == 4.0

    def test_read_ignores_blank_lines(self, tmp_path):
        log = AuditLog(tmp_path)
        log.record(_entry(timestamp=1.0))
        with log._path.open("a", encoding="utf-8") as f:
            f.write("\n\n")
        assert len(log.read()) == 1

    def test_count_since_missing_file(self, tmp_path):
        assert AuditLog(tmp_path / "none").count_since(0) == 0

    def test_count_since_filters(self, tmp_path):
        log = AuditLog(tmp_path)
        log.record(_entry(timestamp=1.0))
        log.record(_entry(timestamp=5.0))
        log.record(_entry(timestamp=9.0))
        assert log.count_since(5.0) == 2
        assert log.count_since(100.0) == 0

    def test_count_since_skips_corrupt(self, tmp_path):
        log = AuditLog(tmp_path)
        log.record(_entry(timestamp=5.0))
        with log._path.open("a", encoding="utf-8") as f:
            f.write("garbage\n")
        assert log.count_since(0) == 1

    def test_record_write_failure_does_not_raise(self, tmp_path, monkeypatch):
        """审计写失败绝不能阻塞操作（record 吞 OSError）。"""
        log = AuditLog(tmp_path)

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("builtins.open", _boom)
        log.record(_entry())  # 不得抛异常
