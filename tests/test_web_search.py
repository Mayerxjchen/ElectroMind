import builtins
from unittest.mock import patch

from pagent import web_search


def test_web_search_formats_results():
    fake = [
        {
            "title": "Sodium",
            "href": "https://example.com/na",
            "body": "Sodium is a chemical element.",
        }
    ]
    with patch("ddgs.DDGS") as ddgs_cls:
        ddgs_cls.return_value.text.return_value = fake
        out = web_search.call({"query": "sodium symbol", "max_results": 3})

    assert "1. Sodium" in out
    assert "https://example.com/na" in out
    assert "Sodium is a chemical element." in out


def test_web_search_empty_query():
    out = web_search.call({"query": "  "})
    assert "empty query" in out


def test_web_search_no_results():
    with patch("ddgs.DDGS") as ddgs_cls:
        ddgs_cls.return_value.text.return_value = []
        out = web_search.call({"query": "xyznonexistentquery123"})
    assert out == "No results found."


def test_web_search_api_error():
    with patch("ddgs.DDGS") as ddgs_cls:
        ddgs_cls.return_value.text.side_effect = RuntimeError("network down")
        out = web_search.call({"query": "test"})
    assert "web_search error: network down" in out


def test_web_search_missing_ddgs():
    real_import = builtins.__import__

    def block_ddgs(name, *args, **kwargs):
        if name == "ddgs":
            raise ImportError("No module named 'ddgs'")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", block_ddgs):
        out = web_search.call({"query": "test"})
    assert "pagent[search]" in out
