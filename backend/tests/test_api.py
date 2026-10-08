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
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


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
