from app.render import box_line_width, display_width, format_banner, row


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
        max_turns = 12

    class FakeThread:
        created = True
        id = "thread-demo"
        ignored_overrides = ()
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

    text = format_banner(FakeRunner(), color=False)
    assert "pagent" in text
    assert "thread-demo" in text
    assert "deepseek-v4-flash" in text
    assert "local" in text
    assert "/exit" in text
