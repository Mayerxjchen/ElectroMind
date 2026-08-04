from unittest.mock import patch

from electromind.tools import fetch_url, web_search


def test_web_search_formats_results():
    fake = [
        {
            "title": "Sodium",
            "href": "https://example.com/na",
            "body": "Sodium is a chemical element.",
        }
    ]
    with patch("electromind.tools.web.ddgs_client") as client_fn:
        client_fn.return_value.text.return_value = fake
        out = web_search.call({"query": "sodium symbol", "max_results": 3})

    assert out.ok is True
    assert "1. Sodium" in out.content
    assert "https://example.com/na" in out.content
    assert "Sodium is a chemical element." in out.content


def test_web_search_empty_query():
    out = web_search.call({"query": "  "})
    assert out.ok is False
    assert "empty query" in out.content


def test_web_search_no_results():
    with patch("electromind.tools.web.ddgs_client") as client_fn:
        client_fn.return_value.text.return_value = []
        out = web_search.call({"query": "xyznonexistentquery123"})
    assert out.ok is True
    assert out.content == "No results found."


def test_web_search_api_error():
    with patch("electromind.tools.web.ddgs_client") as client_fn:
        client_fn.return_value.text.side_effect = RuntimeError("network down")
        out = web_search.call({"query": "test"})
    assert out.ok is False
    assert "web_search error: network down" in out.content


def test_web_search_missing_ddgs():
    with patch("electromind.tools.web.ddgs_client", return_value=None):
        out = web_search.call({"query": "test"})
    assert out.ok is False
    assert "electromind[search]" in out.content


def test_fetch_url_formats_content():
    fake = {"url": "https://example.com", "content": "# Hello\n\nWorld"}
    with patch("electromind.tools.web.ddgs_client") as client_fn:
        client_fn.return_value.extract.return_value = fake
        out = fetch_url.call({"url": "https://example.com"})

    assert out.ok is True
    assert "URL: https://example.com" in out.content
    assert "# Hello" in out.content
    client_fn.return_value.extract.assert_called_once_with(
        "https://example.com", fmt="text_markdown"
    )


def test_fetch_url_rejects_non_http():
    out = fetch_url.call({"url": "ftp://example.com/x"})
    assert out.ok is False
    assert "http://" in out.content


def test_fetch_url_truncates():
    fake = {"url": "https://example.com", "content": "x" * 5000}
    with patch("electromind.tools.web.ddgs_client") as client_fn:
        client_fn.return_value.extract.return_value = fake
        out = fetch_url.call({"url": "https://example.com", "max_chars": 1000})

    assert out.ok is True
    assert "truncated, 5000 chars total" in out.content


def test_fetch_url_missing_ddgs():
    with patch("electromind.tools.web.ddgs_client", return_value=None):
        out = fetch_url.call({"url": "https://example.com"})
    assert out.ok is False
    assert "electromind[search]" in out.content
