import sys
from pathlib import Path

import pytest

_ACP_DIR = Path(__file__).resolve().parents[1] / "examples" / "acp_agent"
sys.path.insert(0, str(_ACP_DIR))
from tools import calc, glob_paths, grep_code


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def hello():\n    return 42\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    return tmp_path


def test_grep_code(workspace):
    out = grep_code.call('{"pattern": "def hello", "path": "."}')
    assert "app.py:1" in out.content


def test_glob_paths(workspace):
    out = glob_paths.call('{"pattern": "**/*.py"}')
    assert "src/app.py" in out.content


def test_calc():
    assert calc.call('{"expression": "2 + 3 * 4"}').content == "14"
    assert not calc.call('{"expression": "__import__(\\"os\\")"}').ok
