"""Read a saved UT Interactive Degree Audit (IDA) results page, locally and without a language model.

The page lists every course you have credit for (with equivalent course numbers) and a checklist of requirements with
hours required, counted and lacking. This turns it into: courses to exclude from planning (already taken or in
progress), Core areas still needed with how many hours, and other remaining requirements. The student's name, EID and
the raw page are never kept; only the requirements that come out of it are saved, after the student reviews them."""

import re
from dataclasses import asdict, dataclass, field

from selectolax.lexbor import LexborHTMLParser

from .models import CORE_AREAS

CORE_NAME = {a.code: a.name for a in CORE_AREAS}
# the audit sometimes labels Natural Science and Technology Part II as 031 or 093
CORE_ALIAS = {"031": "093"}
NOT_COUNTED_GRADES = {"F", "W", "Q", "X", "NC", "I", "WH"}
SKIP_SECTIONS = ("GPA", "Credit Hour", "Courses/hours not counting")


@dataclass
class IdaCourse:
    code: str
    title: str
    grade: str
    term: str
    unique: str
    kind: str
    credits: int
    alias: bool = False
    in_progress: bool = False


@dataclass
class CoreNeed:
    codes: list[str]  # registrar Core codes this rule covers
    names: list[str]
    required_hours: float
    lacking_hours: float
    text: str


@dataclass
class CourseRule:
    section: str
    text: str
    segments: list[list[str]]  # each segment is a set of interchangeable courses; take one from each
    lacking: float | None
    unit: str


@dataclass
class Note:
    section: str
    text: str
    lacking: float | None
    unit: str


@dataclass
class Total:
    text: str
    required: float | None
    counted: float | None
    lacking: float | None
    unit: str


@dataclass
class IdaResult:
    courses: list[IdaCourse] = field(default_factory=list)
    completed_codes: list[str] = field(default_factory=list)  # includes equivalents and in-progress courses
    in_progress_codes: list[str] = field(default_factory=list)
    core_needs: list[CoreNeed] = field(default_factory=list)
    course_rules: list[CourseRule] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    totals: list[Total] = field(default_factory=list)
    program: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def norm_code(raw: str) -> str:
    return _clean(raw).upper()


def _num(s: str) -> tuple[float | None, str]:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)?", s or "")
    if m:
        return float(m.group(1)), (m.group(2) or "").lower()
    return None, ""


_COURSE_TOKEN = re.compile(r"(?:\b([A-Z]{1,3}(?: [A-Z])?)\s+)?\b(\d{3}[A-Z]{0,2})\b")


def course_segments(text: str) -> list[list[str]]:
    """'C S 311 or 311H or 313K; 312 or 307' -> [['C S 311','C S 311H','C S 313K'], ['C S 312','C S 307']].
    Only used for rules that are essentially a list of courses."""
    segs: list[list[str]] = []
    dept = ""
    for part in re.split(r";", text):
        codes: list[str] = []
        for m in _COURSE_TOKEN.finditer(part):
            if m.group(1):
                dept = m.group(1)
            if not dept:
                continue
            num = m.group(2)
            codes.append(f"{dept} {num}")
        if codes:
            segs.append(codes)
    return segs


def _looks_like_course_list(text: str) -> bool:
    body = re.sub(r"^[A-Z -]+REQUIREMENT:\s*", "", text)
    return bool(re.match(r"^[A-Z]{1,3}(?: [A-Z])? \d{3}[A-Z]{0,2}\b", body)) and len(body) < 220


def parse_ida(html: str) -> IdaResult:
    tree = LexborHTMLParser(html)
    out = IdaResult()

    program = tree.css_first("span.major")
    out.program = _clean(program.text()) if program else None

    # --- courses taken, in progress and equivalent
    cw = tree.css_first("#coursework")
    term = ""
    seen: set[tuple[str, str, bool]] = set()
    if cw is not None:
        for tr in cw.css("tr"):
            th = tr.css_first("th.section_title")
            if th is not None:
                term = _clean(th.text()).replace(" Courses", "")
                continue
            tds = tr.css("td")
            if not tds or "course_num" not in (tds[0].attributes.get("class") or ""):
                continue
            icons = " ".join((i.attributes.get("alt") or "") for i in tds[0].css("img"))
            code = norm_code(tds[0].text())
            grade = _clean(tds[2].text()) if len(tds) > 2 else ""
            m = re.search(r"\d+", tds[5].text()) if len(tds) > 5 else None
            c = IdaCourse(
                code=code,
                title=_clean(tds[1].text()),
                grade=grade,
                term=term,
                unique=_clean(tds[3].text()) if len(tds) > 3 else "",
                kind=_clean(tds[4].text()) if len(tds) > 4 else "",
                credits=int(m.group(0)) if m else 0,
                alias="alias" in (tr.attributes.get("class") or ""),
                in_progress="In Progress" in icons,
            )
            if "Future" in icons or "Planned" in icons:
                out.warnings.append(
                    f"{code} is marked planned or future in the audit; it is not counted as taken."
                )
                continue
            key = (code, term, c.alias)
            if key in seen:
                continue
            seen.add(key)
            out.courses.append(c)

    done: list[str] = []
    prog: list[str] = []
    for c in out.courses:
        if c.grade.upper() in NOT_COUNTED_GRADES:
            continue
        if c.code not in done:
            done.append(c.code)
        if c.in_progress and c.code not in prog:
            prog.append(c.code)
    out.completed_codes = done
    out.in_progress_codes = prog

    # --- requirement checklist
    cat = tree.css_first("#categories")
    if cat is None:
        out.warnings.append("This page has no requirement checklist, so only the courses were read.")
        return out
    for table in cat.css("table.results"):
        title_el = table.css_first("th.section_title")
        section = _clean(title_el.text()) if title_el is not None else ""
        for tr in table.css("tbody.section tr"):
            if "rule" not in (tr.attributes.get("class") or ""):
                continue
            tds = tr.css("td")
            if len(tds) < 7:
                continue
            status = ""
            img = tds[1].css_first("img")
            if img is not None:
                status = (img.attributes.get("alt") or "").lower()
            text = _clean(tds[2].text())
            req, unit = _num(_clean(tds[3].text()))
            got, _ = _num(_clean(tds[4].text()))
            lack, _ = _num(_clean(tds[5].text()))
            is_totals = any(k in section for k in SKIP_SECTIONS)
            if is_totals:
                if "Credit Hour" in section:
                    out.totals.append(Total(text, req, got, lack, unit))
                continue
            if status == "completed" or not lack:
                continue
            core = re.search(r"CORE \(([^)]*)\)", text)
            if core:
                codes: list[str] = []
                for c in re.findall(r"\d{3}", core.group(1)):
                    c = CORE_ALIAS.get(c, c)
                    if c in CORE_NAME and c not in codes:
                        codes.append(c)
                if codes and "42 hours" not in text:
                    out.core_needs.append(
                        CoreNeed(codes, [CORE_NAME[c] for c in codes], req or 0, lack or 0, text)
                    )
                    continue
            if "42 hours are required" in text:
                continue  # roll-up of the rules above
            if _looks_like_course_list(text):
                segs = course_segments(text)
                if segs:
                    out.course_rules.append(CourseRule(section, text, segs, lack, unit))
                    continue
            out.notes.append(Note(section, text, lack, unit))
    return out
