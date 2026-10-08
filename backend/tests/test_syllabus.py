import pytest

from utcoursesplus import syllabus as Y
from utcoursesplus.db import connect

TEXT = (
    "Course grading: Two midterm exams worth 20% each and a final exam worth 30%. Attendance is not required "
    "but is encouraged. Late homework loses 10% per day. Expect about 6 hours of reading and homework each week. "
    "There is one term paper. " * 3
)


def ex(**kw):
    base = Y.SyllabusExtraction()
    return base.model_copy(update=kw)


def test_quote_verification_drops_unsupported_values():
    e = Y.SyllabusExtraction(
        exam_count=Y.QInt(value=2, quote="Two midterm exams worth 20% each"),
        weekly_hours=Y.QFloat(value=6, quote="about 6 hours of reading"),
        group_work=Y.QBool(value=False, quote="no group projects ever"),  # not in the text
        has_final_exam=Y.QBool(value=True, quote=None),  # no quote at all
    )
    clean, dropped = Y.verify_quotes(e, TEXT)
    assert clean.exam_count.value == 2 and clean.weekly_hours.value == 6
    assert clean.group_work.value is None and clean.has_final_exam.value is None
    assert set(dropped) == {"group_work", "has_final_exam"}


def test_quote_match_ignores_case_whitespace_and_curly_quotes():
    e = Y.SyllabusExtraction(late_policy=Y.QLate(value="penalty", quote="LATE  homework loses 10% per day"))
    assert Y.verify_quotes(e, TEXT)[0].late_policy.value == "penalty"


def test_lightness_known_values_and_renormalization():
    all_light = Y.SyllabusExtraction(
        exam_count=Y.QInt(value=0),
        exams_total_weight_pct=Y.QFloat(value=0),
        has_final_exam=Y.QBool(value=False),
        attendance=Y.QAttendance(value="none"),
        participation_graded=Y.QBool(value=False),
        late_policy=Y.QLate(value="lenient"),
        weekly_hours=Y.QFloat(value=3),
        major_projects_count=Y.QInt(value=0),
        group_work=Y.QBool(value=False),
    )
    s, cov, _ = Y.lightness(all_light)
    assert s == pytest.approx(1.0) and cov == pytest.approx(1.0)
    heavy = Y.SyllabusExtraction(
        exam_count=Y.QInt(value=5),
        exams_total_weight_pct=Y.QFloat(value=100),
        has_final_exam=Y.QBool(value=True),
        attendance=Y.QAttendance(value="mandatory"),
        participation_graded=Y.QBool(value=True),
        late_policy=Y.QLate(value="no_late_work"),
        weekly_hours=Y.QFloat(value=15),
        major_projects_count=Y.QInt(value=6),
        group_work=Y.QBool(value=True),
    )
    assert Y.lightness(heavy)[0] < 0.3
    only_exam_weight = Y.SyllabusExtraction(exams_total_weight_pct=Y.QFloat(value=70))
    s, cov, _ = Y.lightness(only_exam_weight)
    assert s == pytest.approx(0.3) and cov == pytest.approx(0.20)  # one component: renormalized to itself
    assert Y.lightness(Y.SyllabusExtraction())[0] is None


def test_more_exams_never_lighter():
    scores = [Y.lightness(Y.SyllabusExtraction(exam_count=Y.QInt(value=n)))[0] for n in range(6)]
    assert scores == sorted(scores, reverse=True)


class FakeClient:
    def __init__(self, parsed):
        self.messages = self
        self.parsed = parsed

    def parse(self, **kw):
        class R:
            stop_reason = "end_turn"
            parsed_output = self.parsed

        return R()


def test_add_syllabus_stores_verified_fields_and_gold_eval(tmp_path):
    con = connect(":memory:")
    parsed = Y.SyllabusExtraction(
        exam_count=Y.QInt(value=2, quote="Two midterm exams worth 20% each"),
        group_work=Y.QBool(value=True, quote="made up quote"),
    )
    out = Y.add_syllabus(con, "C S 429", text=TEXT, instructor="DOE, JANE", client=FakeClient(parsed))
    assert out["dropped_unverified"] == ["group_work"] and out["coverage"] == pytest.approx(0.20)
    sheet = tmp_path / "gold.csv"
    assert Y.gold_sheet(con, sheet) == 1
    rows = sheet.read_text().splitlines()
    filled = rows[0] + "\n" + rows[1].rsplit(",", 9)[0] + ",2,,,,,,,,NA\n"
    sheet.write_text(filled)
    stats = Y.gold_eval(con, sheet)
    assert stats["exam_count"] == {
        "labeled": 1,
        "correct": 1,
        "false_values": 0,
        "missed": 0,
        "accuracy": 1.0,
    }
    assert stats["group_work"]["labeled"] == 1 and stats["group_work"]["accuracy"] == 1.0  # NA and null agree
    assert stats["attendance"]["labeled"] == 0 and stats["attendance"]["accuracy"] is None


def test_login_gated_and_short_text_refused():
    con = connect(":memory:")
    with pytest.raises(ValueError, match="UT login"):
        Y.add_syllabus(con, "C S 429", url="https://utdirect.utexas.edu/apps/student/coursedocs/nlogon/x.pdf")
    with pytest.raises(ValueError, match="Not enough"):
        Y.add_syllabus(con, "C S 429", text="short", client=FakeClient(Y.SyllabusExtraction()))


def test_robots_txt_is_honored(tmp_path):
    import httpx

    from utcoursesplus.fetch import Fetcher

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, text="x")

    f = Fetcher(
        cache_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0
    )
    assert Y.robots_allows(f, "https://dept.example.edu/syllabi/cs429.pdf")
    assert not Y.robots_allows(f, "https://dept.example.edu/private/cs429.pdf")
    g = Fetcher(
        cache_dir=tmp_path / "b",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
        min_interval=0,
    )
    assert Y.robots_allows(g, "https://other.example.edu/a.pdf")
