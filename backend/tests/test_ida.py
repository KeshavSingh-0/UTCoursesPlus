from helpers import ida_html

from utcoursesplus import ida as I


def test_ida_courses_equivalents_and_in_progress():
    r = I.parse_ida(ida_html())
    codes = {c.code for c in r.courses}
    assert {"RHE 306", "E 306", "C S 312", "C S 314", "C S 314H"} <= codes  # whitespace normalized
    assert "M 408C" not in r.completed_codes  # an F does not count as taken
    assert "E 306" in r.completed_codes  # equivalents do
    assert r.in_progress_codes == ["C S 314", "C S 314H"]
    assert (
        next(c for c in r.courses if c.code == "E 306").alias
        and next(c for c in r.courses if c.code == "C S 312").credits == 3
    )
    assert r.program == "ENTRY-LEVEL requirements for Computer Sciences"


def test_ida_remaining_core_with_hours_and_code_mapping():
    r = I.parse_ida(ida_html())
    by = {tuple(c.codes): c for c in r.core_needs}
    assert by[("070",)].lacking_hours == 6 and by[("070",)].names == ["American and Texas Government"]
    assert by[("050",)].lacking_hours == 3
    assert ("030", "093") in by  # '030 and 031/093': 031 maps to 093
    assert ("010",) not in by  # fulfilled
    assert all("42 hours" not in c.text for c in r.core_needs)  # the roll-up line is not a requirement


def test_ida_course_lists_notes_and_totals():
    r = I.parse_ida(ida_html())
    assert len(r.course_rules) == 1
    assert r.course_rules[0].segments == [
        ["C S 311", "C S 311H", "C S 313K"],
        ["C S 312", "C S 312H", "C S 307"],
    ]
    assert [n.text[:20] for n in r.notes] == [
        "3 Hrs in a different"
    ]  # prose requirements are shown, not guessed at
    assert r.totals and r.totals[0].required == 60 and r.totals[0].lacking == 43


def test_ida_output_never_contains_identity():
    import json

    s = json.dumps(I.parse_ida(ida_html()).as_dict())
    assert "Test Student" not in s and "xx00000" not in s


def test_ida_without_a_checklist_still_reads_courses():
    html = ida_html().split('<div id="categories">')[0] + "</body></html>"
    r = I.parse_ida(html)
    assert r.courses and not r.core_needs and r.warnings
