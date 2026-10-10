from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from utcoursesplus import signals
from utcoursesplus.api import create_app
from utcoursesplus.db import upsert_section
from utcoursesplus.models import Course, Instructor, Meeting, Section, Tag


def sec(unique, dept, number, title, days, start, end, status="open", core=(), inst="DOE, JANE", level="L"):
    return Section(
        unique=unique,
        term="20272",
        course=Course(dept=dept, number=number, title=title, credit_hours=int(number[0])),
        meetings=[Meeting(days=days, start_min=start, end_min=end, building="GDC", room="1.1")],
        instructors=[Instructor(name=inst)],
        mode="Face-to-face",
        status=status,
        status_raw=status,
        level=level,
        tags=[Tag(kind="core", code=c, label="x") for c in core],
        source_url="https://example/x",
        fetched_at=datetime(2026, 10, 8, tzinfo=UTC),
        source="file",
    )


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "t.sqlite")
    st = app.state.st
    rows = [
        sec("10001", "C S", "312", "INTRO", ["M", "W"], 540, 600, core=["020"]),
        sec("10002", "C S", "312", "INTRO", ["T", "TH"], 540, 600, status="closed", core=["020"]),
        sec("10003", "M", "408C", "CALCULUS", ["M", "W"], 700, 760, core=["020"], inst="SMITH, JOHN"),
        sec(
            "10004",
            "GOV",
            "310L",
            "AMERICAN GOVERNMENT",
            ["T", "TH"],
            700,
            800,
            core=["070"],
            inst="ROE, RICHARD",
        ),
        sec("10005", "E", "316L", "BRITISH LITERATURE", ["F"], 540, 660, core=["040"], inst="LEE, ANN"),
    ]
    with st.lock:
        for r in rows:
            upsert_section(st.con, r)
        st.con.commit()
        st.invalidate()
    return TestClient(app)


def test_status_and_courses(client):
    s = client.get("/api/status").json()
    assert s["sections"] == 5 and s["has_data"] and s["llm_configured"] in (True, False)
    r = client.get("/api/courses", params={"q": "calc"}).json()
    assert (
        r["total"] == 1
        and r["rows"][0]["code"] == "M 408C"
        and r["rows"][0]["signal"]["confidence"] == "None"
    )
    assert client.get("/api/courses", params={"core": "070"}).json()["total"] == 1


def test_requirements_roundtrip_and_validation(client):
    r = client.put(
        "/api/requirements", json={"core_areas": ["070"], "required_courses": ["cs 312", "zz 999"]}
    ).json()
    assert r["requirements"]["required_courses"] == ["C S 312"] and "zz 999" in r["not_in_schedule"]
    assert client.get("/api/requirements").json()["core_areas"] == ["070"]
    assert client.put("/api/requirements", json={"core_areas": ["999"]}).status_code == 422
    assert client.put("/api/requirements", json={"surprise": 1}).status_code == 422
    tree = client.get("/api/core/tree").json()
    assert (
        tree[0]["name"] == "American and Texas Government"
        and tree[0]["departments"][0]["courses"][0]["code"] == "GOV 310L"
    )


def test_prefs_validation_history_and_undo(client):
    cfg = client.get("/api/prefs").json()["config"]
    cfg["hard"]["days_off"] = ["F"]
    assert client.put("/api/prefs", json={"config": cfg}).status_code == 200
    assert client.get("/api/prefs").json()["config"]["hard"]["days_off"] == ["F"]
    bad = dict(cfg, weights={"ease": -1})
    assert client.put("/api/prefs", json={"config": bad}).status_code == 422
    client.post("/api/prefs/undo")
    assert client.get("/api/prefs").json()["config"]["hard"]["days_off"] == []


def test_generate_end_to_end_with_backups_and_registration(client):
    client.put(
        "/api/requirements",
        json={
            "required_courses": ["C S 312"],
            "core_areas": ["070", "040"],
            "registration_time": "Nov 16, 8:00 a.m.",
        },
    )
    cfg = client.get("/api/prefs").json()["config"]
    cfg["hard"].update({"credit_min": 9, "credit_max": 12})
    client.put("/api/prefs", json={"config": cfg})
    r = client.post("/api/schedules/generate", json={"k": 5}).json()
    assert r["schedules"], r["problems"]
    top = r["schedules"][0]
    assert {s["code"] for s in top["sections"]} >= {"C S 312", "GOV 310L", "E 316L"}
    assert (
        r["registration"]["registration_time"] == "Nov 16, 8:00 a.m."
        and r["registration"]["steps"][0]["order"] == 1
    )
    assert "why" in top and isinstance(top["why"], list)
    # a second call reports how the top schedule changed (here: it did not)
    assert client.post("/api/schedules/generate", json={"k": 5}).json()["change"] == [
        "The top schedule did not change."
    ]


def test_generate_reports_why_nothing_fits(client):
    client.put("/api/requirements", json={"required_courses": ["C S 312"]})
    cfg = client.get("/api/prefs").json()["config"]
    cfg["hard"].update({"days_off": ["M", "T"], "credit_min": 0})
    client.put("/api/prefs", json={"config": cfg})
    r = client.post("/api/schedules/generate", json={}).json()
    assert r["schedules"] == [] and r["problems"]


def test_propose_without_api_key_says_what_to_do(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/prefs/propose", json={"request": "no classes before 10"})
    assert r.status_code == 503 and "AI models screen" in r.json()["detail"]


def test_imports_change_signals_and_sources_page(client):
    r = client.post(
        "/api/import/ratings",
        json={"csv": "instructor,avg_rating,avg_difficulty,num_ratings\nJohn Smith,4.8,1.5,120\n"},
    ).json()
    assert r["imported"] == 1
    row = client.get("/api/courses", params={"q": "calc"}).json()["rows"][0]
    assert row["signal"]["rmp_rating"] == 4.8 and "professor ratings" in row["signal"]["signals"]
    g = client.post(
        "/api/import/grades",
        json={"csv": "dept,number,n,mean_gpa\nM,408C,200,3.6\n", "source": "test", "license_note": "unclear"},
    ).json()
    assert g["imported"] == 1
    src = client.get("/api/sources").json()
    assert src["ratings"]["matched"] == 1 and src["grades"]["sources"][0]["license_note"] == "unclear"
    assert "Syllabi" in src["missing"] and "Professor ratings" not in src["missing"]
    assert signals  # imported module used above


def test_suggestions_sorted_by_conservative_ease(client):
    client.post(
        "/api/import/grades",
        json={
            "csv": "dept,number,n,mean_gpa\nC S,312,300,3.9\nM,408C,300,2.5\n",
            "source": "t",
            "license_note": "t",
        },
    )
    s = client.get("/api/suggestions", params={"core": "020"}).json()
    assert [c["code"] for c in s["courses"]] == ["C S 312", "M 408C"]
    assert client.get("/api/suggestions", params={"core": "zzz"}).status_code == 422


def test_syllabus_login_gated_url_rejected(client):
    r = client.post(
        "/api/syllabus",
        json={"course": "C S 312", "url": "https://utdirect.utexas.edu/apps/student/coursedocs/nlogon/x"},
    )
    assert r.status_code in (422, 503) and (
        "login" in r.json()["detail"] or "ANTHROPIC" in r.json()["detail"]
    )


def test_root_explains_missing_frontend_build(tmp_path):
    c = TestClient(create_app(tmp_path / "t.sqlite", dist_dir=tmp_path / "no-such-dist"))
    r = c.get("/")
    assert r.status_code == 200 and "npm install && npm run build" in r.text


def test_root_serves_built_frontend_when_present(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    c = TestClient(create_app(tmp_path / "t.sqlite", dist_dir=dist))
    assert c.get("/").text == "<html>app</html>" and c.get("/courses").text == "<html>app</html>"


def test_preferred_courses_are_ranked_deduplicated_and_never_also_required(client):
    r = client.put(
        "/api/requirements",
        json={
            "required_courses": ["C S 312"],
            "preferred_courses": ["gov 310l", "C S 312", "M 408C", "gov 310l", "zz 1"],
        },
    ).json()
    assert r["requirements"]["preferred_courses"] == ["GOV 310L", "M 408C"]
    assert r["not_in_schedule"] == ["zz 1"]


def test_wishlist_reaches_the_schedule_and_registration_options(client):
    client.put(
        "/api/requirements",
        json={"required_courses": ["C S 312"], "preferred_courses": ["E 316L", "GOV 310L"]},
    )
    cfg = client.get("/api/prefs").json()["config"]
    cfg["hard"].update({"credit_min": 0, "credit_max": 12})
    client.put("/api/prefs", json={"config": cfg})
    r = client.post("/api/schedules/generate", json={}).json()
    top = r["schedules"][0]
    assert top["wish_included"] and set(top["wish_included"]) <= {"E 316L", "GOV 310L"}
    steps = r["registration"]["steps"]
    cs = next(s for s in steps if s["code"] == "C S 312")
    assert (
        cs["options"][0]["unique"] == cs["unique"] and len(cs["options"]) == 2
    )  # primary + the other section
    assert all({"meets", "conflicts", "status"} <= set(o) for o in cs["options"])


def _wait(c, job_id):
    import time

    for _ in range(200):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_syllabus_find_and_read_jobs_with_stand_ins(client, tmp_path):
    import httpx
    from helpers import PAGE, make_docx

    from utcoursesplus import syllabus as Y
    from utcoursesplus.fetch import Fetcher

    home = '<select id="id_department"><option value="C S">C S-Computer Sciences</option></select>'

    def handler(req):
        if "download" in req.url.path:
            return httpx.Response(200, content=make_docx("Grading: two exams worth 20% each. " * 12))
        return httpx.Response(200, text=PAGE if req.url.params.get("course_number") else home)

    st = client.app.state.st
    st.fetcher_factory = lambda: Fetcher(
        cache_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0
    )
    parsed = Y.SyllabusExtraction(exam_count=Y.QInt(value=2, quote="two exams worth 20% each"))

    class Fake:
        messages = None

        def __init__(self):
            self.messages = self

        def parse(self, **kw):
            class R:
                stop_reason = "end_turn"
                parsed_output = parsed

            return R()

    st.llm_client_factory = Fake
    j = _wait(client, client.post("/api/syllabi/find", json={"courses": ["c s 439"]}).json()["job"])
    assert j["state"] == "done", j
    docs = client.get("/api/syllabi/docs", params={"course": "C S 439"}).json()
    assert len(docs) == 4 and sum(d["recommended"] for d in docs) == 2
    pick = [d["id"] for d in docs if d["recommended"]]
    j2 = _wait(client, client.post("/api/syllabi/read", json={"doc_ids": pick}).json()["job"])
    assert j2["state"] == "done" and all(r["ok"] for r in j2["result"])
    ov = client.get("/api/syllabi/overview").json()
    c = next(x for x in ov["courses"] if x["code"] == "C S 439")
    assert len(c["syllabi"]) == 2 and c["difficulty"] is not None and c["docs"]["read"] == 2


def test_syllabus_jobs_explain_missing_login_and_key(client, tmp_path, monkeypatch):
    st = client.app.state.st
    from utcoursesplus.fetch import SessionExpired

    def no_session():
        raise SessionExpired("none")

    st.fetcher_factory = no_session
    r = client.post("/api/syllabi/find", json={"courses": ["C S 312"]})
    assert r.status_code == 409 and "uv run utcoursesplus login" in r.json()["detail"]
    assert client.post("/api/syllabi/find", json={"courses": []}).status_code == 422
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    st.llm_client_factory = __import__("utcoursesplus.llm", fromlist=["get_client"]).get_client
    assert client.post("/api/syllabi/read", json={"doc_ids": [1]}).status_code == 503


# ------------------------------------------------------------------ settings, key, models


def test_settings_save_key_hides_it_and_picks_models_per_task(client, tmp_path):
    key = "sk-ant-api03-" + "x" * 40
    r = client.put(
        "/api/settings",
        json={
            "anthropic_key": key,
            "models": {"syllabus": "claude-haiku-5-5"},
            "default_model": "claude-sonnet-5-5",
        },
    )
    assert r.status_code == 200
    v = r.json()
    assert v["key_source"] == "saved" and key not in r.text and v["key_hint"].startswith("sk-ant-")
    assert v["models"]["syllabus"] == "claude-haiku-5-5" and v["default_model"] == "claude-sonnet-5-5"
    assert (
        key not in client.get("/api/settings").text
        and client.get("/api/status").json()["llm_configured"] is True
    )
    from utcoursesplus import settings

    assert (
        settings.model_for("syllabus") == "claude-haiku-5-5"
        and settings.model_for("audit") == "claude-sonnet-5-5"
    )
    assert (tmp_path / "settings.json").stat().st_mode & 0o077 == 0  # readable only by you
    assert client.put("/api/settings", json={"clear_key": True}).json()["key_source"] is None


def test_settings_reject_things_that_are_not_keys(client):
    assert client.put("/api/settings", json={"anthropic_key": "short"}).status_code == 422
    assert (
        client.put(
            "/api/settings", json={"anthropic_key": "sk-ant- has spaces in it xxxxxxxxxxxx"}
        ).status_code
        == 422
    )


def test_saved_key_is_what_the_model_client_uses(monkeypatch):
    from utcoursesplus import llm, settings

    seen = {}

    class FakeAnthropic:
        def __init__(self, api_key=None):
            seen["key"] = api_key

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    settings.update(key="sk-ant-" + "k" * 30)
    llm.get_client()
    assert seen["key"] == "sk-ant-" + "k" * 30


def test_key_test_lists_models_and_flags_unavailable_choices(client, monkeypatch):
    import anthropic

    class M:
        def __init__(self, i):
            self.id, self.display_name = i, i.upper()

    class FakeModels:
        def list(self, limit=100):
            return [M("claude-opus-5-5"), M("claude-sonnet-5-5")]

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    client.put("/api/settings", json={"models": {"syllabus": "claude-haiku-5-5"}})
    r = client.post("/api/settings/test", json={"anthropic_key": "sk-ant-" + "z" * 30}).json()
    assert r["ok"] and [m["id"] for m in r["models"]] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert r["chosen"]["syllabus"] == {"model": "claude-haiku-5-5", "available": False}
    assert r["chosen"]["audit"]["available"] is True
    assert client.post("/api/settings/test", json={}).status_code == 422  # nothing to test


def test_key_test_explains_a_rejected_key(client, monkeypatch):
    import anthropic
    import httpx

    class Bad:
        def __init__(self, api_key=None):
            outer = self

            class Models:
                def list(self, limit=100):
                    req = httpx.Request("GET", "https://api.anthropic.com/v1/models")
                    raise anthropic.AuthenticationError(
                        "bad", response=httpx.Response(401, request=req), body=None
                    )

            outer.models = Models()

    monkeypatch.setattr(anthropic, "Anthropic", Bad)
    r = client.post("/api/settings/test", json={"anthropic_key": "sk-ant-" + "q" * 30})
    assert r.status_code == 401 and "rejected that key" in r.json()["detail"]


# ------------------------------------------------------------------ triage, pins, compare, plan map


def test_core_triage_tokens_and_pins_are_validated(client):
    r = client.put(
        "/api/requirements",
        json={
            "core_areas": ["070"],
            "preferred_courses": ["core:040", "core:070", "core:999", "E 316L"],
            "pinned_sections": {"c s 312": ["10001", "10003"], "M 408C": ["10003"]},
        },
    ).json()
    req = r["requirements"]
    assert req["preferred_courses"] == ["core:040", "E 316L"]  # 070 is already required; 999 is not an area
    assert req["pinned_sections"] == {"C S 312": ["10001"], "M 408C": ["10003"]}
    assert (
        any("10003 is not a section of c s 312" in x for x in r["not_in_schedule"])
        and "core:999" in r["not_in_schedule"]
    )


def test_add_a_specific_unique_pins_it_and_adds_its_course(client):
    r = client.post("/api/requirements/add-unique", json={"unique": "10002", "target": "like"})
    assert r.status_code == 200
    req = r.json()["requirements"]
    assert req["preferred_courses"] == ["C S 312"] and req["pinned_sections"] == {"C S 312": ["10002"]}
    client.post("/api/requirements/add-unique", json={"unique": "10001"})
    req = client.get("/api/requirements").json()
    assert (
        req["pinned_sections"]["C S 312"] == ["10002", "10001"] and req["required_courses"] == []
    )  # already on a list
    assert client.post("/api/requirements/add-unique", json={"unique": "99999"}).status_code == 404


def test_pinning_changes_what_the_schedule_contains(client):
    client.put(
        "/api/requirements", json={"required_courses": ["C S 312"], "pinned_sections": {"C S 312": ["10002"]}}
    )
    cfg = client.get("/api/prefs").json()["config"]
    cfg["hard"].update({"credit_min": 0})
    client.put("/api/prefs", json={"config": cfg})
    r = client.post("/api/schedules/generate", json={"k": 3}).json()
    assert {s["unique"] for sch in r["schedules"] for s in sch["sections"] if s["code"] == "C S 312"} == {
        "10002"
    }


def test_compare_endpoint_ranks_the_sections_of_one_course(client):
    client.put("/api/requirements", json={"required_courses": ["C S 312"]})
    cfg = client.get("/api/prefs").json()["config"]
    cfg["hard"].update({"credit_min": 0})
    client.put("/api/prefs", json={"config": cfg})
    r = client.post("/api/schedules/compare", json={"code": "c s 312"}).json()
    assert r["code"] == "C S 312" and r["in_plan_as"] == "required"
    assert [row["unique"] for row in r["rows"]] and {row["unique"] for row in r["rows"]} == {"10001", "10002"}
    assert r["rows"][0]["delta"] == 0 and all(row["schedule"] for row in r["rows"] if row["fits"])
    assert (
        client.post("/api/schedules/compare", json={"code": "c s 312", "uniques": ["10001"]}).status_code
        == 422
    )
    assert client.post("/api/schedules/compare", json={"code": "zz 1"}).status_code == 422


def test_deferral_suggestions_reach_the_api_when_nothing_fits(client):
    # 3 + 4 + 3 credit hours of requirements against a 7-hour maximum: dropping any one of them makes it possible
    client.put("/api/requirements", json={"required_courses": ["C S 312", "M 408C"], "core_areas": ["070"]})
    cfg = client.get("/api/prefs").json()["config"]
    cfg["hard"].update({"credit_min": 0, "credit_max": 7})
    client.put("/api/prefs", json={"config": cfg})
    r = client.post("/api/schedules/generate", json={}).json()
    assert r["schedules"] == [] and "at least 10 credit hours" in r["problems"][0]
    assert {(d["kind"], d["key"]) for d in r["deferrals"]} == {
        ("course", "C S 312"),
        ("course", "M 408C"),
        ("core", "070"),
    }


def test_plan_map_groups_the_plan_and_explains_what_was_left_out(client):
    client.put(
        "/api/requirements",
        json={
            "required_courses": ["C S 312"],
            "core_areas": ["070"],
            "preferred_courses": ["E 316L", "core:050"],
        },
    )
    cfg = client.get("/api/prefs").json()["config"]
    cfg["hard"].update({"credit_min": 0, "credit_max": 12})
    client.put("/api/prefs", json={"config": cfg})
    t = client.get("/api/plan/tree").json()["tree"]
    ids = [g["id"] for g in t["groups"]]
    assert ids[:2] == ["required", "core"] and "like" in ids
    req = next(g for g in t["groups"] if g["id"] == "required")["items"][0]
    assert req["code"] == "C S 312" and req["options"][0]["planned"] and len(req["options"]) == 2
    core = next(g for g in t["groups"] if g["id"] == "core")["items"][0]
    assert core["code"] == "GOV 310L" and core["area"] == "American and Texas Government"
    like = next(g for g in t["groups"] if g["id"] == "like")["items"]
    assert [i["key"] for i in like] == ["E 316L", "core:050"]  # in the student's ranking
    assert all(i["included"] or i["reason"] for i in like)


def test_explanations_use_the_wishlist_weight_when_there_is_a_wishlist(client):
    client.put(
        "/api/requirements",
        json={"required_courses": ["C S 312"], "preferred_courses": ["E 316L", "GOV 310L"]},
    )
    cfg = client.get("/api/prefs").json()["config"]
    cfg["hard"].update({"credit_min": 0, "credit_max": 12})
    client.put("/api/prefs", json={"config": cfg})
    r = client.post("/api/schedules/generate", json={"k": 5}).json()
    assert r["weights"]["wishlist"] > 0.05
    cmp = client.post(
        "/api/schedules/compare", json={"code": "C S 312", "uniques": ["10001", "10002"]}
    ).json()
    assert cmp["weights"]["wishlist"] > 0.05
    client.put("/api/requirements", json={"required_courses": ["C S 312"]})
    assert (
        client.post("/api/schedules/generate", json={"k": 5}).json()["weights"]["wishlist"] == 0
    )  # no wishlist, no weight
