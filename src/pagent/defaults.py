"""Minimal built-in tools (optional)."""

import locale
import os
from datetime import UTC, datetime

from .tool import tool


@tool()
def clock(utc: bool = True) -> str:
    """Current time as ISO 8601.

    Args:
        utc: If true, use UTC; otherwise local timezone.
    """
    if utc:
        return datetime.now(UTC).isoformat()
    return datetime.now().isoformat(timespec="seconds")


@tool()
def region() -> str:
    """OS locale / timezone hint (no GPS).

    Typical output: spoken locale from ``locale.getlocale()``,
    preferred encoding, ``TZ`` env if set (Unix), local tz abbreviation.
    """
    now = datetime.now().astimezone()
    tz_abbr = now.strftime("%Z") or "?"
    tz_env = os.environ.get("TZ", "")
    lc = locale.getlocale()
    loc = (lc[0] or "?") if lc else "?"
    enc = (lc[1] or "?") if lc else "?"
    try:
        lc_all = locale.setlocale(locale.LC_ALL)
    except locale.Error:
        lc_all = "?"
    pref_enc = locale.getpreferredencoding(False)
    bits = [
        f"locale={loc}",
        f"encoding={enc}",
        f"preferred_encoding={pref_enc}",
        f"timezone_abbr={tz_abbr}",
        f"LC_ALL={lc_all}",
    ]
    if tz_env:
        bits.append(f"TZ={tz_env}")
    return "; ".join(bits)


@tool()
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return numbered title/link/snippet lines.

    Args:
        query: Search keywords.
        max_results: Maximum number of results (1-10).
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return (
            "web_search error: missing dependency; "
            "install with pip install 'pagent[search]' (or pip install ddgs)"
        )

    q = query.strip()
    if not q:
        return "web_search error: empty query"

    n = max(1, min(int(max_results), 10))
    try:
        rows = list(DDGS().text(q, max_results=n))
    except Exception as e:
        return f"web_search error: {e}"

    if not rows:
        return "No results found."

    lines = []
    for i, row in enumerate(rows, start=1):
        title = str(row.get("title", "")).strip() or "(no title)"
        href = str(row.get("href", row.get("link", ""))).strip()
        body = str(row.get("body", row.get("snippet", ""))).strip()
        lines.append(f"{i}. {title}")
        if href:
            lines.append(f"   {href}")
        if body:
            lines.append(f"   {body}")
    return "\n".join(lines)


DEFAULT_TOOLS = [
    clock,
    region,
]
