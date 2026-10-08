"""Public syllabi -> structured fields -> a documented lightness score.

Only publicly reachable syllabi are fetched (robots.txt checked, throttled, cached). Syllabi behind
a UT login are never pulled. A field is kept only if the model returns a verbatim quote that really
appears in the syllabus text; otherwise it is set to null. Nothing is guessed."""

import hashlib
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib import robotparser
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from . import llm
from .config import SCHEDULE_HOST, USER_AGENT
from .fetch import Fetcher
from .signals import instructor_key

MAX_CHARS = 400_000

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS syllabus(
  id INTEGER PRIMARY KEY, course TEXT NOT NULL, instructor_key TEXT, instructor TEXT, term TEXT,
  source_url TEXT, source_kind TEXT NOT NULL, fetched_at TEXT NOT NULL, text_hash TEXT NOT NULL,
  extraction_json TEXT NOT NULL, dropped_json TEXT NOT NULL, lightness REAL, coverage REAL,
  components_json TEXT NOT NULL);
"""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GradeComponent(Strict):
    name: str
    weight_pct: float = Field(ge=0, le=100)
    quote: str


class QInt(Strict):
    value: int | None = Field(default=None, ge=0, le=100)
    quote: str | None = None


class QFloat(Strict):
    value: float | None = Field(default=None, ge=0, le=100)
    quote: str | None = None


class QBool(Strict):
    value: bool | None = None
    quote: str | None = None


Attendance = Literal["none", "encouraged", "graded", "mandatory"]
LatePolicy = Literal["lenient", "penalty", "no_late_work"]


class QAttendance(Strict):
    value: Attendance | None = None
    quote: str | None = None


class QLate(Strict):
    value: LatePolicy | None = None
    quote: str | None = None


class SyllabusExtraction(Strict):
    grading_breakdown: list[GradeComponent] = []
    exam_count: QInt = QInt()  # in-term exams, not counting the final
    exams_total_weight_pct: QFloat = QFloat()  # all exams including the final
    has_final_exam: QBool = QBool()
    attendance: QAttendance = QAttendance()
    participation_graded: QBool = QBool()
    late_policy: QLate = QLate()
    weekly_hours: QFloat = QFloat()  # stated weekly reading/homework hours
    major_projects_count: QInt = QInt()  # papers and projects
    group_work: QBool = QBool()


FIELDS = [
    "exam_count",
    "exams_total_weight_pct",
    "has_final_exam",
    "attendance",
    "participation_graded",
    "late_policy",
    "weekly_hours",
    "major_projects_count",
    "group_work",
]

SYSTEM = """You extract facts from one university course syllabus. Be literal.
- Fill a field only if the syllabus states it. Otherwise leave value null and quote null. Never infer.
- Every non-null value needs a quote: a short passage copied exactly (same words, same order) from \
the syllabus that supports it.
- exam_count counts exams during the term, not the final. exams_total_weight_pct sums the weights of \
all exams including the final, only if the weights are stated.
- attendance: none (explicitly not required), encouraged, graded (counts toward the grade), mandatory \
(required, with consequences beyond a graded component).
- late_policy: lenient (grace period, dropped assignments, or no penalty), penalty (points off), \
no_late_work.
- grading_breakdown lists each graded component with its percentage weight, each with a quote."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[‘’]", "'", re.sub(r"[“”]", '"', s))).strip().lower()


def verify_quotes(ex: SyllabusExtraction, text: str) -> tuple[SyllabusExtraction, list[str]]:
    """Null every field whose quote does not appear in the text. Returns (clean, dropped field names)."""
    hay = _norm(text)
    dropped: list[str] = []
    data = ex.model_dump()
    for f in FIELDS:
        v = data[f]
        if v["value"] is not None and not (v["quote"] and _norm(v["quote"]) in hay):
            data[f] = {"value": None, "quote": None}
            dropped.append(f)
    kept = []
    for c in data["grading_breakdown"]:
        if _norm(c["quote"]) in hay:
            kept.append(c)
        else:
            dropped.append(f"grading_breakdown:{c['name']}")
    data["grading_breakdown"] = kept
    return SyllabusExtraction.model_validate(data), dropped


# --------------------------------------------------------------------------- lightness


@dataclass
class Component:
    name: str
    weight: float
    value: float | None  # 0 (heavy) .. 1 (light); None when the syllabus does not say
    note: str


def _exam_count_score(n: int) -> float:
    return max(0.2, 1.0 - 0.2 * n)


def _projects_score(n: int) -> float:
    return max(0.25, 1.0 - 0.15 * n)


def lightness(ex: SyllabusExtraction) -> tuple[float | None, float, list[Component]]:
    """Score 0..1 (1 = light). Components and weights are fixed here and shown in the UI.
    Missing components are dropped and the rest renormalized; coverage is the share of weight present."""
    e = ex
    att = {"none": 1.0, "encouraged": 0.85, "graded": 0.45, "mandatory": 0.3}
    late = {"lenient": 1.0, "penalty": 0.6, "no_late_work": 0.3}
    comps = [
        Component(
            "Number of exams",
            0.20,
            None if e.exam_count.value is None else _exam_count_score(e.exam_count.value),
            "0 exams = 1.0, minus 0.2 per exam, floor 0.2",
        ),
        Component(
            "Exam weight",
            0.20,
            None if e.exams_total_weight_pct.value is None else 1 - e.exams_total_weight_pct.value / 100,
            "1 minus the share of the grade from exams",
        ),
        Component(
            "Final exam",
            0.10,
            None if e.has_final_exam.value is None else (0.4 if e.has_final_exam.value else 1.0),
            "No final = 1.0, final = 0.4",
        ),
        Component(
            "Attendance",
            0.10,
            None if e.attendance.value is None else att[e.attendance.value],
            "none 1.0, encouraged 0.85, graded 0.45, mandatory 0.3",
        ),
        Component(
            "Participation graded",
            0.05,
            None if e.participation_graded.value is None else (0.6 if e.participation_graded.value else 1.0),
            "Not graded = 1.0, graded = 0.6",
        ),
        Component(
            "Late policy",
            0.05,
            None if e.late_policy.value is None else late[e.late_policy.value],
            "lenient 1.0, penalty 0.6, no late work 0.3",
        ),
        Component(
            "Weekly hours",
            0.15,
            None if e.weekly_hours.value is None else max(0.0, min(1.0, (12 - e.weekly_hours.value) / 9)),
            "3 hours or less = 1.0, 12 or more = 0, linear between",
        ),
        Component(
            "Projects and papers",
            0.10,
            None if e.major_projects_count.value is None else _projects_score(e.major_projects_count.value),
            "0 = 1.0, minus 0.15 each, floor 0.25",
        ),
        Component(
            "Group work",
            0.05,
            None if e.group_work.value is None else (0.6 if e.group_work.value else 1.0),
            "None = 1.0, group work = 0.6",
        ),
    ]
    present = [c for c in comps if c.value is not None]
    coverage = sum(c.weight for c in present)
    if not present:
        return None, 0.0, comps
    return sum(c.weight * c.value for c in present) / coverage, coverage, comps


# --------------------------------------------------------------------------- acquiring text


def robots_allows(fetcher: Fetcher, url: str) -> bool:
    u = urlparse(url)
    try:
        txt = fetcher.get(f"{u.scheme}://{u.netloc}/robots.txt").text
    except (
        httpx.HTTPStatusError
    ):  # no robots.txt (404 and similar): no restriction. A 403 raises BlockedError.
        return True
    rp = robotparser.RobotFileParser()
    rp.parse(txt.splitlines())
    return rp.can_fetch(USER_AGENT, url)


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def html_text(html: str) -> str:
    from selectolax.lexbor import LexborHTMLParser

    t = LexborHTMLParser(html)
    for n in t.css("script,style,noscript"):
        n.decompose()
    return re.sub(r"\n\s*\n+", "\n\n", t.body.text(separator="\n") if t.body else "")


def fetch_public_syllabus(fetcher: Fetcher, url: str) -> tuple[str, datetime]:
    host = urlparse(url).hostname or ""
    if host.endswith(SCHEDULE_HOST) or "login" in host:
        raise ValueError(
            "That address needs a UT login. Only publicly reachable syllabi are fetched. Paste the text instead."
        )
    if not robots_allows(fetcher, url):
        raise ValueError(
            "That site's robots.txt disallows automated access to this page. Download it yourself and use a file or paste the text."
        )
    data, ctype, when, _ = fetcher.get_bytes(url)
    if "pdf" in ctype.lower() or data[:5] == b"%PDF-":
        return pdf_text(data), when
    return html_text(data.decode("utf-8", errors="replace")), when


# --------------------------------------------------------------------------- storing


def extract(text: str, client=None) -> tuple[SyllabusExtraction, list[str]]:
    if len(text) > MAX_CHARS:
        raise ValueError(
            f"Syllabus text is {len(text):,} characters; the limit is {MAX_CHARS:,}. Split it or trim it by hand."
        )
    client = client or llm.get_client()
    raw = llm.structured(client, SyllabusExtraction, SYSTEM, f"Syllabus:\n\n{text}", max_tokens=6000)
    return verify_quotes(raw, text)


def store(
    con: sqlite3.Connection,
    course: str,
    text: str,
    ex: SyllabusExtraction,
    dropped: list[str],
    *,
    instructor: str | None,
    term: str | None,
    source_url: str | None,
    source_kind: str,
    fetched_at: datetime | None = None,
) -> int:
    con.executescript(SCHEMA_SQL)
    score, cov, comps = lightness(ex)
    with con:
        cur = con.execute(
            "INSERT INTO syllabus(course, instructor_key, instructor, term, source_url, source_kind, fetched_at, "
            "text_hash, extraction_json, dropped_json, lightness, coverage, components_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                course.upper(),
                instructor_key(instructor) if instructor else None,
                instructor,
                term,
                source_url,
                source_kind,
                (fetched_at or datetime.now(UTC)).isoformat(),
                hashlib.sha256(text.encode()).hexdigest(),
                ex.model_dump_json(),
                json.dumps(dropped),
                score,
                cov,
                json.dumps([c.__dict__ for c in comps]),
            ),
        )
    return cur.lastrowid


def add_syllabus(
    con,
    course: str,
    *,
    text: str | None = None,
    url: str | None = None,
    instructor: str | None = None,
    term: str | None = None,
    client=None,
    fetcher: Fetcher | None = None,
    source_url: str | None = None,
    source_kind: str | None = None,
    fetched_at: datetime | None = None,
) -> dict:
    """Public address (url) is fetched here; text may instead be supplied by the caller, who may label where it
    came from with source_url / source_kind."""
    if url:
        text, when = fetch_public_syllabus(fetcher or Fetcher(), url)
        kind = "public url"
    else:
        when, kind = fetched_at or datetime.now(UTC), source_kind or "pasted or file"
        url = source_url
    if not text or len(text.strip()) < 200:
        raise ValueError(
            "Not enough syllabus text found (under 200 characters). It may be a scanned image; paste the text instead."
        )
    ex, dropped = extract(text, client)
    sid = store(
        con,
        course,
        text,
        ex,
        dropped,
        instructor=instructor,
        term=term,
        source_url=url,
        source_kind=kind,
        fetched_at=when,
    )
    score, cov, comps = lightness(ex)
    return {
        "id": sid,
        "lightness": score,
        "coverage": cov,
        "dropped_unverified": dropped,
        "components": [c.__dict__ for c in comps],
    }


# --------------------------------------------------------------------------- gold set


GOLD_FIELDS = FIELDS


def gold_sheet(con: sqlite3.Connection, path) -> int:
    """CSV to fill in by hand. Leave a cell empty to skip it; write NA when the syllabus does not say."""
    import csv

    con.executescript(SCHEMA_SQL)
    rows = con.execute("SELECT id, course, instructor, source_url FROM syllabus ORDER BY id").fetchall()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["syllabus_id", "course", "instructor", "source_url", *GOLD_FIELDS])
        for r in rows:
            w.writerow(
                [r["id"], r["course"], r["instructor"] or "", r["source_url"] or "", *[""] * len(GOLD_FIELDS)]
            )
    return len(rows)


def _parse_label(field: str, raw: str):
    raw = raw.strip()
    if raw == "":
        return "SKIP"
    if raw.upper() == "NA":
        return None
    if field in ("has_final_exam", "participation_graded", "group_work"):
        return raw.lower() in ("yes", "y", "true", "1")
    if field in ("attendance", "late_policy"):
        return raw.lower()
    return float(raw)


def gold_eval(con: sqlite3.Connection, path) -> dict:
    import csv

    tol = {"exams_total_weight_pct": 5.0, "weekly_hours": 1.0}
    stats = {f: {"labeled": 0, "correct": 0, "false_values": 0, "missed": 0} for f in GOLD_FIELDS}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            r = con.execute(
                "SELECT extraction_json FROM syllabus WHERE id=?", (int(row["syllabus_id"]),)
            ).fetchone()
            if not r:
                continue
            ex = json.loads(r[0])
            for f in GOLD_FIELDS:
                gold = _parse_label(f, row.get(f, ""))
                if gold == "SKIP":
                    continue
                got = ex[f]["value"]
                s = stats[f]
                s["labeled"] += 1
                if gold is None and got is None:
                    ok = True
                elif gold is None or got is None:
                    ok = False
                    s["false_values" if gold is None else "missed"] += 1
                elif isinstance(gold, float):
                    ok = abs(float(got) - gold) <= tol.get(f, 0.0)
                else:
                    ok = got == gold
                s["correct"] += ok
    for s in stats.values():
        s["accuracy"] = round(s["correct"] / s["labeled"], 3) if s["labeled"] else None
    return stats
