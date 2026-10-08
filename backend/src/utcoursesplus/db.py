"""SQLite storage. One file under data/, no server."""

import sqlite3
from pathlib import Path

from .config import DB_PATH
from .models import CORE_AREAS, Section

SCHEMA = """
CREATE TABLE IF NOT EXISTS core_area(code TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS course(
  course_id TEXT PRIMARY KEY, dept TEXT NOT NULL, number TEXT NOT NULL, title TEXT NOT NULL,
  credit_hours INTEGER);
CREATE TABLE IF NOT EXISTS section(
  unique_no TEXT NOT NULL, term TEXT NOT NULL, course_id TEXT NOT NULL REFERENCES course(course_id),
  mode TEXT, status TEXT NOT NULL, status_raw TEXT, reserved INTEGER NOT NULL DEFAULT 0, level TEXT,
  source_url TEXT NOT NULL, fetched_at TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY(unique_no, term));
CREATE TABLE IF NOT EXISTS meeting(
  unique_no TEXT NOT NULL, term TEXT NOT NULL, idx INTEGER NOT NULL, days TEXT NOT NULL,
  start_min INTEGER, end_min INTEGER, building TEXT, room TEXT,
  PRIMARY KEY(unique_no, term, idx));
CREATE TABLE IF NOT EXISTS instructor(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS section_instructor(
  unique_no TEXT NOT NULL, term TEXT NOT NULL, name TEXT NOT NULL REFERENCES instructor(name),
  PRIMARY KEY(unique_no, term, name));
CREATE TABLE IF NOT EXISTS section_tag(
  unique_no TEXT NOT NULL, term TEXT NOT NULL, kind TEXT NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(unique_no, term, kind, code, label));
CREATE TABLE IF NOT EXISTS crawl_log(
  url TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, from_cache INTEGER NOT NULL, source TEXT NOT NULL,
  n_sections INTEGER NOT NULL, n_failures INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS parse_failure(url TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requirement_group(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, core_code TEXT,
  courses_json TEXT NOT NULL, credit_hours_needed INTEGER, remaining INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_section_course ON section(course_id);
CREATE INDEX IF NOT EXISTS ix_tag_code ON section_tag(kind, code);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(section_tag)")}
    if (
        "title" not in cols
    ):  # database created by an earlier version: derived data, rebuild it
        con.execute("DROP TABLE section_tag")
        con.executescript(SCHEMA)
    con.executemany(
        "INSERT OR IGNORE INTO core_area VALUES(?,?)",
        [(a.code, a.name) for a in CORE_AREAS],
    )
    con.commit()
    return con


def upsert_section(con: sqlite3.Connection, s: Section) -> None:
    """Replace a section's scalar fields and meetings; tags and instructors are unioned
    so a section seen by both a field search and a core search keeps every tag."""
    c = s.course
    con.execute(
        "INSERT INTO course VALUES(?,?,?,?,?) ON CONFLICT(course_id) DO UPDATE SET "
        "credit_hours=excluded.credit_hours",
        (c.course_id, c.dept, c.number, c.title, c.credit_hours),
    )
    prev = con.execute(
        "SELECT level, course_id FROM section WHERE unique_no=? AND term=?",
        (s.unique, s.term),
    ).fetchone()
    if prev and prev["course_id"] != c.course_id:
        con.execute(
            "INSERT INTO parse_failure VALUES(?,?)",
            (
                s.source_url,
                f"unique {s.unique} changed course from {prev['course_id']} to {c.course_id}",
            ),
        )
    level = s.level or (prev["level"] if prev else None)
    con.execute(
        "INSERT OR REPLACE INTO section VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            s.unique,
            s.term,
            c.course_id,
            s.mode,
            s.status,
            s.status_raw,
            int(s.reserved),
            level,
            s.source_url,
            s.fetched_at.isoformat(),
            s.source,
        ),
    )
    con.execute("DELETE FROM meeting WHERE unique_no=? AND term=?", (s.unique, s.term))
    for i, m in enumerate(s.meetings):
        con.execute(
            "INSERT INTO meeting VALUES(?,?,?,?,?,?,?,?)",
            (
                s.unique,
                s.term,
                i,
                ",".join(m.days),
                m.start_min,
                m.end_min,
                m.building,
                m.room,
            ),
        )
    for ins in s.instructors:
        con.execute("INSERT OR IGNORE INTO instructor VALUES(?)", (ins.name,))
        con.execute(
            "INSERT OR IGNORE INTO section_instructor VALUES(?,?,?)",
            (s.unique, s.term, ins.name),
        )
    for t in s.tags:
        con.execute(
            "INSERT OR IGNORE INTO section_tag VALUES(?,?,?,?,?,?)",
            (s.unique, s.term, t.kind, t.code, t.label, t.title),
        )


def log_page(
    con,
    url: str,
    fetched_at: str,
    from_cache: bool,
    source: str,
    n_sections: int,
    failures: list[str],
) -> None:
    con.execute(
        "INSERT OR REPLACE INTO crawl_log VALUES(?,?,?,?,?,?)",
        (url, fetched_at, int(from_cache), source, n_sections, len(failures)),
    )
    con.execute("DELETE FROM parse_failure WHERE url=?", (url,))
    con.executemany(
        "INSERT INTO parse_failure VALUES(?,?)", [(url, f) for f in failures]
    )
