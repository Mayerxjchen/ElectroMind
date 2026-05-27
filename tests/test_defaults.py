from pagent import DEFAULT_TOOLS, bash, clock, readfile, region
from pagent.defaults import parse_bash_argv, resolve_readfile_path


def test_default_tools_order():
    assert [t.name for t in DEFAULT_TOOLS] == ["clock", "region"]


def test_clock_returns_iso():
    out = clock.call("{}")
    assert out.ok is True
    assert "T" in out.content or ":" in out.content


def test_region_has_hints():
    out = region.call({})
    for key in (
        "locale=",
        "encoding=",
        "timezone_abbr=",
        "LC_ALL=",
        "preferred_encoding=",
    ):
        assert key in out.content


def test_readfile_reads_under_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sample = tmp_path / "hello.txt"
    sample.write_text("hello pagent", encoding="utf-8")

    out = readfile.call(f'{{"path": "{sample}"}}')
    assert out.ok is True
    assert "hello pagent" in out.content
    assert "hello.txt" in out.content


def test_readfile_reads_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")

    out = readfile.call('{"path": "hello.txt"}')
    assert out.ok is True
    assert "hi" in out.content


def test_readfile_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "home.txt").write_text("from home", encoding="utf-8")

    out = readfile.call('{"path": "~/home.txt"}')
    assert out.ok is True
    assert "from home" in out.content


def test_readfile_rejects_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    out = readfile.call(f'{{"path": "{outside}"}}')
    assert out.ok is False
    assert "outside workspace" in out.content


def test_resolve_readfile_path_empty():
    path, err = resolve_readfile_path("  ")
    assert path is None
    assert "empty path" in err


def test_readfile_limits_utf_code_points(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    text = "中" * 600
    (tmp_path / "big.txt").write_text(text, encoding="utf-8")

    big = tmp_path / "big.txt"
    out = readfile.call(f'{{"path": "{big}", "max_chars": 500}}')
    assert out.ok is True
    body = out.content.split("---\n", 1)[-1]
    assert len(body) == 500
    assert "continues at offset 500" in out.content


def test_readfile_offset_reads_next_chunk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    text = "a" * 800
    (tmp_path / "chunked.txt").write_text(text, encoding="utf-8")

    first = readfile.call(
        f'{{"path": "{tmp_path / "chunked.txt"}", "max_chars": 500, "offset": 0}}'
    )
    second = readfile.call(
        f'{{"path": "{tmp_path / "chunked.txt"}", "max_chars": 500, "offset": 500}}'
    )
    assert first.ok is True
    assert second.ok is True
    assert first.content.split("---\n", 1)[-1] == "a" * 500
    assert second.content.split("---\n", 1)[-1] == "a" * 300
    assert "continues at offset 500" in first.content
    assert "continues at offset" not in second.content.split(") ---")[0]


def test_bash_ls_lists_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "visible.txt").write_text("x", encoding="utf-8")

    out = bash.call('{"command": "ls"}')
    assert out.ok is True
    assert "visible.txt" in out.content


def test_bash_ls_with_flags(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    out = bash.call('{"command": "ls -la"}')
    assert out.ok is True
    assert "a.txt" in out.content


def test_bash_rejects_non_whitelisted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    out = bash.call('{"command": "rm -rf /"}')
    assert out.ok is False
    assert "not allowed" in out.content


def test_bash_rejects_shell_injection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    out = bash.call('{"command": "ls; echo pwned"}')
    assert out.ok is False
    assert "not allowed" in out.content


def test_bash_rejects_path_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "secret_dir"
    outside.mkdir(exist_ok=True)

    out = bash.call(f'{{"command": "ls {outside}"}}')
    assert out.ok is False
    assert "outside workspace" in out.content


def test_parse_bash_argv_empty():
    parts, err = parse_bash_argv("   ")
    assert parts is None
    assert "empty command" in err


def test_readfile_offset_past_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tiny.txt").write_text("hi", encoding="utf-8")

    out = readfile.call(f'{{"path": "{tmp_path / "tiny.txt"}", "offset": 10}}')
    assert out.ok is False
    assert "past end" in out.content
