from pagent import DEFAULT_TOOLS, clock, region


def test_default_tools_order():
    assert [t.name for t in DEFAULT_TOOLS] == ["clock", "region"]


def test_clock_returns_iso():
    out = clock.call("{}")
    assert "T" in out or ":" in out


def test_region_has_hints():
    out = region.call({})
    for key in (
        "locale=",
        "encoding=",
        "timezone_abbr=",
        "LC_ALL=",
        "preferred_encoding=",
    ):
        assert key in out
