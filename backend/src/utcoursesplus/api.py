"""Local web API. Everything is read from and written to the SQLite file; nothing leaves the
machine except language-model calls for audit parsing, syllabus extraction and preference tuning."""

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import anthropic
import httpx
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import (
    coursedocs,
    ida,
    llm,
    nlpref,
    plantree,
    prefs,
    replan,
    requirements,
    schedule,
    settings,
    signals,
    syllabus,
)
from .buildings import Buildings
from .catalog import CORE_NAMES, Catalog, core_tree, when_text
from .config import DATA_DIR, TERM
from .db import connect
from .fetch import BlockedError, Fetcher, SessionExpired, load_cookies
from .models import CORE_AREAS
from .quality import report

UT_RMP_SCHOOL_ID = "1255"


@dataclass
class Job:
    id: str
    kind: str
    state: str = "running"  # running | done | error
    lines: list[str] = field(default_factory=list)
    result: object = None
    error: str | None = None


class State:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path
        self.con = connect(db_path)
        self.lock = threading.RLock()
        self.buildings = Buildings.load()
        self._cat: Catalog | None = None
        self._sig: signals.SignalIndex | None = None
        self.last_top: schedule.Schedule | None = None
        self.last: dict | None = None  # most recent generation, reused by the plan map
        self.jobs: dict[str, Job] = {}
        # replaceable in tests
        self.fetcher_factory = lambda: Fetcher(cookies=load_cookies())
        self.llm_client_factory = lambda: llm.get_client("syllabus")

    def invalidate(self) -> None:
        self._cat = None
        self._sig = None

    @property
    def cat(self) -> Catalog:
        if self._cat is None:
            self._cat = Catalog.load(self.con)
        return self._cat

    @property
    def sig(self) -> signals.SignalIndex:
        if self._sig is None:
            self._sig = signals.SignalIndex(self.con, self.cat.instructor_depts())
        return self._sig

    def start_job(self, kind: str, work) -> Job:
        """Run work(connection, progress) on a thread with its own database connection. One job at a time so
        the request spacing to UT's servers is never exceeded."""
        if any(j.state == "running" for j in self.jobs.values()):
            raise RuntimeError("Another job is still running. Wait for it to finish.")
        job = Job(id=uuid.uuid4().hex[:10], kind=kind)
        self.jobs[job.id] = job

        def run():
            con = connect(self.db_path)
            try:
                job.result = work(con, job.lines.append)
                job.state = "done"
            except SessionExpired as e:
                job.error, job.state = (
                    f"Your UT login is missing or expired ({e}). Run uv run utcoursesplus login in a terminal, then try again.",
                    "error",
                )
            except BlockedError as e:
                job.error, job.state = (
                    f"The site blocked or refused a request ({e}). Stopped. Do not retry now.",
                    "error",
                )
            except (llm.LLMUnavailable, ValueError) as e:
                job.error, job.state = str(e), "error"
            except (anthropic.APIError, httpx.HTTPError) as e:
                job.error, job.state = (
                    f"A network or model call failed ({type(e).__name__}: {str(e)[:160]}).",
                    "error",
                )
            finally:
                con.close()
                with self.lock:
                    self.invalidate()

        threading.Thread(target=run, daemon=True).start()
        return job


class AuditIn(BaseModel):
    text: str


class GroupsIn(BaseModel):
    groups: list[requirements.RequirementGroup]


class ProposeIn(BaseModel):
    request: str


class ApplyIn(BaseModel):
    config: dict[str, Any]
    note: str = ""


class GenerateIn(BaseModel):
    k: int = 8


class ReplanIn(BaseModel):
    registered: list[str] = []  # unique numbers the student now holds
    full: list[str] = []  # unique numbers that were full or refused
    dropped: list[str] = []  # unique numbers the student dropped on the plan's advice
    skipped: list[str] = []  # course codes the student has given up on
    previous: list[str] = []  # unique numbers of the steps they were following, to describe what changed
    k: int = 8


class SyllabusIn(BaseModel):
    course: str
    text: str | None = None
    url: str | None = None
    instructor: str | None = None
    term: str | None = None


class SettingsIn(BaseModel):
    keys: dict[str, str] = {}  # provider id -> API key to save
    clear_keys: list[str] = []
    custom_base_url: str | None = None
    default: str | None = None  # 'provider:model'
    tasks: dict[str, str] | None = None  # task -> 'provider:model'; empty string = use the default


class TestKeyIn(BaseModel):
    provider: str = "anthropic"
    key: str | None = None


class AddUniqueIn(BaseModel):
    unique: str
    target: str = "required"  # required | like


class CompareIn(BaseModel):
    code: str
    uniques: list[str] | None = None


class IdaParseIn(BaseModel):
    html: str


class IdaRuleChoice(BaseModel):
    segments: list[list[str]]
    mode: str = "defer"  # required | defer
    text: str = ""


class IdaApplyIn(BaseModel):
    completed: list[str] = []
    core: dict[str, str] = {}  # area code -> required | like | defer
    core_hours: dict[str, float] = {}
    rules: list[IdaRuleChoice] = []


class FindIn(BaseModel):
    courses: list[str]


class ReadIn(BaseModel):
    doc_ids: list[int]


class CsvIn(BaseModel):
    csv: str
    source: str = "manual import"
    license_note: str = "not stated"


def rmp_link(name: str) -> str:
    last = name.split(",")[0].strip() if "," in name else name.split()[-1]
    return f"https://www.ratemyprofessors.com/search/professors/{UT_RMP_SCHOOL_ID}?q={quote(last)}"


def create_app(db_path: Path | str | None = None, dist_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="UT Courses Plus", docs_url="/api/docs", openapi_url="/api/openapi.json")
    st = State(db_path)
    app.state.st = st

    def fail(code: int, msg: str):
        raise HTTPException(status_code=code, detail=msg)

    def guard_llm(fn):
        try:
            return fn()
        except llm.LLMUnavailable as e:
            fail(503, str(e))
        except (nlpref.ProposalError, ValueError) as e:
            fail(422, str(e))
        except BlockedError as e:
            fail(
                409,
                f"The site refused or blocked the request ({e}). Do not retry now; download the file yourself and paste its text.",
            )
        except (anthropic.APIError, httpx.HTTPError) as e:
            fail(
                502,
                f"The call failed ({type(e).__name__}: {str(e)[:200]}). Check your network and API key, then retry.",
            )

    # ------------------------------------------------------------------ status and sources
    @app.get("/api/status")
    def status():
        with st.lock:
            q = report(st.con)
            cfg_has_data = q["sections"] > 0
            return {
                "term": TERM,
                "sections": q["sections"],
                "courses": q["courses"],
                "departments": q["departments"],
                "has_data": cfg_has_data,
                "llm_configured": settings.configured(),
                "model": settings.default_spec(),
                "buildings_loaded": st.buildings.available,
            }

    @app.get("/api/sources")
    def sources():
        with st.lock:
            con = st.con
            signals.ensure(con)
            con.executescript(syllabus.SCHEMA_SQL)
            by_source = [
                dict(r)
                for r in con.execute(
                    "SELECT source, COUNT(*) AS sections, MIN(fetched_at) AS first_fetch, MAX(fetched_at) AS last_fetch FROM section GROUP BY source"
                )
            ]
            pages = [
                dict(r)
                for r in con.execute(
                    "SELECT source, COUNT(*) AS pages, SUM(n_sections) AS sections, SUM(n_failures) AS parse_failures, "
                    "MIN(fetched_at) AS first_fetch, MAX(fetched_at) AS last_fetch FROM crawl_log GROUP BY source"
                )
            ]
            sample_urls = [
                r[0]
                for r in con.execute(
                    "SELECT url FROM crawl_log WHERE n_sections>0 ORDER BY fetched_at DESC LIMIT 5"
                )
            ]
            n_inst = con.execute("SELECT COUNT(*) FROM instructor").fetchone()[0]
            ratings = con.execute("SELECT COUNT(*) FROM rating").fetchone()[0]
            matched = sum(
                1
                for n in {x for s in st.cat.sections.values() for x in s.instructors}
                if len(st.sig.ratings.get(signals.instructor_key(n), [])) == 1
            )
            gsrc = [
                dict(r)
                for r in con.execute("SELECT id, name, license_note, imported_at, n_rows FROM grade_source")
            ]
            syl = [
                dict(r)
                for r in con.execute(
                    "SELECT id, course, instructor, source_url, source_kind, fetched_at, lightness, coverage FROM syllabus ORDER BY id DESC"
                )
            ]
            grade_courses = len({(r[0], r[1]) for r in con.execute("SELECT dept, number FROM grade")})
            return {
                "schedule": {
                    "by_source": by_source,
                    "pages": pages,
                    "recent_urls": sample_urls,
                    "note": "Pages from the registrar schedule were read while you were logged in with your own EID."
                    if any(p["source"] == "authenticated" for p in pages)
                    else None,
                },
                "ratings": {
                    "rows": ratings,
                    "instructors_in_schedule": n_inst,
                    "matched": matched,
                    "how": "CSV import. RateMyProfessors' terms prohibit automated collection, so none is done.",
                },
                "grades": {"sources": gsrc, "courses_covered": grade_courses},
                "syllabi": syl,
                "missing": [
                    m
                    for m, ok in [
                        ("Professor ratings", ratings > 0),
                        ("Grade distributions", bool(gsrc)),
                        ("Syllabi", bool(syl)),
                    ]
                    if not ok
                ],
            }

    # ------------------------------------------------------------------ requirements
    @app.get("/api/core/areas")
    def core_areas():
        return [a.model_dump() for a in CORE_AREAS]

    @app.get("/api/requirements")
    def get_requirements():
        with st.lock:
            return requirements.load(st.con).model_dump()

    @app.put("/api/requirements")
    def put_requirements(body: dict[str, Any]):
        with st.lock:
            try:
                req = requirements.Requirements.model_validate(body)
            except ValidationError as e:
                fail(422, f"Requirements rejected: {e.errors()[0]['msg']} at {e.errors()[0]['loc']}")
            valid = {a.code for a in CORE_AREAS}
            bad = [c for c in req.core_areas if c not in valid]
            if bad:
                fail(422, f"Unknown Core area codes: {', '.join(bad)}.")
            unknown: list[str] = []

            def clean(codes: list[str]) -> list[str]:
                out = []
                for c in codes:
                    rc = requirements.resolve_code(c, st.cat)
                    if rc is None:
                        unknown.append(c)
                    elif rc not in out:
                        out.append(rc)
                return out

            req.required_courses = clean(req.required_courses)
            valid_core = {a.code for a in CORE_AREAS}
            ranked: list[str] = []
            for tok in req.preferred_courses:
                if tok.startswith("core:"):
                    code = tok[5:]
                    if code not in valid_core:
                        unknown.append(tok)
                    elif code not in req.core_areas and tok not in ranked:
                        ranked.append(tok)
                else:
                    ranked += [c for c in clean([tok]) if c not in ranked and c not in req.required_courses]
            # a course is either required or "like to take", never both; the ranking is the list order
            req.preferred_courses = ranked
            pins: dict[str, list[str]] = {}
            for code, uniques in req.pinned_sections.items():
                rc = requirements.resolve_code(code, st.cat)
                good = [
                    u
                    for u in dict.fromkeys(uniques)
                    if u in st.cat.sections and st.cat.sections[u].code == rc
                ]
                unknown += [f"{u} is not a section of {code}" for u in uniques if u not in good]
                if rc and good:
                    pins[rc] = good
            req.pinned_sections = pins
            req.completed_courses = list(
                dict.fromkeys(" ".join(c.upper().split()) for c in req.completed_courses if c.strip())
            )
            req.core_slots = {a: max(1, min(int(n), 6)) for a, n in req.core_slots.items() if a in valid_core}
            requirements.save(st.con, req)
            return {"requirements": req.model_dump(), "not_in_schedule": unknown}

    @app.post("/api/requirements/audit/parse")
    def audit_parse(body: AuditIn):
        parsed, sent = guard_llm(lambda: requirements.parse_audit(body.text))
        return {
            "groups": [g.model_dump() for g in parsed.groups],
            "notes": parsed.notes,
            "characters_sent": sent,
            "stored": False,
        }

    @app.post("/api/requirements/audit/apply")
    def audit_apply(body: GroupsIn):
        with st.lock:
            req, warnings = requirements.apply_groups(requirements.load(st.con), body.groups, st.cat)
            requirements.save(st.con, req)
            return {"requirements": req.model_dump(), "warnings": warnings}

    # ------------------------------------------------------------------ degree audit (IDA) import, read locally
    @app.post("/api/requirements/ida/parse")
    def ida_parse(body: IdaParseIn):
        if len(body.html) > 8_000_000:
            fail(422, "That file is larger than 8 MB, so it is probably not an audit results page.")
        r = ida.parse_ida(body.html)
        if not r.courses and not r.core_needs and not r.notes:
            fail(
                422,
                "No courses or requirements were found. Save the audit's Results page (File > Save Page As, HTML only) and choose that file.",
            )
        return {**r.as_dict(), "stored": False}

    @app.post("/api/requirements/ida/apply")
    def ida_apply(body: IdaApplyIn):
        with st.lock:
            req = requirements.load(st.con)
            valid = {a.code for a in CORE_AREAS}
            req.completed_courses = list(
                dict.fromkeys(
                    [*req.completed_courses, *(" ".join(c.upper().split()) for c in body.completed)]
                )
            )
            warnings: list[str] = []
            for code, mode in body.core.items():
                if code not in valid:
                    warnings.append(f"Unknown Core code {code} was ignored.")
                    continue
                tok = f"core:{code}"
                req.core_areas = [c for c in req.core_areas if c != code]
                req.preferred_courses = [c for c in req.preferred_courses if c != tok]
                if mode == "required":
                    req.core_areas.append(code)
                elif mode == "like":
                    req.preferred_courses.append(tok)
                hours = body.core_hours.get(code)
                if hours and mode in ("required", "like"):
                    req.core_slots[code] = max(1, min(6, round(hours / 3)))
            for rule in body.rules:
                if rule.mode != "required":
                    continue
                for seg in rule.segments:
                    codes = [c for c in (requirements.resolve_code(x, st.cat) for x in seg) if c]
                    codes = [c for c in codes if c not in req.completed_courses]
                    if not codes:
                        warnings.append(
                            f"None of {', '.join(seg)} is offered in Spring 2027 or not already taken, so it was left out."
                        )
                    elif len(codes) == 1:
                        if codes[0] not in req.required_courses:
                            req.required_courses.append(codes[0])
                    else:
                        req.groups.append(
                            requirements.RequirementGroup(
                                name=rule.text[:80] or "Choose one", kind="choose_from", courses=codes, pick=1
                            )
                        )
            req.required_courses = [c for c in req.required_courses if c not in req.completed_courses]
            req.preferred_courses = [c for c in req.preferred_courses if c not in req.completed_courses]
            requirements.save(st.con, req)
            st.invalidate()
            return {"requirements": req.model_dump(), "warnings": warnings}

    @app.get("/api/core/tree")
    def tree(areas: str | None = None):
        with st.lock:
            codes = [a for a in (areas.split(",") if areas else requirements.load(st.con).core_areas) if a]
            return core_tree(st.cat, codes, set(requirements.load(st.con).completed_courses))

    # ------------------------------------------------------------------ courses
    @app.get("/api/courses")
    def courses(
        q: str = "", dept: str = "", level: str = "", core: str = "", status: str = "", limit: int = 6000
    ):
        with st.lock:
            sc = schedule.Scorer(prefs.current(st.con), st.sig, st.buildings)
            ql = q.strip().lower()
            done = set(requirements.load(st.con).completed_courses)
            rows = []
            for s in st.cat.sections.values():
                if dept and s.dept != dept:
                    continue
                if level and s.level != level:
                    continue
                if core and core not in s.core:
                    continue
                if status and s.status != status:
                    continue
                if ql and ql not in f"{s.code} {s.title} {' '.join(s.instructors)} {s.unique}".lower():
                    continue
                rows.append(s)
            rows.sort(key=lambda s: (s.code, s.title, s.unique))
            total = len(rows)
            out = []
            for s in rows[:limit]:
                sg = sc.signal(s)
                d = schedule.section_json(s)
                d["taken"] = s.code in done
                d["signal"] = {
                    k: getattr(sg, k)
                    for k in (
                        "ease",
                        "ease_lo",
                        "ease_hi",
                        "ease_score",
                        "ease_score_lo",
                        "ease_score_hi",
                        "confidence",
                        "lightness",
                        "lightness_coverage",
                        "gpa",
                        "n_graded",
                        "rmp_difficulty",
                        "rmp_rating",
                        "rmp_n",
                        "signals",
                    )
                }
                out.append(d)
            return {"total": total, "rows": out}

    @app.get("/api/departments")
    def departments():
        with st.lock:
            return sorted({s.dept for s in st.cat.sections.values()})

    @app.get("/api/instructors/rmp-link")
    def get_rmp_link(name: str):
        return {"url": rmp_link(name)}

    @app.get("/api/syllabus/{sid}")
    def syllabus_detail(sid: int):
        import json

        with st.lock:
            st.con.executescript(syllabus.SCHEMA_SQL)
            r = st.con.execute("SELECT * FROM syllabus WHERE id=?", (sid,)).fetchone()
            if not r:
                fail(404, "No syllabus with that id.")
            d = dict(r)
            d["extraction"] = json.loads(d.pop("extraction_json"))
            d["dropped"] = json.loads(d.pop("dropped_json"))
            d["components"] = json.loads(d.pop("components_json"))
            return d

    # ------------------------------------------------------------------ preferences
    @app.get("/api/prefs")
    def get_prefs():
        with st.lock:
            cfg = prefs.current(st.con)
            cfg.hard.required_courses = requirements.load(st.con).required_courses
            return {"config": cfg.model_dump(), "history": prefs.history(st.con)}

    def _save(cfg_in: dict[str, Any], note: str):
        try:
            cfg = prefs.PreferenceConfig.model_validate(cfg_in)
        except ValidationError as e:
            fail(
                422,
                f"Preferences rejected: {e.errors()[0]['msg']} at {'.'.join(map(str, e.errors()[0]['loc']))}.",
            )
        cfg.hard.required_courses = []  # required courses live on the Requirements screen
        prefs.save(st.con, cfg, note)
        return cfg

    @app.put("/api/prefs")
    def put_prefs(body: ApplyIn):
        with st.lock:
            cfg = _save(body.config, body.note or "Edited in settings")
            return {"config": cfg.model_dump(), "history": prefs.history(st.con)}

    @app.post("/api/prefs/propose")
    def propose(body: ProposeIn):
        with st.lock:
            cur = prefs.current(st.con)
        return guard_llm(lambda: nlpref.propose(body.request, cur))

    @app.post("/api/prefs/apply")
    def apply(body: ApplyIn):
        with st.lock:
            cfg = _save(body.config, body.note or "Applied from natural-language request")
            return {"config": cfg.model_dump(), "history": prefs.history(st.con)}

    @app.post("/api/prefs/undo")
    def undo():
        with st.lock:
            cfg = prefs.undo(st.con)
            return {"config": cfg.model_dump(), "history": prefs.history(st.con)}

    # ------------------------------------------------------------------ schedules
    def run_generate(k: int) -> dict[str, Any]:
        cfg = prefs.current(st.con)
        req = requirements.load(st.con)
        cfg.hard.required_courses = req.required_courses
        res = schedule.generate(st.cat, req, cfg, st.sig, st.buildings, k=max(1, min(k, 25)))
        scorer = schedule.Scorer(cfg, st.sig, st.buildings)
        scorer.wish = schedule.wish_weights(req)
        w = scorer.weights()
        out: dict[str, Any] = {
            "problems": res.problems,
            "notes": res.notes,
            "truncated": res.truncated,
            "searched": res.nodes,
            "schedules": [],
            "backups": [],
            "registration": None,
            "weights": w,
            "change": [],
            "deferrals": res.deferrals,
            "plan_tree": None,
        }
        st.last = None
        if res.schedules:
            top = res.schedules[0]
            for i, sch in enumerate(res.schedules):
                d = schedule.schedule_json(sch, scorer)
                nxt = res.schedules[i + 1] if i + 1 < len(res.schedules) else None
                d["why"] = schedule.explain_vs(sch, nxt, w)
                d["why_against"] = f"{nxt.credits} credits, utility {nxt.utility:.3f}" if nxt else None
                out["schedules"].append(d)
            backs = schedule.backups(res.pool, top, 3)
            out["backups"] = [schedule.schedule_json(b, scorer) for b in backs]
            out["registration"] = schedule.registration_plan(st.cat, top, req, cfg)
            out["plan_tree"] = plantree.plan_tree(st.cat, req, cfg, scorer, top, backs, out["registration"])
            out["change"] = schedule.describe_change(st.last_top, top) if st.last_top else []
            st.last_top = top
        return out

    @app.post("/api/schedules/generate")
    def generate(body: GenerateIn):
        with st.lock:
            return run_generate(body.k)

    @app.post("/api/plan/replan")
    def plan_replan(body: ReplanIn):
        with st.lock:
            cfg = prefs.current(st.con)
            req = requirements.load(st.con)
            cfg.hard.required_courses = req.required_courses
            return replan.replan(
                st.cat,
                req,
                cfg,
                st.sig,
                st.buildings,
                registered=body.registered,
                full=body.full,
                skipped=body.skipped,
                previous=body.previous,
                dropped=body.dropped,
                k=max(1, min(body.k, 12)),
            )

    @app.get("/api/courses/sections")
    def course_sections(code: str):
        with st.lock:
            rc = requirements.resolve_code(code, st.cat) or code.strip().upper()
            secs = sorted(st.cat.by_code.get(rc, []), key=lambda s: (s.status == "cancelled", s.unique))
            sc = schedule.Scorer(prefs.current(st.con), st.sig, st.buildings)
            return {
                "code": rc,
                "pinned": requirements.load(st.con).pinned_sections.get(rc, []),
                "sections": [schedule.section_json(s, sc) for s in secs],
            }

    @app.post("/api/requirements/add-unique")
    def add_unique(body: AddUniqueIn):
        u = body.unique.strip()
        with st.lock:
            sec = st.cat.sections.get(u)
            if not sec:
                fail(404, f"{u} is not a unique number in the Spring 2027 schedule you loaded.")
            if sec.status == "cancelled":
                fail(422, f"{u} ({sec.code}) is cancelled.")
            req = requirements.load(st.con)
            if sec.code not in req.required_courses and sec.code not in req.preferred_courses:
                (req.required_courses if body.target == "required" else req.preferred_courses).append(
                    sec.code
                )
            pins = req.pinned_sections.setdefault(sec.code, [])
            if u not in pins:
                pins.append(u)
            requirements.save(st.con, req)
            return {"requirements": req.model_dump(), "added": f"{sec.code} {sec.title}, unique {u}"}

    @app.post("/api/schedules/compare")
    def compare(body: CompareIn):
        with st.lock:
            cfg = prefs.current(st.con)
            req = requirements.load(st.con)
            code = requirements.resolve_code(body.code, st.cat)
            if not code:
                fail(422, f"{body.code} is not in the Spring 2027 schedule.")
            avail = [s.unique for s in st.cat.by_code[code] if s.status != "cancelled"]
            uniques = [u for u in (body.uniques or req.pinned_sections.get(code) or avail) if u in avail][:12]
            if len(uniques) < 2:
                fail(422, "Choose at least two sections of the course to compare.")
            rows, weights = schedule.compare_sections(st.cat, req, cfg, st.sig, st.buildings, code, uniques)
            scorer = schedule.Scorer(cfg, st.sig, st.buildings)
            best_u = next((r.utility for r in rows if r.schedule and r.included), None)
            return {
                "code": code,
                "in_plan_as": "required"
                if code in req.required_courses
                else "like to take"
                if code in req.preferred_courses
                else "added for this comparison",
                "rows": [
                    {
                        "unique": r.unique,
                        "section": schedule.section_json(r.section, scorer) if r.section else None,
                        "fits": bool(r.schedule and r.included),
                        "utility": None if r.utility is None else round(r.utility, 4),
                        "delta": None if r.delta is None else round(r.delta, 4),
                        "why": r.why,
                        "problems": r.problems
                        if not r.schedule
                        else (
                            []
                            if r.included
                            else [f"{code} was left out of the best schedule with this section."]
                        ),
                        "schedule": schedule.schedule_json(r.schedule, scorer) if r.schedule else None,
                    }
                    for r in rows
                ],
                "best_utility": best_u,
                "weights": weights,
            }

    @app.get("/api/plan/tree")
    def plan_tree_ep():
        with st.lock:
            out = run_generate(8)
            return {
                "tree": out["plan_tree"],
                "problems": out["problems"],
                "deferrals": out["deferrals"],
                "notes": out["notes"],
            }

    # ------------------------------------------------------------------ settings and API key
    @app.get("/api/settings")
    def get_settings():
        return settings.public_view()

    @app.put("/api/settings")
    def put_settings(body: SettingsIn):
        for p, k in body.keys.items():
            if p not in settings.PROVIDERS:
                fail(422, f"Unknown provider {p!r}.")
            if k.strip() and (len(k.strip()) < 20 or any(c.isspace() for c in k.strip())):
                fail(422, "That does not look like an API key. Paste the whole key with no spaces.")
        for p in body.clear_keys:
            if p not in settings.PROVIDERS:
                fail(422, f"Unknown provider {p!r}.")
        specs = [s for s in [body.default, *(body.tasks or {}).values()] if s]
        for s in specs:
            if not settings.valid_spec(s):
                fail(422, f"{s!r} is not a provider and model. Choose both on the AI models screen.")
        for t in body.tasks or {}:
            if t not in settings.TASKS:
                fail(422, f"Unknown job {t!r}.")
        url = body.custom_base_url
        if url and not url.strip().startswith(("https://", "http://localhost", "http://127.0.0.1")):
            fail(
                422,
                "The service address must start with https:// (or http://localhost for a model on this computer).",
            )
        settings.update(
            keys=body.keys,
            clear_keys=body.clear_keys,
            custom_base_url=url,
            default=body.default,
            tasks=body.tasks,
        )
        return settings.public_view()

    @app.post("/api/settings/test")
    def test_key(body: TestKeyIn):
        if body.provider not in settings.PROVIDERS:
            fail(422, f"Unknown provider {body.provider!r}.")
        key = (body.key or "").strip() or settings.get_key(body.provider)
        if not key:
            fail(422, "No key to test. Paste one first.")
        try:
            models = llm.list_models(body.provider, key)
        except llm.LLMUnavailable as e:
            fail(401 if "rejected" in str(e) else 502, str(e))
        ids = {m["id"] for m in models}
        chosen = {}
        for t in settings.TASKS:
            p, m = settings.resolve(t)
            if p == body.provider:
                chosen[t] = {"model": m, "available": m in ids}
        return {"ok": True, "provider": body.provider, "models": models, "chosen": chosen}

    @app.get("/api/suggestions")
    def suggestions(core: str, limit: int = 40):
        if core not in CORE_NAMES:
            fail(422, f"Unknown Core area code {core!r}.")
        with st.lock:
            cfg = prefs.current(st.con)
            sc = schedule.Scorer(cfg, st.sig, st.buildings)
            groups: dict[str, list] = {}
            done = set(requirements.load(st.con).completed_courses)
            for s in st.cat.active():
                if core in s.core and s.code not in done:
                    groups.setdefault(s.course_key, []).append(s)
            rows = []
            for secs in groups.values():
                sigs = [sc.signal(s) for s in secs]
                best = max(sigs, key=lambda g: 0.65 * g.rank_ease + 0.35 * g.rank_lightness)
                rank = 0.65 * best.rank_ease + 0.35 * best.rank_lightness
                rows.append((rank, secs, best))
            rows.sort(key=lambda t: -t[0])
            return {
                "area": CORE_NAMES[core],
                "total": len(rows),
                "courses": [
                    {
                        "code": secs[0].code,
                        "title": secs[0].title,
                        "credits": secs[0].credits,
                        "rank": round(rank, 3),
                        "signal": {
                            k: getattr(best, k)
                            for k in (
                                "ease_score",
                                "ease_score_lo",
                                "ease_score_hi",
                                "confidence",
                                "signals",
                                "lightness",
                                "gpa",
                                "rmp_rating",
                            )
                        },
                        "sections": [
                            {
                                "unique": s.unique,
                                "when": when_text(s),
                                "status": s.status,
                                "reserved": s.reserved,
                                "instructors": list(s.instructors),
                            }
                            for s in secs
                        ],
                    }
                    for rank, secs, best in rows[:limit]
                ],
            }

    # ------------------------------------------------------------------ imports
    @app.post("/api/import/ratings")
    def import_ratings(body: CsvIn):
        with st.lock:
            r = signals.import_ratings_csv(st.con, body.csv)
            st.invalidate()
            return r

    @app.post("/api/import/grades")
    def import_grades(body: CsvIn):
        with st.lock:
            r = signals.import_grades_csv(st.con, body.csv, body.source, body.license_note)
            st.invalidate()
            return r

    @app.post("/api/import/file")
    async def import_file(file: UploadFile):
        return {"filename": file.filename, "csv": (await file.read()).decode("utf-8", errors="replace")}

    @app.post("/api/syllabus")
    def add_syllabus(body: SyllabusIn):
        def run():
            with st.lock:
                out = syllabus.add_syllabus(
                    st.con,
                    body.course,
                    text=body.text,
                    url=body.url,
                    instructor=body.instructor,
                    term=body.term,
                )
                st.invalidate()
                return out

        return guard_llm(run)

    # ------------------------------------------------------------------ course-site syllabi (selected courses only)
    def spring_instructors(code: str) -> list[str]:
        names = {n for s in st.cat.by_code.get(code, []) for n in s.instructors}
        return sorted(names)

    @app.get("/api/syllabi/overview")
    def syllabi_overview():
        import json as _json

        with st.lock:
            coursedocs.ensure(st.con)
            st.con.executescript(syllabus.SCHEMA_SQL)
            req = requirements.load(st.con)
            roles = {c: "required" for c in req.required_courses}
            roles.update({c: "like to take" for c in req.preferred_courses})
            docs = {r["course"] for r in st.con.execute("SELECT DISTINCT course FROM syllabus_doc")}
            read = {r["course"] for r in st.con.execute("SELECT DISTINCT course FROM syllabus")}
            out = []
            for code in list(roles) + sorted((docs | read) - set(roles)):
                secs = st.cat.by_code.get(code, [])
                d = {
                    r["status"]: r["n"]
                    for r in st.con.execute(
                        "SELECT status, COUNT(*) AS n FROM syllabus_doc WHERE course=? GROUP BY status",
                        (code,),
                    )
                }
                reads = [
                    dict(r)
                    for r in st.con.execute(
                        "SELECT id, term, instructor, source_url, source_kind, lightness, coverage, components_json FROM syllabus "
                        "WHERE course=? ORDER BY id DESC",
                        (code,),
                    )
                ]
                for r in reads:
                    r["components"] = _json.loads(r.pop("components_json"))
                vals = [r["lightness"] for r in reads if r["lightness"] is not None]
                out.append(
                    {
                        "code": code,
                        "role": roles.get(code),
                        "title": secs[0].title if secs else None,
                        "instructors": spring_instructors(code),
                        "docs": d,
                        "syllabi": reads,
                        "difficulty": (1 - sum(vals) / len(vals)) if vals else None,
                    }
                )
            return {
                "courses": out,
                "session_saved": (DATA_DIR / "session" / "state.json").exists(),
                "llm_configured": settings.configured(),
            }

    @app.get("/api/syllabi/docs")
    def syllabi_docs(course: str):
        with st.lock:
            coursedocs.ensure(st.con)
            rows = st.con.execute(
                "SELECT id, term_text, unique_no, title, instructors, url, kind, recommended, status, error FROM syllabus_doc "
                "WHERE course=? ORDER BY year DESC, season DESC, unique_no",
                (course.upper(),),
            ).fetchall()
            return [dict(r) for r in rows]

    def job_or_409(kind: str, work):
        try:
            return st.start_job(kind, work)
        except RuntimeError as e:
            fail(409, str(e))

    @app.post("/api/syllabi/find")
    def syllabi_find(body: FindIn):
        with st.lock:
            courses = {}
            for c in body.courses[:40]:
                code = requirements.resolve_code(c, st.cat) or c.strip().upper()
                courses[code] = spring_instructors(code)
        if not courses:
            fail(422, "Select at least one course.")
        try:
            fetcher = st.fetcher_factory()
        except SessionExpired:
            fail(409, "No saved UT login. Run uv run utcoursesplus login in a terminal, then try again.")
        job = job_or_409("find", lambda con, say: coursedocs.find_docs(con, fetcher, courses, say))
        return {"job": job.id}

    @app.post("/api/syllabi/read")
    def syllabi_read(body: ReadIn):
        if not body.doc_ids:
            fail(422, "Select at least one syllabus.")
        if len(body.doc_ids) > 30:
            fail(422, "Read at most 30 syllabi at a time.")
        try:
            client = st.llm_client_factory()
            fetcher = st.fetcher_factory()
        except llm.LLMUnavailable as e:
            fail(503, str(e))
        except SessionExpired:
            fail(409, "No saved UT login. Run uv run utcoursesplus login in a terminal, then try again.")
        job = job_or_409(
            "read", lambda con, say: coursedocs.read_docs(con, fetcher, body.doc_ids, client, say)
        )
        return {"job": job.id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        j = st.jobs.get(job_id)
        if not j:
            fail(404, "No such job. The server may have restarted.")
        return {
            "id": j.id,
            "kind": j.kind,
            "state": j.state,
            "lines": j.lines[-60:],
            "error": j.error,
            "result": j.result,
        }

    # ------------------------------------------------------------------ static frontend
    dist = dist_dir or Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            f = dist / path
            return FileResponse(f if path and f.is_file() else dist / "index.html")

    else:
        from fastapi.responses import PlainTextResponse

        @app.get("/", response_class=PlainTextResponse)
        def no_frontend():
            return PlainTextResponse(
                "The server is running, but the web interface has not been built.\n"
                "In another terminal, run these two commands one after the other:\n"
                "  cd frontend\n"
                "  npm install && npm run build\n"
                "Then reload this page. (Use && and not &, so the build waits for the install.)\n"
            )

    return app


def default_app() -> FastAPI:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return create_app()
