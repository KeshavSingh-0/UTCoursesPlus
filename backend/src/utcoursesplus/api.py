"""Local web API. Everything is read from and written to the SQLite file; nothing leaves the
machine except language-model calls for audit parsing, syllabus extraction and preference tuning."""

import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

import anthropic
import httpx
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import llm, nlpref, prefs, requirements, schedule, signals, syllabus
from .buildings import Buildings
from .catalog import CORE_NAMES, Catalog, core_tree, when_text
from .config import DATA_DIR, TERM
from .db import connect
from .fetch import BlockedError
from .models import CORE_AREAS
from .quality import report

UT_RMP_SCHOOL_ID = "1255"


class State:
    def __init__(self, db_path: Path | str | None = None):
        self.con = connect(db_path)
        self.lock = threading.RLock()
        self.buildings = Buildings.load()
        self._cat: Catalog | None = None
        self._sig: signals.SignalIndex | None = None
        self.last_top: schedule.Schedule | None = None

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


class SyllabusIn(BaseModel):
    course: str
    text: str | None = None
    url: str | None = None
    instructor: str | None = None
    term: str | None = None


class CsvIn(BaseModel):
    csv: str
    source: str = "manual import"
    license_note: str = "not stated"


def rmp_link(name: str) -> str:
    last = name.split(",")[0].strip() if "," in name else name.split()[-1]
    return f"https://www.ratemyprofessors.com/search/professors/{UT_RMP_SCHOOL_ID}?q={quote(last)}"


def create_app(db_path: Path | str | None = None) -> FastAPI:
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
                "llm_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "model": llm.MODEL,
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
            fixed, unknown = [], []
            for c in req.required_courses:
                rc = requirements.resolve_code(c, st.cat)
                (fixed if rc else unknown).append(rc or c)
            req.required_courses = list(dict.fromkeys(fixed))
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

    @app.get("/api/core/tree")
    def tree(areas: str | None = None):
        with st.lock:
            codes = [a for a in (areas.split(",") if areas else requirements.load(st.con).core_areas) if a]
            return core_tree(st.cat, codes)

    # ------------------------------------------------------------------ courses
    @app.get("/api/courses")
    def courses(
        q: str = "", dept: str = "", level: str = "", core: str = "", status: str = "", limit: int = 6000
    ):
        with st.lock:
            sc = schedule.Scorer(prefs.current(st.con), st.sig, st.buildings)
            ql = q.strip().lower()
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
    @app.post("/api/schedules/generate")
    def generate(body: GenerateIn):
        with st.lock:
            cfg = prefs.current(st.con)
            req = requirements.load(st.con)
            cfg.hard.required_courses = req.required_courses
            res = schedule.generate(st.cat, req, cfg, st.sig, st.buildings, k=max(1, min(body.k, 25)))
            scorer = schedule.Scorer(cfg, st.sig, st.buildings)
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
            }
            if res.schedules:
                top = res.schedules[0]
                for i, sch in enumerate(res.schedules):
                    d = schedule.schedule_json(sch, scorer)
                    nxt = res.schedules[i + 1] if i + 1 < len(res.schedules) else None
                    d["why"] = schedule.explain_vs(sch, nxt, w)
                    d["why_against"] = f"{nxt.credits} credits, utility {nxt.utility:.3f}" if nxt else None
                    out["schedules"].append(d)
                out["backups"] = [
                    schedule.schedule_json(b, scorer) for b in schedule.backups(res.pool, top, 3)
                ]
                out["registration"] = schedule.registration_plan(st.cat, top, req, cfg)
                out["change"] = schedule.describe_change(st.last_top, top) if st.last_top else []
                st.last_top = top
            return out

    @app.get("/api/suggestions")
    def suggestions(core: str, limit: int = 40):
        if core not in CORE_NAMES:
            fail(422, f"Unknown Core area code {core!r}.")
        with st.lock:
            cfg = prefs.current(st.con)
            sc = schedule.Scorer(cfg, st.sig, st.buildings)
            groups: dict[str, list] = {}
            for s in st.cat.active():
                if core in s.core:
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

    # ------------------------------------------------------------------ static frontend
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            f = dist / path
            return FileResponse(f if path and f.is_file() else dist / "index.html")

    return app


def default_app() -> FastAPI:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return create_app()
