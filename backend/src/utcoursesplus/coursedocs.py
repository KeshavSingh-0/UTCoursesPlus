"""UT's "Syllabi & CVs" site (utdirect.utexas.edu/apps/student/coursedocs), read with the
student's own logged-in session, and only for courses the student selected.

Two steps, both read-only and throttled: (1) search one course at a time and list what exists;
(2) download and read only the syllabi the student picks. Downloaded files stay in the local
cache and are never shared. Files are turned into text locally; only that text goes to the model."""

import io
import re
import sqlite3
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin
from xml.etree import ElementTree

from selectolax.lexbor import LexborHTMLParser

from .config import SCHEDULE_HOST
from .fetch import Fetcher
from .signals import instructor_key

BASE = f"https://{SCHEDULE_HOST}/apps/student/coursedocs/courses/nlogon/"
SEASON = {"Spring": 1, "Summer": 2, "Fall": 3}
RECENT_FROM_YEAR = 2022  # prefer syllabi from the last few years; older ones only as a last resort

DOC_SCHEMA = """
CREATE TABLE IF NOT EXISTS syllabus_doc(
  id INTEGER PRIMARY KEY, course TEXT NOT NULL, term_text TEXT NOT NULL, year INTEGER NOT NULL, season INTEGER NOT NULL,
  unique_no TEXT, title TEXT, instructors TEXT NOT NULL, url TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
  recommended INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'found', error TEXT,
  syllabus_id INTEGER, found_at TEXT NOT NULL);
"""


@dataclass
class DocRow:
    term_text: str
    year: int
    season: int
    course: str
    unique: str
    title: str
    instructors: list[str]
    url: str | None
    kind: str | None  # 'download' (needs login) | 'external' (Simple Syllabus link) | None (no syllabus)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def norm_course(s: str) -> str:
    return _clean(s).upper()


def parse_results(html: str, base: str = BASE) -> list[DocRow]:
    """Rows of the results table: Semester, Course, Unique, Section Title, Instructor(s), CV(s), Syllabus."""
    tree = LexborHTMLParser(html)
    out: list[DocRow] = []
    for tr in tree.css("#results_table tbody tr"):
        tds = tr.css("td")
        if len(tds) < 7:
            continue
        term = _clean(tds[0].text())
        m = re.match(r"^(\d{4})\s+(Spring|Summer|Fall)$", term)
        if not m:
            continue
        names = [
            _clean(x) for x in re.split(r"<br\s*/?>", tds[4].html or "") if _clean(re.sub(r"<[^>]+>", " ", x))
        ]
        names = [_clean(re.sub(r"<[^>]+>", " ", n)) for n in names]
        a = tds[6].css_first("a")
        href = (a.attributes.get("href") or "") if a else ""
        kind = None
        url = None
        if href:
            url = urljoin(base, href)
            kind = "download" if "/coursedocs/" in href and "/download/" in href else "external"
        out.append(
            DocRow(
                term_text=term,
                year=int(m.group(1)),
                season=SEASON[m.group(2)],
                course=norm_course(tds[1].text()),
                unique=_clean(tds[2].text()),
                title=_clean(tds[3].text()),
                instructors=names,
                url=url,
                kind=kind,
            )
        )
    return out


def parse_department_values(html: str) -> dict[str, str]:
    """Normalized department code -> the exact option value the form expects (some are space padded)."""
    tree = LexborHTMLParser(html)
    out: dict[str, str] = {}
    for o in tree.css("select#id_department option"):
        v = o.attributes.get("value") or ""
        if v.strip():
            out[v.strip().upper()] = v
    return out


def search_url(dept_value: str, number: str) -> str:
    q = {
        "year": "",
        "semester": "",
        "department": dept_value,
        "course_number": number,
        "course_title": "",
        "unique": "",
        "csn": "",
        "instructor_first": "",
        "instructor_last": "",
        "course_type": "In Residence",
        "search": "",
    }
    return BASE + "?" + urlencode(q)


def split_course(code: str) -> tuple[str, str]:
    dept, _, number = code.strip().upper().rpartition(" ")
    return dept, number


def recency(r: DocRow) -> tuple[int, int]:
    return (r.year, r.season)


def pick_docs(
    rows: list[DocRow], course: str, spring_instructors: list[str], per_course: int = 3
) -> list[DocRow]:
    """Recommend which syllabi to read: for each instructor teaching it this spring, their most recent
    syllabus; otherwise (and as a course-level fallback) the most recent ones. Exact course only
    (the honors version is a different course)."""
    mine = [r for r in rows if r.course == norm_course(course) and r.url and r.kind == "download"]
    mine.sort(key=recency, reverse=True)
    recent = [r for r in mine if r.year >= RECENT_FROM_YEAR] or mine
    picked: list[DocRow] = []

    def add(r: DocRow) -> None:
        if r not in picked and len(picked) < per_course:
            picked.append(r)

    for name in spring_instructors:
        k = instructor_key(name)
        match = next((r for r in recent if any(instructor_key(n) == k for n in r.instructors)), None)
        if match:
            add(match)
    for r in recent:
        add(r)
    return picked


# ----------------------------------------------------------------------------- text from files


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml")
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ElementTree.fromstring(xml)
    paras = []
    for p in root.iter(f"{ns}p"):
        paras.append("".join(t.text or "" for t in p.iter(f"{ns}t")))
    return "\n".join(paras)


def extract_text(data: bytes, content_type: str = "") -> str:
    """PDF, Word (.docx) or HTML to text. Raises ValueError for anything else (for example old .doc)."""
    from .syllabus import html_text, pdf_text

    ct = content_type.lower()
    if data[:5] == b"%PDF-" or "pdf" in ct:
        text = pdf_text(data)
    elif data[:2] == b"PK":
        try:
            text = docx_text(data)
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
            raise ValueError("The file is a zip archive but not a readable Word document.") from e
    elif "html" in ct or data.lstrip()[:1] == b"<":
        text = html_text(data.decode("utf-8", errors="replace"))
    else:
        raise ValueError(
            "This file type cannot be read here (for example an old .doc or an image). Open it yourself and paste the text."
        )
    if len(text.strip()) < 200:
        raise ValueError(
            "Almost no text was found; it may be a scanned image. Open it yourself and paste the text."
        )
    return text


# ----------------------------------------------------------------------------- jobs


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(DOC_SCHEMA)


def find_docs(
    con: sqlite3.Connection,
    fetcher: Fetcher,
    courses: dict[str, list[str]],
    progress: Callable[[str], None] = print,
    per_course: int = 3,
) -> dict[str, dict]:
    """courses: {'C S 439': [spring instructor names]}. One search per course."""
    ensure(con)
    out: dict[str, dict] = {}
    home = fetcher.get(BASE).text
    dept_values = parse_department_values(home)
    for i, (code, instr) in enumerate(courses.items(), 1):
        dept, number = split_course(code)
        progress(f"[{i}/{len(courses)}] Searching {code}")
        value = (
            dept_values.get(dept.upper()) or dept_values.get(dept.replace(" ", "").upper()) or dept.ljust(3)
        )
        rows = parse_results(fetcher.get(search_url(value, number)).text)
        exact = [r for r in rows if r.course == norm_course(code)]
        picks = pick_docs(rows, code, instr, per_course)
        now = datetime.now(UTC).isoformat()
        with con:
            for r in exact:
                if not r.url:
                    continue
                con.execute(
                    "INSERT OR IGNORE INTO syllabus_doc(course, term_text, year, season, unique_no, title, instructors, url, kind, "
                    "found_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        code.upper(),
                        r.term_text,
                        r.year,
                        r.season,
                        r.unique,
                        r.title,
                        "; ".join(r.instructors),
                        r.url,
                        r.kind or "download",
                        now,
                    ),
                )
            con.execute("UPDATE syllabus_doc SET recommended=0 WHERE course=?", (code.upper(),))
            for r in picks:
                con.execute("UPDATE syllabus_doc SET recommended=1 WHERE url=?", (r.url,))
        out[code] = {
            "rows_on_site": len(rows),
            "exact": len(exact),
            "with_syllabus": sum(1 for r in exact if r.url),
            "recommended": len(picks),
        }
        progress(f"    {out[code]['with_syllabus']} syllabi found for {code}, {len(picks)} recommended")
    return out


def read_docs(
    con: sqlite3.Connection,
    fetcher: Fetcher,
    doc_ids: list[int],
    client=None,
    progress: Callable[[str], None] = print,
) -> list[dict]:
    """Download the chosen syllabi, extract text locally, and read them with the model."""
    from . import syllabus as Y

    ensure(con)
    results = []
    for i, did in enumerate(doc_ids, 1):
        row = con.execute("SELECT * FROM syllabus_doc WHERE id=?", (did,)).fetchone()
        if not row:
            continue
        label = f"{row['course']} {row['term_text']} ({row['instructors'] or 'instructor not listed'})"
        progress(f"[{i}/{len(doc_ids)}] Reading {label}")
        try:
            if row["kind"] != "download":
                raise ValueError(
                    "This syllabus is on an outside site (Simple Syllabus) and cannot be downloaded here."
                )
            data, ctype, when, _ = fetcher.get_bytes(row["url"])
            text = extract_text(data, ctype)
            first = (row["instructors"] or "").split(";")[0].strip() or None
            r = Y.add_syllabus(
                con,
                row["course"],
                text=text,
                instructor=first,
                term=row["term_text"],
                client=client,
                source_url=row["url"],
                source_kind="UT syllabi site (login)",
                fetched_at=when,
            )
            with con:
                con.execute(
                    "UPDATE syllabus_doc SET status='read', syllabus_id=?, error=NULL WHERE id=?",
                    (r["id"], did),
                )
            results.append(
                {
                    "doc_id": did,
                    "course": row["course"],
                    "ok": True,
                    "lightness": r["lightness"],
                    "coverage": r["coverage"],
                    "dropped": r["dropped_unverified"],
                }
            )
            progress(
                f"    lightness {r['lightness'] if r['lightness'] is None else round(r['lightness'], 2)}, "
                f"{round(r['coverage'] * 100)}% of fields found"
            )
        except ValueError as e:
            with con:
                con.execute("UPDATE syllabus_doc SET status='failed', error=? WHERE id=?", (str(e), did))
            results.append({"doc_id": did, "course": row["course"], "ok": False, "error": str(e)})
            progress(f"    skipped: {e}")
    return results
