"""Optional per-course signals: professor ratings (CSV import), grade distributions (CSV import),
syllabus lightness. Every signal may be missing; scores drop what is missing and report confidence.

Estimation is empirical Bayes on a z scale. Each course/instructor's true difficulty has a prior
N(0, 1) in units of the between-course spread tau. A source with n observations of per-observation
spread sigma contributes precision n * tau^2 / sigma^2 and an observed z. The posterior mean is the
precision-weighted average shrunk toward 0 (the department prior), and the posterior variance is
1 / (1 + total precision). With no data the estimate is the prior with a wide interval."""

import csv
import io
import math
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from statistics import NormalDist

PHI = NormalDist().cdf

# Spreads in each source's own units. These are judgment values, documented here and in tests.
GPA_SIGMA, GPA_TAU = 0.85, 0.35  # per-student GPA spread; spread of course mean GPAs
RMP_DIFF_SIGMA, RMP_DIFF_TAU = 1.1, 0.7  # per-rater difficulty (1-5) spread; spread between professors
RMP_QUAL_SIGMA, RMP_QUAL_TAU = 1.2, 0.6
GRADE_N_CAP = 400  # one course's huge enrollment must not make the estimate look certain
MIN_COURSE_INSTRUCTOR_N = 20  # below this, use the course-wide grades instead of this instructor's
DEFAULT_GPA, DEFAULT_RMP_DIFF, DEFAULT_RMP_QUAL = 3.3, 3.0, 3.5
EASE_BLEND = {"difficulty": 0.65, "lightness": 0.35}
RANK_PENALTY = 0.5  # rank value = score - RANK_PENALTY * interval half-width

GRADE_POINTS = {
    "A": 4.0,
    "A-": 3.67,
    "B+": 3.33,
    "B": 3.0,
    "B-": 2.67,
    "C+": 2.33,
    "C": 2.0,
    "C-": 1.67,
    "D+": 1.33,
    "D": 1.0,
    "D-": 0.67,
    "F": 0.0,
}
DROP_COLS = ["W", "Q", "X", "DROP", "DROPS", "WITHDRAW"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS rating(
  instructor TEXT PRIMARY KEY, key TEXT NOT NULL, avg_rating REAL, avg_difficulty REAL,
  num_ratings INTEGER NOT NULL, would_take_again REAL, source_url TEXT, imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS grade_source(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, license_note TEXT NOT NULL, imported_at TEXT NOT NULL,
  n_rows INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS grade(
  source_id INTEGER NOT NULL REFERENCES grade_source(id), dept TEXT NOT NULL, number TEXT NOT NULL,
  instructor_key TEXT, instructor TEXT, term TEXT, n_graded INTEGER NOT NULL, mean_gpa REAL NOT NULL,
  a_n REAL NOT NULL, drop_n REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_grade_course ON grade(dept, number);
"""


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def instructor_key(name: str) -> str:
    """'SMITH, JOHN Q' and 'John Smith' both -> 'smith|j'. Hyphens and punctuation are ignored."""
    s = name.strip()
    if "," in s:
        last, first = s.split(",", 1)
    else:
        parts = s.split()
        if len(parts) < 2:
            return re.sub(r"[^a-z]", "", s.lower()) + "|"
        first, last = parts[0], parts[-1]
    last = re.sub(r"[^a-z]", "", last.lower())
    first = re.sub(r"[^a-z]", "", first.strip().lower())
    return f"{last}|{first[:1]}"


def course_code(dept: str, number: str) -> str:
    return f"{dept.strip().upper()} {number.strip().upper()}"


# ----------------------------------------------------------------------------- imports


def _rows(text: str) -> list[dict[str, str]]:
    rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rd]


def _num(s: str | None) -> float | None:
    if s is None or s.strip() in ("", "N/A", "n/a", "-"):
        return None
    try:
        v = float(s.strip().rstrip("%"))
    except ValueError:
        return None
    return v / 100 if s.strip().endswith("%") else v


def import_ratings_csv(con: sqlite3.Connection, text: str) -> dict:
    """Columns: instructor, avg_rating, avg_difficulty, num_ratings, would_take_again, source_url."""
    ensure(con)
    ok, bad = 0, []
    now = datetime.now(UTC).isoformat()
    with con:
        for i, r in enumerate(_rows(text), start=2):
            name, n = r.get("instructor", ""), _num(r.get("num_ratings"))
            rating, diff = _num(r.get("avg_rating")), _num(r.get("avg_difficulty"))
            if not name or n is None or n < 1 or (rating is None and diff is None):
                bad.append(f"line {i}: need instructor, num_ratings >= 1 and a rating or difficulty")
                continue
            if (rating is not None and not 1 <= rating <= 5) or (diff is not None and not 1 <= diff <= 5):
                bad.append(f"line {i}: ratings and difficulty must be between 1 and 5")
                continue
            wta = _num(r.get("would_take_again"))
            if wta is not None and wta > 1:
                wta /= 100
            con.execute(
                "INSERT OR REPLACE INTO rating VALUES(?,?,?,?,?,?,?,?)",
                (name, instructor_key(name), rating, diff, int(n), wta, r.get("source_url") or None, now),
            )
            ok += 1
    return {"imported": ok, "rejected": bad}


def gpa_from_counts(counts: dict[str, float]) -> tuple[float, float, float, float]:
    """-> (n_graded, mean_gpa, a_n, drop_n) from letter-grade counts."""
    n = sum(counts.get(g, 0) for g in GRADE_POINTS)
    pts = sum(counts.get(g, 0) * p for g, p in GRADE_POINTS.items())
    a_n = counts.get("A", 0) + counts.get("A-", 0)
    drops = sum(counts.get(d, 0) for d in DROP_COLS)
    return n, (pts / n if n else 0.0), a_n, drops


def import_grades_csv(con: sqlite3.Connection, text: str, source: str, license_note: str) -> dict:
    """Either letter-grade count columns (A, A-, ... F, W) or aggregates: n, mean_gpa, a_rate,
    drop_rate. Always needs dept and number; instructor and term are optional."""
    ensure(con)
    rows = _rows(text)
    ok, bad = [], []
    for i, r in enumerate(rows, start=2):
        dept, number = r.get("dept", "").upper(), r.get("number", r.get("course_number", "")).upper()
        if not dept or not number:
            bad.append(f"line {i}: dept and number are required")
            continue
        counts = {g: _num(r.get(g.lower())) or 0.0 for g in GRADE_POINTS}
        counts.update({d: _num(r.get(d.lower())) or 0.0 for d in DROP_COLS})
        if any(counts[g] for g in GRADE_POINTS):
            n, gpa, a_n, drops = gpa_from_counts(counts)
        else:
            n, gpa = _num(r.get("n")), _num(r.get("mean_gpa"))
            if n is None or gpa is None or n <= 0 or not 0 <= gpa <= 4:
                bad.append(f"line {i}: give grade counts, or n and mean_gpa (0-4)")
                continue
            a_n = (_num(r.get("a_rate")) or 0.0) * n
            dr = _num(r.get("drop_rate")) or 0.0
            drops = n * dr / (1 - dr) if dr < 1 else 0.0
        if n <= 0:
            bad.append(f"line {i}: no graded students")
            continue
        inst = r.get("instructor") or None
        ok.append(
            (
                dept,
                number,
                instructor_key(inst) if inst else None,
                inst,
                r.get("term") or None,
                int(n),
                gpa,
                a_n,
                drops,
            )
        )
    with con:
        sid = con.execute(
            "INSERT INTO grade_source(name, license_note, imported_at, n_rows) VALUES(?,?,?,?)",
            (source, license_note, datetime.now(UTC).isoformat(), len(ok)),
        ).lastrowid
        con.executemany("INSERT INTO grade VALUES(?,?,?,?,?,?,?,?,?,?)", [(sid, *t) for t in ok])
    return {"imported": len(ok), "rejected": bad, "source_id": sid}


# ----------------------------------------------------------------------------- estimation


@dataclass
class Estimate:
    """Difficulty/ease on 0..1 (ease = 1 - difficulty), with a 95% interval."""

    ease: float
    ease_lo: float
    ease_hi: float
    sources: list[str] = field(default_factory=list)


def posterior(observations: list[tuple[float, float]]) -> tuple[float, float]:
    """observations: [(z, precision)] -> (posterior mean z, posterior sd z) with a N(0,1) prior."""
    prec = sum(p for _, p in observations)
    mean = sum(z * p for z, p in observations) / (1.0 + prec)
    return mean, math.sqrt(1.0 / (1.0 + prec))


def z_to_ease(mean_z: float, sd_z: float) -> tuple[float, float, float]:
    """Higher z means harder. Ease = 1 - Phi(z); interval from +/- 1.96 sd."""
    return 1 - PHI(mean_z), 1 - PHI(mean_z + 1.96 * sd_z), 1 - PHI(mean_z - 1.96 * sd_z)


def confidence_label(sd_z: float, n_sources: int) -> str:
    if n_sources == 0:
        return "None"
    if sd_z < 0.45 and n_sources >= 2:
        return "High"
    if sd_z < 0.7:
        return "Medium"
    return "Low"


@dataclass
class CourseSignal:
    code: str
    # difficulty-based ease (grades + professor difficulty)
    ease: float | None = None
    ease_lo: float | None = None
    ease_hi: float | None = None
    difficulty_sources: list[str] = field(default_factory=list)
    gpa: float | None = None
    n_graded: int = 0
    a_rate: float | None = None
    drop_rate: float | None = None
    rmp_difficulty: float | None = None
    rmp_rating: float | None = None
    rmp_n: int = 0
    # professor quality 0..1 (shrunk)
    quality: float | None = None
    quality_lo: float | None = None
    quality_hi: float | None = None
    # syllabus
    lightness: float | None = None
    lightness_coverage: float = 0.0
    # blended course ease score
    ease_score: float | None = None
    ease_score_lo: float | None = None
    ease_score_hi: float | None = None
    confidence: str = "None"
    rank_ease: float = 0.35  # conservative value used for ranking (missing data lowers it)
    rank_lightness: float = 0.35
    rank_quality: float = 0.35
    signals: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _prior_halfwidth_rank(prior_mean: float = 0.5, halfwidth: float = 0.475) -> float:
    return prior_mean - RANK_PENALTY * halfwidth


class SignalIndex:
    """Loads all optional signals once and answers per course/instructor queries."""

    def __init__(self, con: sqlite3.Connection, instructor_depts: dict[str, set[str]] | None = None):
        ensure(con)
        self.ratings: dict[str, list[sqlite3.Row]] = {}
        for r in con.execute("SELECT * FROM rating"):
            self.ratings.setdefault(r["key"], []).append(r)
        self.grades_by_course: dict[str, list[sqlite3.Row]] = {}
        for r in con.execute("SELECT * FROM grade"):
            self.grades_by_course.setdefault(course_code(r["dept"], r["number"]), []).append(r)
        self.syllabus: dict[tuple[str, str | None], tuple[float, float]] = {}
        try:
            for r in con.execute("SELECT course, instructor_key, lightness, coverage FROM syllabus"):
                self.syllabus[(r["course"], r["instructor_key"])] = (r["lightness"], r["coverage"])
        except sqlite3.OperationalError:
            pass
        self.dept_gpa = self._dept_gpa()
        self.global_gpa = self._global_gpa()
        self.dept_rmp = self._dept_rmp(instructor_depts or {})
        allr = [r for rs in self.ratings.values() for r in rs]
        self.global_rmp_diff = _weighted(
            [(r["avg_difficulty"], r["num_ratings"]) for r in allr], DEFAULT_RMP_DIFF
        )
        self.global_rmp_qual = _weighted(
            [(r["avg_rating"], r["num_ratings"]) for r in allr], DEFAULT_RMP_QUAL
        )

    # --- priors
    def _global_gpa(self) -> float:
        rows = [r for rs in self.grades_by_course.values() for r in rs]
        return _weighted([(r["mean_gpa"], r["n_graded"]) for r in rows], DEFAULT_GPA)

    def _dept_gpa(self) -> dict[str, float]:
        out: dict[str, list[tuple[float, float]]] = {}
        for rs in self.grades_by_course.values():
            for r in rs:
                out.setdefault(r["dept"].upper(), []).append((r["mean_gpa"], r["n_graded"]))
        return {d: _weighted(v, DEFAULT_GPA) for d, v in out.items()}

    def _dept_rmp(self, inst_depts: dict[str, set[str]]) -> dict[str, tuple[float, float]]:
        acc: dict[str, list[tuple[float, float, float]]] = {}
        for key, rs in self.ratings.items():
            for r in rs:
                for d in inst_depts.get(key, ()):
                    acc.setdefault(d, []).append((r["avg_difficulty"], r["avg_rating"], r["num_ratings"]))
        out = {}
        for d, v in acc.items():
            out[d] = (
                _weighted([(a, w) for a, _, w in v if a is not None], DEFAULT_RMP_DIFF),
                _weighted([(b, w) for _, b, w in v if b is not None], DEFAULT_RMP_QUAL),
            )
        return out

    # --- queries
    def estimate(self, code: str, instructor_names: list[str]) -> CourseSignal:
        dept = code.split(" ")[0] if " " in code else code
        # a course code like "C S 429" has a two-token dept
        m = re.match(r"^(.*?)\s+(\d\w*)$", code)
        dept = m.group(1) if m else dept
        keys = [instructor_key(n) for n in instructor_names if n]
        sig = CourseSignal(code=code)
        obs: list[tuple[float, float]] = []

        # grades: course+instructor if enough students, otherwise whole course
        rows = self.grades_by_course.get(code, [])
        mine = [r for r in rows if r["instructor_key"] in keys] if keys else []
        use = mine if sum(r["n_graded"] for r in mine) >= MIN_COURSE_INSTRUCTOR_N else rows
        if use:
            n = sum(r["n_graded"] for r in use)
            gpa = sum(r["mean_gpa"] * r["n_graded"] for r in use) / n
            prior = self.dept_gpa.get(dept, self.global_gpa)
            z = (prior - gpa) / GPA_TAU
            neff = min(n, GRADE_N_CAP)
            obs.append((z, neff * GPA_TAU**2 / GPA_SIGMA**2))
            sig.gpa, sig.n_graded = gpa, int(n)
            sig.a_rate = sum(r["a_n"] for r in use) / n
            tot = n + sum(r["drop_n"] for r in use)
            sig.drop_rate = sum(r["drop_n"] for r in use) / tot if tot else None
            sig.difficulty_sources.append("grades")

        # professor ratings (pooled over co-instructors that have ratings)
        # a name key shared by two imported people is ambiguous: use neither
        rat = [self.ratings[k][0] for k in dict.fromkeys(keys) if len(self.ratings.get(k, [])) == 1]
        if rat:
            dprior, qprior = self.dept_rmp.get(dept, (self.global_rmp_diff, self.global_rmp_qual))
            dn = [(r["avg_difficulty"], r["num_ratings"]) for r in rat if r["avg_difficulty"] is not None]
            if dn:
                n = sum(w for _, w in dn)
                x = sum(a * w for a, w in dn) / n
                obs.append(((x - dprior) / RMP_DIFF_TAU, n * RMP_DIFF_TAU**2 / RMP_DIFF_SIGMA**2))
                sig.rmp_difficulty, sig.rmp_n = x, int(n)
                sig.difficulty_sources.append("professor ratings")
            qn = [(r["avg_rating"], r["num_ratings"]) for r in rat if r["avg_rating"] is not None]
            if qn:
                n = sum(w for _, w in qn)
                x = sum(a * w for a, w in qn) / n
                prec = n * RMP_QUAL_TAU**2 / RMP_QUAL_SIGMA**2
                zq = (x - qprior) / RMP_QUAL_TAU
                mean, sd = posterior([(zq, prec)])
                post = qprior + mean * RMP_QUAL_TAU
                half = 1.96 * sd * RMP_QUAL_TAU
                sig.rmp_rating = x
                sig.quality = _clip((post - 1) / 4)
                sig.quality_lo, sig.quality_hi = _clip((post - half - 1) / 4), _clip((post + half - 1) / 4)
                sig.rank_quality = _clip(sig.quality - RANK_PENALTY * (sig.quality_hi - sig.quality_lo) / 2)
        if "professor ratings" in sig.difficulty_sources or sig.quality is not None:
            sig.signals.append("professor ratings")
        if "grades" in sig.difficulty_sources:
            sig.signals.append("grades")

        mean_z, sd_z = posterior(obs)
        if obs:
            sig.ease, sig.ease_lo, sig.ease_hi = z_to_ease(mean_z, sd_z)
            sig.rank_ease = _clip(sig.ease - RANK_PENALTY * (sig.ease_hi - sig.ease_lo) / 2)

        # syllabus lightness: instructor-specific if present, else any syllabus for the course
        found = next(((self.syllabus[(code, k)]) for k in keys if (code, k) in self.syllabus), None)
        found = found or self.syllabus.get((code, None))
        if found:
            sig.lightness, sig.lightness_coverage = found
            sig.signals.append("syllabus")
            half = 0.5 * (1 - sig.lightness_coverage) + 0.05
            sig.rank_lightness = _clip(sig.lightness - RANK_PENALTY * half)

        # blended ease score: missing signals dropped, weights renormalized
        parts = []
        if sig.ease is not None:
            parts.append((EASE_BLEND["difficulty"], sig.ease, sig.ease_lo, sig.ease_hi))
        if sig.lightness is not None:
            half = 0.5 * (1 - sig.lightness_coverage) + 0.05
            parts.append((EASE_BLEND["lightness"], sig.lightness, sig.lightness - half, sig.lightness + half))
        if parts:
            w = sum(p[0] for p in parts)
            sig.ease_score = sum(p[0] * p[1] for p in parts) / w
            sig.ease_score_lo = _clip(sum(p[0] * p[2] for p in parts) / w)
            sig.ease_score_hi = _clip(sum(p[0] * p[3] for p in parts) / w)
        n_src = len(sig.difficulty_sources) + (1 if sig.lightness is not None else 0)
        sig.confidence = confidence_label(sd_z if obs else 1.0, n_src)
        if sig.lightness is not None and not obs:
            sig.confidence = "Low" if sig.lightness_coverage < 0.7 else "Medium"
        return sig


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _weighted(pairs: list[tuple[float, float]], default: float) -> float:
    pairs = [(a, w) for a, w in pairs if a is not None and w]
    tw = sum(w for _, w in pairs)
    return sum(a * w for a, w in pairs) / tw if tw else default
