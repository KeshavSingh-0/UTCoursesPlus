"""Parse registrar results pages (course_schedule/<term>/results/) into validated Sections."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from .models import CORE_AREAS, Course, Instructor, Level, Meeting, Section, Tag
from .timeutil import parse_days, parse_time_range

_HEADER_RE = re.compile(r"^(?P<dept>.+?)\s+(?P<num>\d[0-9A-Z]*)\s+(?P<title>.+)$")
_CORE_BY_NAME = {a.name.lower(): a.code for a in CORE_AREAS}


@dataclass
class ParsedPage:
    sections: list[Section] = field(default_factory=list)
    next_url: str | None = None
    failures: list[str] = field(default_factory=list)
    has_results_table: bool = False


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _spans(td: Node | None) -> list[str]:
    """Each meeting/instructor line is its own <span>; blank spans are kept as ''."""
    if td is None:
        return []
    return [_clean(s.text()) for s in td.css("span")]


def _parse_status(raw: str) -> tuple[str, bool]:
    low = raw.lower()
    reserved = "reserved" in low
    for key in ("cancelled", "waitlisted", "closed", "open"):
        if key in low:
            return key, reserved
    return "unknown", reserved


def _parse_tags(td: Node | None, hint_core_code: str | None) -> list[Tag]:
    tags: list[Tag] = []
    if td is not None:
        for li in td.css("ul li"):
            label = _clean(li.text())
            title = li.attributes.get("title") or ""
            css = (li.attributes.get("class") or "").strip()
            code = _CORE_BY_NAME.get(label.lower())
            if code or "core curriculum requirement" in title:
                tags.append(Tag(kind="core", code=code or css or label, label=label))
            elif label:
                tags.append(Tag(kind="flag", code=css or label, label=label))
    if hint_core_code and not any(
        t.kind == "core" and t.code == hint_core_code for t in tags
    ):
        area = next((a for a in CORE_AREAS if a.code == hint_core_code), None)
        if area:
            tags.append(Tag(kind="core", code=area.code, label=area.name))
    return tags


def _parse_meetings(
    days: list[str], hours: list[str], rooms: list[str]
) -> list[Meeting]:
    n = max(len(days), len(hours), len(rooms), 0)
    out = []
    for i in range(n):
        d = days[i] if i < len(days) else ""
        h = hours[i] if i < len(hours) else ""
        r = rooms[i] if i < len(rooms) else ""
        if not d and not h:
            continue
        start = end = None
        if h:
            start, end = parse_time_range(h)
        building = room = None
        if r:
            parts = r.split(" ", 1)
            building, room = parts[0], (parts[1] if len(parts) > 1 else None)
        out.append(
            Meeting(
                days=parse_days(d) if d else [],
                start_min=start,
                end_min=end,
                building=building,
                room=room,
            )
        )
    return out


def parse_results(
    html: str,
    url: str,
    fetched_at: datetime,
    *,
    term: str,
    level: Level | None = None,
    hint_core_code: str | None = None,
    source: str = "authenticated",
) -> ParsedPage:
    tree = HTMLParser(html)
    page = ParsedPage()
    nxt = tree.css_first("a#next_nav_link")
    if nxt and nxt.attributes.get("href"):
        page.next_url = urljoin(url, nxt.attributes["href"].replace("&amp;", "&"))
    table = tree.css_first("table.results")
    page.has_results_table = table is not None
    if table is None:
        return page

    header: Course | None = None
    header_text = ""
    for tr in table.css("tbody tr"):
        h = tr.css_first("td.course_header h2")
        if h is not None:
            header_text = _clean(h.text())
            m = _HEADER_RE.match(header_text)
            if not m:
                header = None
                page.failures.append(f"unparseable course header: {header_text!r}")
                continue
            num = m["num"]
            header = Course(
                dept=m["dept"],
                number=num,
                title=m["title"],
                credit_hours=int(num[0]) if num[0].isdigit() else None,
            )
            continue
        cells = {
            (td.attributes.get("data-th") or "").lower(): td
            for td in tr.css("td[data-th]")
        }
        uq = cells.get("unique")
        if uq is None:
            continue
        unique = _clean(uq.text())
        try:
            if header is None:
                raise ValueError("section row without a parseable course header")
            status, reserved = _parse_status(
                _clean(cells["status"].text()) if "status" in cells else ""
            )
            instructors = [
                Instructor(name=s) for s in _spans(cells.get("instructor")) if s
            ]
            tag_td = cells.get("core") or cells.get("flags")
            mode_td = cells.get("instruction mode")
            page.sections.append(
                Section(
                    unique=unique,
                    term=term,
                    course=header,
                    meetings=_parse_meetings(
                        _spans(cells.get("days")),
                        _spans(cells.get("hour")),
                        _spans(cells.get("room")),
                    ),
                    instructors=instructors,
                    mode=_clean(mode_td.text()) if mode_td is not None else None,
                    status=status,
                    status_raw=_clean(cells["status"].text())
                    if "status" in cells
                    else "",
                    reserved=reserved,
                    level=level,
                    tags=_parse_tags(tag_td, hint_core_code),
                    source_url=url,
                    fetched_at=fetched_at,
                    source=source,
                )
            )
        except (
            ValueError,
            KeyError,
        ) as e:  # pydantic's ValidationError is a ValueError; recorded, not fatal
            page.failures.append(f"unique {unique!r} under {header_text!r}: {e}")
    return page
