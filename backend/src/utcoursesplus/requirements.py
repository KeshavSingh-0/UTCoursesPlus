"""What the student still needs. The Core areas and course lists are entered or confirmed by the
user; a pasted degree audit can be parsed into proposed groups, which are shown for correction
before anything is saved. The raw audit text is never stored."""

import json
import re
import sqlite3
from typing import Literal

from pydantic import Field

from . import llm
from .catalog import Catalog
from .models import CORE_AREAS
from .prefs import Strict

Kind = Literal["core_area", "required_course", "choose_from", "elective"]


class RequirementGroup(Strict):
    name: str
    kind: Kind
    core_code: str | None = None  # for core_area: one of the 10 registrar codes
    courses: list[str] = []  # UT format, e.g. 'C S 312'
    pick: int = Field(default=1, ge=1, le=12)  # for choose_from: how many to take
    credit_hours_needed: int | None = Field(default=None, ge=0, le=60)


class AuditParse(Strict):
    groups: list[RequirementGroup] = []
    notes: str | None = None  # anything the audit said that did not fit a group


class Requirements(Strict):
    core_areas: list[str] = []  # codes still needed, one course each
    required_courses: list[str] = []
    preferred_courses: list[str] = []  # "like to take", in the student's own ranking, best first
    groups: list[RequirementGroup] = []  # choose_from and elective groups
    elective_depts: list[str] = []  # limit electives to these departments; empty = any
    registration_time: str | None = None  # typed in by the user; never read from an account


def _ensure(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def load(con: sqlite3.Connection) -> Requirements:
    _ensure(con)
    row = con.execute("SELECT value FROM kv WHERE key='requirements'").fetchone()
    return Requirements.model_validate_json(row[0]) if row else Requirements()


def save(con: sqlite3.Connection, req: Requirements) -> None:
    _ensure(con)
    with con:
        con.execute("INSERT OR REPLACE INTO kv VALUES('requirements', ?)", (req.model_dump_json(),))


def resolve_code(text: str, cat: Catalog) -> str | None:
    """'cs 312', 'C S312', 'CS 312' -> 'C S 312' when that course exists in the catalog."""
    m = re.match(r"^\s*([A-Za-z][A-Za-z ]{0,3}?)\s*(\d\w{0,4})\s*$", text)
    if not m:
        return None
    dept_in, num = m.group(1).replace(" ", "").upper(), m.group(2).upper()
    for code in cat.by_code:
        d, _, n = code.rpartition(" ")
        if d.replace(" ", "") == dept_in and n == num:
            return code
    return None


# --- degree audit text (pasted by the user) ---------------------------------------------------------

_DROP = re.compile(
    r"(eid|student\s*(id|name)|name:|@|\b\d{3}[-.\s]\d{3,4}[-.\s]\d{4}\b|address|date of birth|dob|ssn|\b\d{7,10}\b)",
    re.IGNORECASE,
)
_KEEP = re.compile(
    r"(\b[A-Z]{1,3}\s?\d{3}[A-Z]?\b|core|require|remain|need|not satisf|elective|hours|credit|flag|"
    r"choose|select|complete|in progress|signature|communication|mathematics|science|history|government|humanities|arts|behavioral)",
    re.IGNORECASE,
)
MAX_AUDIT_CHARS = 60_000


def minimize_audit(text: str) -> str:
    """Local redaction before anything is sent: drop lines that look like identity details and keep
    only lines about requirements or courses."""
    kept = [
        ln.strip() for ln in text.splitlines() if ln.strip() and _KEEP.search(ln) and not _DROP.search(ln)
    ]
    return "\n".join(kept)[:MAX_AUDIT_CHARS]


AUDIT_SYSTEM = f"""You read the text of a UT Austin degree audit and list what the student STILL NEEDS.
- Output groups. kind=core_area for a remaining Core curriculum area (core_code from this list only: \
{", ".join(f"{a.code}={a.name}" for a in CORE_AREAS)}); kind=required_course for a specific course still \
required; kind=choose_from when the audit says to pick N from a list; kind=elective for open elective \
hours (credit_hours_needed).
- Skip anything already satisfied or in progress. Do not invent courses. Use UT course format such as \
"C S 312" and "M 408C".
- Put anything that does not fit in notes."""


def parse_audit(text: str, client=None) -> tuple[AuditParse, int]:
    """Returns (proposed groups, characters sent). The caller shows them for correction."""
    small = minimize_audit(text)
    if not small:
        raise ValueError("No requirement lines found in that text. Paste the audit's requirements section.")
    client = client or llm.get_client()
    return llm.structured(client, AuditParse, AUDIT_SYSTEM, small, max_tokens=6000), len(small)


def apply_groups(
    req: Requirements, groups: list[RequirementGroup], cat: Catalog
) -> tuple[Requirements, list[str]]:
    """Merge confirmed groups into saved requirements; returns (requirements, warnings)."""
    r = req.model_copy(deep=True)
    warn: list[str] = []
    valid_core = {a.code for a in CORE_AREAS}
    for g in groups:
        if g.kind == "core_area":
            if g.core_code in valid_core and g.core_code not in r.core_areas:
                r.core_areas.append(g.core_code)
            elif g.core_code not in valid_core:
                warn.append(f"{g.name}: unknown Core code {g.core_code!r}")
        elif g.kind == "required_course":
            for c in g.courses:
                code = resolve_code(c, cat)
                if code is None:
                    warn.append(f"{c}: not in the Spring 2027 schedule, left out")
                elif code not in r.required_courses:
                    r.required_courses.append(code)
        else:
            codes = [resolve_code(c, cat) for c in g.courses]
            for c, rc in zip(g.courses, codes, strict=True):
                if rc is None:
                    warn.append(f"{c}: not in the Spring 2027 schedule, left out")
            r.groups.append(g.model_copy(update={"courses": [c for c in codes if c]}))
    return r, warn


def dump(req: Requirements) -> str:
    return json.dumps(req.model_dump())
