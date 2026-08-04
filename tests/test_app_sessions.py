"""Coverage + 行为：app/sessions.py（会话扫描/解析/格式化纯逻辑）。

覆盖 _relative_time / _is_deleted / _project_basename / _iter_thread_dirs /
_load_metainfo / list_sessions / find_* / format_session_table，满足 A+ v1.0
真实覆盖率 ≥78%（percent_covered 原始值，非四舍五入）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.sessions import (
    SessionInfo,
    _is_deleted,
    _project_basename,
    _relative_time,
    format_session_table,
    list_sessions,
)


def _thread_dir(root: Path, thread_id: str, *, meta: dict | None = None) -> Path:
    """Create a valid thread dir: must contain SPEC_FILENAME (thread.toml)
    for the production scanner to recognize it, plus optional metainfo.json."""
    from electromind.ithread import SPEC_FILENAME

    d = root / "threads" / thread_id
    d.mkdir(parents=True, exist_ok=True)
    # 最小有效 thread.toml —— 生产扫描（sessions._iter_thread_dirs）只把含
    # SPEC_FILENAME 的目录识别为 thread；不放宽生产约束。
    (d / SPEC_FILENAME).write_text('backend = "local"\n', encoding="utf-8")
    if meta is not None:
        (d / "metainfo.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


class TestPureHelpers:
    def test_relative_time_empty(self):
        assert _relative_time("") == "—"

    def test_relative_time_invalid(self):
        assert _relative_time("not-a-date") == "not-a-date"

    def test_relative_time_just_now(self):
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        assert _relative_time(now.isoformat()) == "刚刚"

    def test_relative_time_minutes(self):
        import datetime

        t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
        assert _relative_time(t.isoformat()) == "5 分钟前"

    def test_relative_time_hours(self):
        import datetime

        t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)
        assert _relative_time(t.isoformat()) == "3 小时前"

    def test_relative_time_yesterday(self):
        import datetime

        t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        assert _relative_time(t.isoformat()) == "昨天"

    def test_relative_time_days(self):
        import datetime

        t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)
        assert _relative_time(t.isoformat()) == "3 天前"

    def test_relative_time_older_renders_date(self):
        import datetime

        t = datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc)
        assert _relative_time(t.isoformat()) == "01 月 15 日"

    def test_is_deleted_false_when_absent(self):
        assert _is_deleted({}) is False

    def test_is_deleted_false_when_blank(self):
        assert _is_deleted({"deleted_at": "   "}) is False

    def test_is_deleted_true(self):
        assert _is_deleted({"deleted_at": "2026-08-01T00:00:00+08:00"}) is True

    def test_project_basename_empty(self):
        assert _project_basename("") == "—"

    def test_project_basename_path(self):
        assert _project_basename("/home/user/my-project") == "my-project"


class TestScanning:
    def test_list_sessions_empty_home(self, tmp_path):
        assert list_sessions(home=tmp_path) == []

    def test_list_sessions_filters_deleted(self, tmp_path):
        _thread_dir(tmp_path, "gone", meta={"deleted_at": "x"})
        _thread_dir(tmp_path, "alive", meta={"title": "A"})
        sessions = list_sessions(home=tmp_path)
        ids = [s.id for s in sessions]
        assert ids == ["alive"]
        assert "gone" not in ids

    def test_list_sessions_skips_non_thread_dirs(self, tmp_path):
        # 无 spec 文件的目录不是 thread
        (tmp_path / "threads").mkdir(parents=True)
        (tmp_path / "threads" / "not-a-thread").mkdir()
        assert list_sessions(home=tmp_path) == []

    def test_list_sessions_parses_metadata(self, tmp_path):
        _thread_dir(
            tmp_path,
            "t1",
            meta={
                "title": "Hello",
                "message_count": 7,
                "last_run_status": "completed",
                "updated_at": "2026-08-04T10:00:00+08:00",
            },
        )
        s = list_sessions(home=tmp_path)[0]
        assert s.id == "t1"
        assert s.title == "Hello"
        assert s.message_count == 7
        assert s.status == "completed"
        assert s.updated_at == "2026-08-04T10:00:00+08:00"

    def test_list_sessions_bad_metainfo_ignored(self, tmp_path):
        d = _thread_dir(tmp_path, "t1")
        (d / "metainfo.json").write_text("{not json", encoding="utf-8")
        s = list_sessions(home=tmp_path)[0]
        assert s.id == "t1"
        assert s.title == ""

    def test_list_sessions_metainfo_non_dict(self, tmp_path):
        d = _thread_dir(tmp_path, "t1")
        (d / "metainfo.json").write_text('"just-a-string"', encoding="utf-8")
        assert list_sessions(home=tmp_path)[0].id == "t1"


class TestFind:
    def test_find_by_id(self, tmp_path, monkeypatch):
        _thread_dir(tmp_path, "t1", meta={"title": "T"})
        monkeypatch.setattr("app.sessions.default_electromind_home", lambda: tmp_path)
        from app.sessions import find_session_by_id

        assert find_session_by_id("t1").id == "t1"
        assert find_session_by_id("missing") is None

    def test_format_table_empty(self):
        assert format_session_table([]) == "(no sessions)"

    def test_format_table_renders(self):
        s = SessionInfo(
            id="t1",
            title="Run",
            project_name="proj",
            message_count=3,
            updated_at="",
            status="completed",
        )
        table = format_session_table([s])
        assert "t1" in table
        assert "Run" in table
        assert "proj" in table
        assert "completed" in table
