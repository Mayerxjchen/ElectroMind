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


DEFAULT_TOOLS = [
    clock,
    region,
]
