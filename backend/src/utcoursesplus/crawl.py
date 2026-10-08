"""Crawl the Spring 2027 schedule: every field of study x {lower, upper, graduate}, plus each
core curriculum area. Read-only GETs through the throttled, cached Fetcher."""

import re
import sqlite3
from collections.abc import Callable
from urllib.parse import parse_qs, urlencode, urlparse

from selectolax.lexbor import LexborHTMLParser

from .config import RESULTS_URL, SCHEDULE_BASE, TERM
from .db import log_page, upsert_section
from .fetch import Fetcher
from .models import CORE_AREAS
from .parse import parse_results

LEVELS = ("L", "U", "G")


def parse_departments(homepage_html: str) -> list[tuple[str, str]]:
    """[(code, name)] from the field-of-study select on the search home page."""
    tree = LexborHTMLParser(homepage_html)
    sel = tree.css_first("select#fos_fl")
    out = []
    for o in sel.css("option") if sel else []:
        code = (o.attributes.get("value") or "").strip()
        if code:
            name = re.sub(r"^.*? - ", "", o.text().strip(), count=1)
            out.append((code, name))
    return out


def field_url(dept: str, level: str) -> str:
    return (
        RESULTS_URL
        + "?"
        + urlencode(
            {"ccyys": TERM, "search_type_main": "FIELD", "fos_fl": dept, "level": level}
        )
    )


def core_url(core_code: str) -> str:
    return (
        RESULTS_URL
        + "?"
        + urlencode({"ccyys": TERM, "search_type_main": "CORE", "core_code": core_code})
    )


def plan(departments: list[tuple[str, str]]) -> list[str]:
    urls = [core_url(a.code) for a in CORE_AREAS]
    urls += [field_url(d, lv) for d, _ in departments for lv in LEVELS]
    return urls


def crawl_chain(
    fetcher: Fetcher,
    con: sqlite3.Connection,
    start_url: str,
    progress: Callable[[str], None] = print,
    source: str = "authenticated",
) -> tuple[int, int]:
    """Follow 'Next page' links from start_url. Returns (sections, pages)."""
    q = parse_qs(urlparse(start_url).query)
    level = (q.get("level") or [None])[0]
    core = (q.get("core_code") or [None])[0]
    url, n_sections, n_pages = start_url, 0, 0
    seen: set[str] = set()
    while url and url not in seen:
        seen.add(url)
        got = fetcher.get(url)
        page = parse_results(
            got.text,
            url,
            got.fetched_at,
            term=TERM,
            level=level,
            hint_core_code=core,
            source=source,
        )
        with con:
            for s in page.sections:
                upsert_section(con, s)
            log_page(
                con,
                url,
                got.fetched_at.isoformat(),
                got.from_cache,
                source,
                len(page.sections),
                page.failures,
            )
        n_sections += len(page.sections)
        n_pages += 1
        progress(
            f"  {'cache' if got.from_cache else 'fetch'} {len(page.sections):3d} sections, "
            f"{len(page.failures)} parse failures  {url[len(SCHEDULE_BASE) :][:90]}"
        )
        url = page.next_url
    return n_sections, n_pages


def crawl_all(
    fetcher: Fetcher,
    con: sqlite3.Connection,
    departments: list[tuple[str, str]],
    progress: Callable[[str], None] = print,
    only: set[str] | None = None,
) -> None:
    urls = plan(departments)
    for i, u in enumerate(urls, 1):
        q = parse_qs(urlparse(u).query)
        key = (q.get("fos_fl") or q.get("core_code") or [""])[0]
        if only and key not in only:
            continue
        progress(f"[{i}/{len(urls)}] {key} {(q.get('level') or [''])[0]}")
        crawl_chain(fetcher, con, u, progress)
