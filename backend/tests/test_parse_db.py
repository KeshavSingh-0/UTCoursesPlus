import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from utcoursesplus import crawl, quality
from utcoursesplus.db import connect, upsert_section
from utcoursesplus.importers import import_json
from utcoursesplus.models import Section
from utcoursesplus.parse import parse_results

FIX = Path(__file__).parent / "fixtures" / "results_sample.html"
URL = "https://utdirect.utexas.edu/apps/registrar/course_schedule/20272/results/?ccyys=20272&fos_fl=C+S&level=L"
NOW = datetime(2026, 10, 8, tzinfo=UTC)


def parsed():
    return parse_results(FIX.read_text(), URL, NOW, term="20272", level="L")


def test_parse_sections_and_failures():
    p = parsed()
    assert [s.unique for s in p.sections] == ["10001", "10003"]
    assert len(p.failures) == 1 and "10002" in p.failures[0]
    assert p.next_url.endswith("next_unique=99999") and p.next_url.startswith(
        "https://utdirect"
    )


def test_first_section_fields():
    s = parsed().sections[0]
    assert (s.course.dept, s.course.number, s.course.credit_hours) == ("C S", "312", 3)
    assert s.status == "waitlisted" and s.reserved
    assert [i.name for i in s.instructors] == ["DOE, JANE", "ROE, RICHARD"]
    assert len(s.meetings) == 2 and s.meetings[0].days == ["M", "W", "F"]
    assert (s.meetings[0].building, s.meetings[0].room) == ("GDC", "2.216")
    assert s.meetings[1].building is None
    assert {(t.kind, t.code) for t in s.tags} == {("flag", "QR"), ("core", "020")}


def test_db_roundtrip_and_tag_union():
    con = connect(":memory:")
    s = parsed().sections[0]
    upsert_section(con, s)
    other = s.model_copy(
        update={"tags": [], "level": None}
    )  # e.g. seen again by a core search
    upsert_section(con, other)
    n_tags = con.execute("SELECT COUNT(*) FROM section_tag").fetchone()[0]
    assert n_tags == 2
    assert (
        con.execute("SELECT level FROM section").fetchone()[0] == "L"
    )  # level not erased


def test_conflicting_course_is_recorded():
    con = connect(":memory:")
    s = parsed().sections[0]
    upsert_section(con, s)
    upsert_section(
        con,
        s.model_copy(update={"course": s.course.model_copy(update={"number": "313"})}),
    )
    assert con.execute("SELECT COUNT(*) FROM parse_failure").fetchone()[0] == 1


def test_quality_report():
    con = connect(":memory:")
    for s in parsed().sections:
        upsert_section(con, s)
    r = quality.report(con)
    assert r["sections"] == 2 and r["sections_missing_times"] == 0
    assert r["by_core_area"]["Mathematics"] == 1


def test_json_importer_rejects_bad_input(tmp_path):
    con = connect(":memory:")
    good = parsed().sections[0].model_dump(mode="json")
    p = tmp_path / "s.json"
    p.write_text(json.dumps([good]))
    assert import_json(con, p) == 1
    bad = dict(good, unique="12", surprise=1)
    p.write_text(json.dumps([bad]))
    with pytest.raises(ValidationError):
        import_json(con, p)
    with pytest.raises(ValidationError):
        Section.model_validate(bad)


def test_plan_covers_every_department_level_and_core_area():
    depts = [("C S", "Computer Science"), ("M", "Mathematics")]
    urls = crawl.plan(depts)
    assert len(urls) == 10 + 2 * 3
    assert any("core_code=093" in u for u in urls) and any(
        "fos_fl=M&level=G" in u for u in urls
    )


def test_parse_departments_from_homepage_sample():
    home = Path(__file__).parents[2] / "data" / "samples" / "homepage.html"
    if not home.exists():
        pytest.skip("local sample not present")
    d = crawl.parse_departments(home.read_text())
    assert len(d) == 229 and ("C S", "Computer Science") in d


def test_unknown_core_title_is_kept_as_unmapped_and_flags_keep_titles():
    from selectolax.lexbor import LexborHTMLParser

    from utcoursesplus.parse import _parse_tags

    td = LexborHTMLParser(
        '<table><tr><td><ul class="core">'
        '<li class="X" title="Foo Bar core curriculum requirement">Foo Bar</li>'
        '<li class="WR" title="Writing flag">Writing</li>'
        '<li class="N" title="x">Natural Science &amp; Technology, Part I</li>'
        "</ul></td></tr></table>"
    ).css_first("td")
    tags = {(t.kind, t.code, t.label) for t in _parse_tags(td, None)}
    assert ("core", "unmapped", "Foo Bar") in tags
    assert ("flag", "WR", "Writing") in tags
    assert ("core", "030", "Natural Science & Technology, Part I") in tags


def test_continuation_row_adds_meeting_and_instructor():
    html = """<table class="results"><tbody>
    <tr><td class="course_header"><h2>C S  429 SOFTWARE ENGINEERING</h2></td></tr>
    <tr><td data-th="Unique"><a>11111</a></td><td data-th="Days"><span>MW</span></td>
    <td data-th="Hour"><span>9:00 a.m.-10:00 a.m.</span></td><td data-th="Room"><span>GDC 1.304</span></td>
    <td data-th="Instructor"><span>A, B</span></td><td data-th="Status">open</td></tr>
    <tr><td data-th="Unique"></td><td data-th="Days"><span>F</span></td>
    <td data-th="Hour"><span>9:00 a.m.-10:00 a.m.</span></td><td data-th="Room"><span>GDC 1.304</span></td>
    <td data-th="Instructor"><span>C, D</span></td></tr></tbody></table>"""
    p = parse_results(html, URL, NOW, term="20272")
    assert len(p.sections) == 1
    assert [m.days for m in p.sections[0].meetings] == [["M", "W"], ["F"]]
    assert [i.name for i in p.sections[0].instructors] == ["A, B", "C, D"]


def test_reparse_cache_rebuilds_without_requests(tmp_path):
    import json

    from utcoursesplus.rebuild import reparse_cache

    (tmp_path / "a.html").write_text(FIX.read_text())
    (tmp_path / "a.json").write_text(
        json.dumps({"url": URL, "fetched_at": NOW.isoformat()})
    )
    con = connect(":memory:")
    assert reparse_cache(con, tmp_path, progress=lambda *_: None) == 2
    assert reparse_cache(con, tmp_path, progress=lambda *_: None) == 2  # idempotent
    assert con.execute("SELECT COUNT(*) FROM section").fetchone()[0] == 2
    assert con.execute("SELECT level FROM section LIMIT 1").fetchone()[0] == "L"
