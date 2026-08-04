"""R6 终端能力探测：TERM=dumb / 非 TTY 自动降级。"""

from __future__ import annotations

import pytest

from app.tui.capabilities import (
    color_supported,
    fullscreen_supported,
    terminal_profile,
    unicode_supported,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.delenv("LANG", raising=False)


def test_non_tty_no_fullscreen_no_color(monkeypatch):
    monkeypatch.setattr("app.tui.capabilities.sys.stdout.isatty", lambda: False)
    assert fullscreen_supported() is False
    assert color_supported() is False


def test_dumb_term_no_fullscreen(monkeypatch):
    monkeypatch.setattr("app.tui.capabilities.sys.stdout.isatty", lambda: True)
    monkeypatch.setenv("TERM", "dumb")
    assert fullscreen_supported() is False
    assert color_supported() is False


def test_unset_term_fail_closed(monkeypatch):
    """TERM 未设置 → 保守降级：无 full-screen、无颜色（除非 COLORTERM 明确）。"""
    monkeypatch.setattr("app.tui.capabilities.sys.stdout.isatty", lambda: True)
    assert fullscreen_supported() is False
    assert color_supported() is False
    monkeypatch.setenv("COLORTERM", "truecolor")
    assert color_supported() is True  # COLORTERM 明确覆盖


def test_colorterm_truecolor(monkeypatch):
    monkeypatch.setattr("app.tui.capabilities.sys.stdout.isatty", lambda: True)
    monkeypatch.setenv("COLORTERM", "truecolor")
    assert color_supported() is True


def test_explicit_color_override_wins(monkeypatch):
    monkeypatch.setattr("app.tui.capabilities.sys.stdout.isatty", lambda: True)
    monkeypatch.setenv("TERM", "dumb")
    assert color_supported(explicit=False) is False
    assert color_supported(explicit=True) is True


def test_unicode_utf8_lang(monkeypatch):
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    assert unicode_supported() is True


def test_profile_shape(monkeypatch):
    monkeypatch.setattr("app.tui.capabilities.sys.stdout.isatty", lambda: True)
    profile = terminal_profile()
    assert set(profile) == {"tty", "fullscreen", "color", "unicode"}
    assert profile["tty"] is True
