from pathlib import Path

import httpx
import pytest
from helpers import PAGE, make_docx

from utcoursesplus import coursedocs as D
from utcoursesplus import syllabus as Y
from utcoursesplus.db import connect
from utcoursesplus.fetch import Fetcher, SessionExpired

SAMPLE = Path(__file__).parents[2] / "data" / "samples" / "syllabi_cs439.html"


def test_parse_results_reads_terms_courses_instructors_and_link_kinds():
    rows = D.parse_results(PAGE)
    assert len(rows) == 6
    r = rows[2]
    assert (r.year, r.season, r.course, r.unique) == (2026, 3, "C S 439", "55250")
    assert r.instructors == ["Ahmed Gheith"] and r.kind == "download" and r.url.endswith("/download/552509/")
    assert r.url.startswith("https://utdirect.utexas.edu/")
    assert rows[1].kind == "external" and rows[5].kind is None


def test_pick_prefers_current_instructor_then_recent_and_never_the_honors_course():
    rows = D.parse_results(PAGE)
    picks = D.pick_docs(rows, "C S 439", ["GHEITH, AHMED", "ELNOZAHY, E"], per_course=3)
    assert [p.unique for p in picks] == ["55250", "55240"]  # Gheith's newest; then the next newest recent one
    assert all(p.course == "C S 439" for p in picks)  # not 439H, not the external-only row
    assert "55230" not in [p.unique for p in picks]  # 2013 is too old while recent ones exist
    only_old = [r for r in rows if r.year < 2020]
    assert [p.unique for p in D.pick_docs(only_old, "C S 439", [])] == ["55230"]  # but better than nothing


def test_department_values_keep_the_site_padding():
    html = '<select id="id_department"><option value="">x</option><option value="E  ">E  -English</option><option value="C S">C S-Computer Sciences</option><option value="NE">NE -Nano</option></select>'
    v = D.parse_department_values(html)
    assert v["E"] == "E  " and v["C S"] == "C S" and v["NE"] == "NE"
    assert "department=E++" in D.search_url("E  ", "316L")


def test_split_course():
    assert D.split_course("c s 439") == ("C S", "439") and D.split_course("M 408C") == ("M", "408C")


LONG = "Grading: two exams worth 20% each. " * 12


def test_extract_text_from_docx_and_html_and_rejections():
    assert "two exams" in D.extract_text(make_docx(LONG))
    assert "two exams" in D.extract_text(f"<html><body><p>{LONG}</p></body></html>".encode(), "text/html")
    with pytest.raises(ValueError, match="cannot be read"):
        D.extract_text(b"\xd0\xcf\x11\xe0 old word file")
    with pytest.raises(ValueError, match="Almost no text"):
        D.extract_text(make_docx("tiny"))


class FakeClient:
    def __init__(self, parsed):
        self.messages = self
        self.parsed = parsed

    def parse(self, **kw):
        class R:
            stop_reason = "end_turn"
            parsed_output = self.parsed

        return R()


def make_fetcher(tmp_path, handler):
    return Fetcher(
        cache_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0
    )


def test_find_then_read_end_to_end_with_stand_in_site_and_model(tmp_path):
    home = '<select id="id_department"><option value="C S">C S-Computer Sciences</option></select>'
    asked = []

    def handler(req: httpx.Request):
        asked.append(str(req.url))
        if "download" in req.url.path:
            return httpx.Response(
                200, content=make_docx(LONG), headers={"content-type": "application/vnd.openxmlformats"}
            )
        if req.url.params.get("course_number"):
            return httpx.Response(200, text=PAGE)
        return httpx.Response(200, text=home)

    con = connect(":memory:")
    f = make_fetcher(tmp_path, handler)
    found = D.find_docs(con, f, {"C S 439": ["GHEITH, AHMED"]}, progress=lambda *_: None)
    assert found["C S 439"]["with_syllabus"] == 4 and found["C S 439"]["recommended"] == 2
    ids = [r["id"] for r in con.execute("SELECT id FROM syllabus_doc WHERE recommended=1 ORDER BY year DESC")]
    assert len(ids) == 2
    assert not any("download" in u for u in asked)  # nothing is downloaded until the student chooses

    parsed = Y.SyllabusExtraction(exam_count=Y.QInt(value=2, quote="two exams worth 20% each"))
    res = D.read_docs(con, f, ids[:1], client=FakeClient(parsed), progress=lambda *_: None)
    assert res[0]["ok"] and res[0]["lightness"] is not None
    assert sum("download" in u for u in asked) == 1
    st = con.execute("SELECT status FROM syllabus_doc WHERE id=?", (ids[0],)).fetchone()[0]
    assert st == "read"
    stored = con.execute("SELECT course, instructor_key, source_url FROM syllabus").fetchone()
    assert stored["course"] == "C S 439" and stored["source_url"].endswith("/download/552509/")


def test_unreadable_and_external_docs_are_reported_not_fatal(tmp_path):
    con = connect(":memory:")
    D.ensure(con)
    con.execute(
        "INSERT INTO syllabus_doc(course, term_text, year, season, instructors, url, kind, found_at) VALUES('C S 439','2026 Fall',2026,3,'X Y','https://x/ext','external','t')"
    )
    con.execute(
        "INSERT INTO syllabus_doc(course, term_text, year, season, instructors, url, kind, found_at) VALUES('C S 439','2026 Fall',2026,3,'X Y','https://utdirect.utexas.edu/apps/student/coursedocs/courses/nlogon/download/1/','download','t')"
    )
    f = make_fetcher(
        tmp_path,
        lambda r: httpx.Response(
            200, content=b"\xd0\xcf\x11\xe0 old", headers={"content-type": "application/msword"}
        ),
    )
    res = D.read_docs(con, f, [1, 2], client=FakeClient(Y.SyllabusExtraction()), progress=lambda *_: None)
    assert [r["ok"] for r in res] == [False, False]
    assert "Simple Syllabus" in res[0]["error"] and "cannot be read" in res[1]["error"]


def test_login_page_instead_of_file_means_session_expired(tmp_path):
    f = make_fetcher(
        tmp_path,
        lambda r: httpx.Response(
            200, text="<form><input name='SAMLRequest'></form>", headers={"content-type": "text/html"}
        ),
    )
    with pytest.raises(SessionExpired):
        f.get_bytes("https://utdirect.utexas.edu/apps/student/coursedocs/courses/nlogon/download/1/")


@pytest.mark.skipif(not SAMPLE.exists(), reason="local sample not present")
def test_real_saved_results_page():
    rows = D.parse_results(SAMPLE.read_text())
    assert len(rows) == 276 and {r.course for r in rows} == {"C S 439", "C S 439H"}
    assert sum(r.kind == "download" for r in rows) == 275 and sum(r.kind == "external" for r in rows) == 1
    picks = D.pick_docs(rows, "C S 439", ["GHEITH, AHMED"])
    assert picks and picks[0].year >= 2025 and any("Gheith" in n for n in picks[0].instructors)
