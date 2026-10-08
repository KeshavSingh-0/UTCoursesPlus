"""Work from already-fetched pages: rebuild the database after a parser change (no requests),
and dump raw rows for anomalies so the parser can be corrected against real markup."""

import json
import re
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from selectolax.lexbor import LexborHTMLParser

from .config import CACHE_DIR, DATA_DIR, TERM
from .db import log_page, upsert_section
from .parse import _clean, parse_results


def cached_pages(cache_dir: Path = CACHE_DIR) -> Iterator[tuple[str, datetime, str]]:
    for meta in sorted(cache_dir.glob("*.json")):
        m = json.loads(meta.read_text())
        body = meta.with_suffix(".html")
        if body.exists():
            yield m["url"], datetime.fromisoformat(m["fetched_at"]), body.read_text()


def reparse_cache(con: sqlite3.Connection, cache_dir: Path = CACHE_DIR, progress=print) -> int:
    """Replace every section that came from the authenticated crawl with a fresh parse of the cache."""
    with con:
        for t in ("section_tag", "meeting", "section_instructor"):
            con.execute(
                f"DELETE FROM {t} WHERE (unique_no, term) IN "
                "(SELECT unique_no, term FROM section WHERE source='authenticated')"
            )
        con.execute("DELETE FROM section WHERE source='authenticated'")
        con.execute(
            "DELETE FROM parse_failure WHERE url IN (SELECT url FROM crawl_log WHERE source='authenticated')"
        )
        con.execute("DELETE FROM crawl_log WHERE source='authenticated'")
    total = 0
    for url, fetched_at, html in cached_pages(cache_dir):
        q = parse_qs(urlparse(url).query)
        page = parse_results(
            html,
            url,
            fetched_at,
            term=TERM,
            level=(q.get("level") or [None])[0],
            hint_core_code=(q.get("core_code") or [None])[0],
        )
        with con:
            for s in page.sections:
                upsert_section(con, s)
            log_page(
                con,
                url,
                fetched_at.isoformat(),
                True,
                "authenticated",
                len(page.sections),
                page.failures,
            )
        total += len(page.sections)
    progress(f"Reparsed cached pages: {total} sections.")
    return total


def diagnose(cache_dir: Path = CACHE_DIR, out: Path | None = None, per_category: int = 3) -> Path:
    """Write raw HTML of example rows (no cookies, only schedule markup) to data/diagnose.txt."""
    out = out or DATA_DIR / "diagnose.txt"
    found: dict[str, list[str]] = {
        "no_times": [],
        "no_instructor": [],
        "unusual_tags": [],
        "no_unique_rows": [],
    }
    seen_labels: set[str] = set()
    known = {
        "first year signature course",
        "communication",
        "humanities",
        "mathematics",
    }
    for url, _, html in cached_pages(cache_dir):
        tree = LexborHTMLParser(html)
        rows = tree.css("table.results tbody tr")
        header = ""
        for i, tr in enumerate(rows):
            h = tr.css_first("td.course_header h2")
            if h is not None:
                header = _clean(h.text())
                continue
            cells = {(td.attributes.get("data-th") or "").lower(): td for td in tr.css("td[data-th]")}
            uq = cells.get("unique")
            snippet = f"<!-- {header} | {url[-80:]} -->\n{tr.html}"
            if uq is None or not _clean(uq.text()):
                if len(found["no_unique_rows"]) < per_category:
                    prev = rows[i - 1].html if i else ""
                    found["no_unique_rows"].append(f"<!-- previous row -->\n{prev}\n{snippet}")
                continue
            hours = [_clean(s.text()) for s in cells["hour"].css("span")] if "hour" in cells else []
            instr = (
                [_clean(s.text()) for s in cells["instructor"].css("span")] if "instructor" in cells else []
            )
            if not any(hours) and len(found["no_times"]) < per_category:
                found["no_times"].append(snippet)
            if not any(instr) and len(found["no_instructor"]) < per_category:
                found["no_instructor"].append(snippet)
            for li in tr.css("td ul li"):
                label = _clean(li.text())
                key = re.sub(r"[^a-z]+", " ", label.lower()).strip()
                if key and key not in known and label not in seen_labels:
                    seen_labels.add(label)
                    found["unusual_tags"].append(snippet)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for k, rows in found.items():
            f.write(f"\n\n===== {k} ({len(rows)} examples) =====\n")
            f.write("\n\n".join(rows))
    return out
