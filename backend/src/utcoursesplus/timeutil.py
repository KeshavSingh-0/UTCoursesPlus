"""Parsing of registrar day/time strings into minutes-from-midnight."""

import re

DAY_ORDER = ["M", "T", "W", "TH", "F", "S", "U"]
_DAY_RE = re.compile(r"TH|M|T|W|F|S|U")
_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([ap])\.?m\.?\s*$", re.IGNORECASE)


def parse_days(text: str) -> list[str]:
    """'MWF' -> ['M','W','F']; 'TTH' -> ['T','TH']. Raises ValueError on leftovers."""
    s = text.strip().upper().replace(" ", "")
    days = _DAY_RE.findall(s)
    if not s or "".join(days) != s:
        raise ValueError(f"unrecognized days: {text!r}")
    return sorted(set(days), key=DAY_ORDER.index)


def parse_clock(text: str) -> int:
    """'11:00 a.m.' -> 660, '12:30 p.m.' -> 750."""
    m = _TIME_RE.match(text)
    if not m:
        raise ValueError(f"unrecognized time: {text!r}")
    hour, minute, ap = int(m[1]), int(m[2]), m[3].lower()
    if not (1 <= hour <= 12 and minute < 60):
        raise ValueError(f"time out of range: {text!r}")
    hour = hour % 12 + (12 if ap == "p" else 0)
    return hour * 60 + minute


def parse_time_range(text: str) -> tuple[int, int]:
    """'11:00 a.m.-12:30 p.m.' -> (660, 750)."""
    parts = re.split(r"\s*-\s*", text.strip())
    if len(parts) != 2:
        raise ValueError(f"unrecognized time range: {text!r}")
    start, end = parse_clock(parts[0]), parse_clock(parts[1])
    if end <= start:
        raise ValueError(f"end before start: {text!r}")
    return start, end
