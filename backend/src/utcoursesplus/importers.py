"""Offline inputs: saved schedule result pages (.html) and hand-written/pasted JSON."""

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from .config import TERM
from .db import log_page, upsert_section
from .models import Section
from .parse import parse_results


def import_html_files(con: sqlite3.Connection, paths: list[Path], progress=print) -> int:
    """Parse results pages you saved from your own browser (File > Save Page As). The page's own
    URL is not stored in a saved file, so the core code is taken from its hidden form fields."""
    total = 0
    for p in paths:
        html = p.read_text(errors="replace")
        core = re.search(
            r'name="core_code"\s*[^>]*value="(\d*)"|value="(\d*)"\s+name="core_code"',
            html,
        )
        core_code = next((g for g in (core.groups() if core else ()) if g), None)
        lvl = re.search(r'value="([LUG])"\s+name="level"', html)
        now = datetime.fromtimestamp(p.stat().st_mtime, UTC)
        url = f"file://{p.resolve()}"
        page = parse_results(
            html,
            url,
            now,
            term=TERM,
            level=lvl.group(1) if lvl else None,
            hint_core_code=core_code,
            source="file",
        )
        with con:
            for s in page.sections:
                upsert_section(con, s)
            log_page(
                con,
                url,
                now.isoformat(),
                True,
                "file",
                len(page.sections),
                page.failures,
            )
        progress(f"{p.name}: {len(page.sections)} sections, {len(page.failures)} parse failures")
        total += len(page.sections)
    return total


def import_json(con: sqlite3.Connection, path: Path) -> int:
    """JSON list of Section objects (see models.Section). Validation errors abort the import."""
    sections = TypeAdapter(list[Section]).validate_python(json.loads(path.read_text()))
    with con:
        for s in sections:
            upsert_section(con, s)
        log_page(
            con,
            f"file://{path.resolve()}",
            datetime.now(UTC).isoformat(),
            True,
            "json",
            len(sections),
            [],
        )
    return len(sections)
