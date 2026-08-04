from app.render import (
    LOGO_LINES,
    box_line_width,
    display_width,
    format_banner,
    format_logo,
    row,
)
from electromind import RunState


def test_logo_fits_in_box_width():
    for line in LOGO_LINES:
        assert display_width(line) <= box_line_width()


def test_format_logo_renders_all_lines():
    text = format_logo(color=False)
    assert text.splitlines() == list(LOGO_LINES)


def test_row_aligns_with_cjk_status():
    line = row("thread", "thread-demo · 新建", color=False)
    assert line.startswith("│")
    assert line.endswith("│")
    assert display_width(line) == box_line_width()


def test_box_top_and_row_share_width():
    from app.render import box_top

    top = box_top(color=False)
    line = row("model", "deepseek-v4-flash", color=False)
    assert display_width(top) == display_width(line)


def test_banner_contains_key_fields():
    class FakeAgent:
        max_turns = 24

    class FakeThread:
        created = True
        id = "thread-demo"
        ignored_overrides = ()
        project_path = "/work/repo"
        spec = type("Spec", (), {"model": "deepseek-v4-flash", "backend": "local"})()

    class FakeSandbox:
        home = "/home/agent"
        workdir = "/tmp/workspace"

    class FakeSkills:
        def names(self):
            return []

    class FakeRunner:
        thread = FakeThread()
        sandbox = FakeSandbox()
        messages = type("M", (), {"data": []})()
        agent = FakeAgent()
        skills = FakeSkills()
        run_state = RunState()

    text = format_banner(FakeRunner(), color=False)
    assert "electromind" in text
    assert "thread-demo" in text
    assert "空闲" in text
    assert "deepseek-v4-flash" in text
    assert "local" in text
    assert "/work/repo" in text
    assert "/exit" in text
