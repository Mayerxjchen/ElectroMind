"""Harness web tools — run in the host process, not in sandbox."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ..core.tool import ToolOutput, tool

DDGS_MISSING = (
    "missing dependency ddgs; install with pip install 'pagent[search]' "
    "(or pip install ddgs)"
)

DEFAULT_FETCH_MAX_CHARS = 20_000
MAX_FETCH_MAX_CHARS = 100_000


def ddgs_client():
    try:
        from ddgs import DDGS
    except ImportError:
        return None
    return DDGS()


def clamp_max_results(max_results: int, *, default: int = 5, limit: int = 10) -> int:
    try:
        value = int(max_results)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, limit))


def clamp_max_chars(max_chars: int, *, default: int = DEFAULT_FETCH_MAX_CHARS) -> int:
    try:
        value = int(max_chars)
    except (TypeError, ValueError):
        value = default
    return max(500, min(value, MAX_FETCH_MAX_CHARS))


def first_field(row: dict, keys: Iterable[str]) -> str:
    for key in keys:
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def format_result_rows(
    rows: list[dict],
    *,
    url_keys: tuple[str, ...] = ("href", "link", "url"),
    body_keys: tuple[str, ...] = ("body", "snippet"),
) -> str:
    lines: list[str] = []
    for index, row in enumerate(rows, start=1):
        title = str(row.get("title", "")).strip() or "(no title)"
        lines.append(f"{index}. {title}")
        href = first_field(row, url_keys)
        if href:
            lines.append(f"   {href}")
        body = first_field(row, body_keys)
        if body:
            lines.append(f"   {body}")
    return "\n".join(lines)


def run_ddgs_search(
    *,
    query: str,
    max_results: int,
    search: Callable,
    error_prefix: str,
) -> ToolOutput:
    client = ddgs_client()
    if client is None:
        return ToolOutput.fail(f"{error_prefix}: {DDGS_MISSING}")

    q = query.strip()
    if not q:
        return ToolOutput.fail(f"{error_prefix}: empty query")

    n = clamp_max_results(max_results)
    try:
        rows = list(search(client, q, n))
    except Exception as exc:
        return ToolOutput.fail(f"{error_prefix}: {exc}")

    if not rows:
        return ToolOutput.succeed("No results found.")
    return ToolOutput.succeed(format_result_rows(rows))


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n...(truncated, {len(text)} chars total)"


@tool(
    description=(
        "用关键字搜索网页，返回编号列表（标题、链接、摘要）。"
        "适合还不知道该看哪个网址、需要先找资料时使用。"
        "若已有具体链接，请改用 fetch_url 读取页面正文。"
    )
)
def web_search(query: str, max_results: int = 5) -> ToolOutput:
    """Args:
    query: 搜索关键词，例如库名、错误信息、概念名称。
    max_results: 最多返回几条结果（1-10，默认 5）。
    """

    def search(client, q: str, n: int):
        return client.text(q, max_results=n)

    return run_ddgs_search(
        query=query,
        max_results=max_results,
        search=search,
        error_prefix="web_search error",
    )


@tool(
    description=(
        "根据 http(s) URL 抓取网页并提取正文，返回 markdown 文本。"
        "适合阅读文档、博客、README、API 参考等静态页面。"
        "常见用法：先用 web_search 找到链接，再用本工具读内容。"
        "不执行 JavaScript；SPA、登录墙或强反爬页面可能内容很少或抓取失败。"
    )
)
def fetch_url(url: str, max_chars: int = DEFAULT_FETCH_MAX_CHARS) -> ToolOutput:
    """Args:
    url: 完整 URL，必须以 http:// 或 https:// 开头。
    max_chars: 最多返回多少字符（500-100000，默认 20000）；超出部分会截断。
    """
    client = ddgs_client()
    if client is None:
        return ToolOutput.fail(f"fetch_url error: {DDGS_MISSING}")

    target = url.strip()
    if not target:
        return ToolOutput.fail("fetch_url error: empty url")
    if not target.startswith(("http://", "https://")):
        return ToolOutput.fail(
            "fetch_url error: url must start with http:// or https://"
        )

    limit = clamp_max_chars(max_chars)
    try:
        payload = client.extract(target, fmt="text_markdown")
    except Exception as exc:
        return ToolOutput.fail(f"fetch_url error: {exc}")

    content = payload.get("content", "")
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = str(content)

    if not text.strip():
        return ToolOutput.fail("fetch_url error: empty content")

    resolved = str(payload.get("url", target)).strip() or target
    body = truncate_text(text.strip(), limit)
    return ToolOutput.succeed(f"URL: {resolved}\n\n{body}")
