"""Share the class database. `export_seed` writes schedule facts only (courses, sections, meetings, instructors,
Core tags) to seed/spring2027.sqlite, which is meant to be committed. `bootstrap` copies it into place on a computer
that has no data yet, so a fresh clone opens with the full catalog and no crawl. Ratings, grades, syllabi, your
requirements, preferences and settings never go into the seed."""

import shutil
import sqlite3
from pathlib import Path

from . import config

SEED_TABLES = ("core_area", "course", "section", "meeting", "instructor", "section_instructor", "section_tag")


def sections_in(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM section").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def export_seed(src: Path, dest: Path | None = None) -> tuple[Path, int]:
    dest = dest or config.SEED_DB
    n = sections_in(src)
    if not n:
        raise ValueError(f"{src} has no sections to export. Load the schedule first (see the README).")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    con = sqlite3.connect(src)
    try:
        con.execute("VACUUM INTO ?", (str(dest),))
    finally:
        con.close()
    out = sqlite3.connect(dest)
    try:
        for (t,) in out.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall():
            if t not in SEED_TABLES:
                out.execute(f'DROP TABLE "{t}"')
        out.commit()
        out.execute("VACUUM")
    finally:
        out.close()
    return dest, n


def bootstrap(db: Path, seed: Path | None = None) -> int:
    """Copy the seed into `db` if `db` has no sections. Returns the number of sections copied (0 if nothing done)."""
    seed = seed or config.SEED_DB
    if sections_in(db) or not sections_in(seed):
        return 0
    db.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("", "-wal", "-shm"):
        Path(str(db) + ext).unlink(missing_ok=True)
    shutil.copyfile(seed, db)
    return sections_in(db)
