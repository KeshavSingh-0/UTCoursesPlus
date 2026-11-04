"""In-memory view of the sections table, for scoring and schedule generation."""

import sqlite3
from dataclasses import dataclass, field

from .config import TERM
from .models import CORE_AREAS

DAYS = ["M", "T", "W", "TH", "F", "S", "U"]
CORE_NAMES = {a.code: a.name for a in CORE_AREAS}


@dataclass(frozen=True)
class Meet:
    days: tuple[str, ...]
    start: int | None
    end: int | None
    building: str | None = None
    room: str | None = None

    @property
    def timed(self) -> bool:
        return self.start is not None and self.end is not None and bool(self.days)


@dataclass
class Sec:
    unique: str
    code: str  # 'C S 312'
    dept: str
    number: str
    title: str
    credits: int
    level: str | None
    mode: str | None
    status: str
    reserved: bool
    instructors: tuple[str, ...]
    meets: tuple[Meet, ...]
    core: tuple[str, ...]
    source_url: str = ""
    fetched_at: str = ""
    source: str = ""

    @property
    def timed_meets(self) -> list[Meet]:
        return [m for m in self.meets if m.timed]

    @property
    def course_key(self) -> str:
        return f"{self.code}|{self.title}"


def derived_level(number: str) -> str | None:
    """UT numbering: first digit is credit hours; second digit 0-1 lower, 2-7 upper, 8-9 graduate."""
    digits = [c for c in number if c.isdigit()]
    if len(digits) < 2:
        return None
    return "L" if digits[1] in "01" else "U" if digits[1] in "234567" else "G"


@dataclass
class Catalog:
    sections: dict[str, Sec] = field(default_factory=dict)
    by_course: dict[str, list[Sec]] = field(default_factory=dict)  # keyed by course_key
    by_code: dict[str, list[Sec]] = field(default_factory=dict)  # keyed by 'C S 312' (all titles)
    fetched_range: tuple[str, str] | None = None

    @classmethod
    def load(cls, con: sqlite3.Connection, term: str = TERM) -> "Catalog":
        cat = cls()
        meets: dict[str, list[Meet]] = {}
        for m in con.execute("SELECT * FROM meeting WHERE term=? ORDER BY unique_no, idx", (term,)):
            meets.setdefault(m["unique_no"], []).append(
                Meet(
                    tuple(d for d in m["days"].split(",") if d),
                    m["start_min"],
                    m["end_min"],
                    m["building"],
                    m["room"],
                )
            )
        inst: dict[str, list[str]] = {}
        for r in con.execute(
            "SELECT unique_no, name FROM section_instructor WHERE term=? ORDER BY name", (term,)
        ):
            inst.setdefault(r["unique_no"], []).append(r["name"])
        core: dict[str, list[str]] = {}
        for r in con.execute(
            "SELECT unique_no, code FROM section_tag WHERE term=? AND kind='core' AND code!='unmapped'",
            (term,),
        ):
            core.setdefault(r["unique_no"], []).append(r["code"])
        for r in con.execute(
            "SELECT s.*, c.dept, c.number, c.title, c.credit_hours FROM section s JOIN course c USING(course_id) WHERE s.term=?",
            (term,),
        ):
            u = r["unique_no"]
            sec = Sec(
                unique=u,
                code=f"{r['dept']} {r['number']}",
                dept=r["dept"],
                number=r["number"],
                title=r["title"],
                credits=r["credit_hours"] or 3,
                level=r["level"] or derived_level(r["number"]),
                mode=r["mode"],
                status=r["status"],
                reserved=bool(r["reserved"]),
                instructors=tuple(inst.get(u, [])),
                meets=tuple(meets.get(u, [])),
                core=tuple(sorted(set(core.get(u, [])))),
                source_url=r["source_url"],
                fetched_at=r["fetched_at"],
                source=r["source"],
            )
            cat.sections[u] = sec
            cat.by_course.setdefault(sec.course_key, []).append(sec)
            cat.by_code.setdefault(sec.code, []).append(sec)
        times = [s.fetched_at for s in cat.sections.values() if s.fetched_at]
        cat.fetched_range = (min(times), max(times)) if times else None
        return cat

    def active(self) -> list[Sec]:
        return [s for s in self.sections.values() if s.status != "cancelled"]

    def instructor_depts(self) -> dict[str, set[str]]:
        from .signals import instructor_key

        out: dict[str, set[str]] = {}
        for s in self.sections.values():
            for n in s.instructors:
                out.setdefault(instructor_key(n), set()).add(s.dept)
        return out


def core_tree(cat: Catalog, area_codes: list[str], exclude: set[str] | None = None) -> list[dict]:
    """area -> department -> course -> section counts, from the registrar's own Core tags."""
    tree = []
    for code in area_codes:
        depts: dict[str, dict[str, dict]] = {}
        for s in cat.sections.values():
            if code in s.core and s.code not in (exclude or set()):
                c = depts.setdefault(s.dept, {}).setdefault(
                    s.course_key,
                    {"code": s.code, "title": s.title, "credits": s.credits, "sections": 0, "open": 0},
                )
                if s.status != "cancelled":
                    c["sections"] += 1
                    c["open"] += s.status == "open"
        tree.append(
            {
                "code": code,
                "name": CORE_NAMES.get(code, code),
                "departments": [
                    {"dept": d, "courses": sorted(cs.values(), key=lambda c: (c["code"], c["title"]))}
                    for d, cs in sorted(depts.items())
                ],
                "n_courses": sum(len(cs) for cs in depts.values()),
            }
        )
    return tree


def fmt_time(m: int | None) -> str:
    if m is None:
        return "TBA"
    h, mi = divmod(m, 60)
    return f"{(h % 12) or 12}:{mi:02d} {'a.m.' if h < 12 else 'p.m.'}"


def when_text(s: Sec) -> str:
    if not s.meets or not any(m.timed for m in s.meets):
        return "No meeting time listed"
    return "; ".join(f"{''.join(m.days)} {fmt_time(m.start)}-{fmt_time(m.end)}" for m in s.meets if m.timed)
