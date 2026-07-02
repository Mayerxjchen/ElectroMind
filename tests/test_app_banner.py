from app.repl import format_banner


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
