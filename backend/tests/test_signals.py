import pytest

from utcoursesplus import signals as S
from utcoursesplus.db import connect

RATINGS = """instructor,avg_rating,avg_difficulty,num_ratings,would_take_again,source_url
"Smith, John",4.5,2.0,200,90%,https://example.org/a
Jane Doe,3.0,4.5,3,40,https://example.org/b
Bad Row,9,2,5,,
,,,,
"""


def test_instructor_key_handles_both_name_orders():
    assert S.instructor_key("SMITH, JOHN Q") == S.instructor_key("John Smith") == "smith|j"
    assert S.instructor_key("O'BRIEN-LEE, ANN") == "obrienlee|a"


def test_ratings_import_validates_rows():
    con = connect(":memory:")
    r = S.import_ratings_csv(con, RATINGS)
    assert r["imported"] == 2 and len(r["rejected"]) == 2
    row = con.execute("SELECT would_take_again FROM rating WHERE instructor='Smith, John'").fetchone()
    assert row[0] == pytest.approx(0.9)


def test_grades_import_counts_and_aggregates():
    con = connect(":memory:")
    csv_text = 'dept,number,instructor,term,A,A-,B,F,W\nC S,312,"DOE, JANE",2025F,50,10,40,0,10\nC S,312,,2025F,,,,,\n'
    r = S.import_grades_csv(con, csv_text, "test file", "unclear")
    assert r["imported"] == 1 and len(r["rejected"]) == 1
    row = con.execute("SELECT n_graded, mean_gpa, a_n, drop_n FROM grade").fetchone()
    assert (
        row[0] == 100
        and row[1] == pytest.approx((50 * 4 + 10 * 3.67 + 40 * 3) / 100)
        and row[2] == 60
        and row[3] == 10
    )
    agg = S.import_grades_csv(
        con, "dept,number,n,mean_gpa,a_rate,drop_rate\nM,408C,300,2.9,0.2,0.1\n", "agg", "n/a"
    )
    assert agg["imported"] == 1
    assert con.execute("SELECT license_note FROM grade_source").fetchall()[0][0] == "unclear"


def test_posterior_shrinks_toward_prior_and_interval_narrows_with_data():
    few = S.posterior([(2.0, 0.5)])
    many = S.posterior([(2.0, 50.0)])
    assert 0 < few[0] < 1.0 < many[0] < 2.0  # small samples are pulled toward 0
    assert many[1] < few[1] < 1.0  # more data, narrower
    assert S.posterior([]) == (0.0, 1.0)  # no data: prior with full width


def test_z_to_ease_monotone_and_interval_ordered():
    e, lo, hi = S.z_to_ease(1.0, 0.5)
    assert lo < e < hi and e < 0.5
    assert S.z_to_ease(-1.0, 0.5)[0] > 0.5


def build(con):
    S.import_ratings_csv(con, RATINGS)
    S.import_grades_csv(
        con,
        "dept,number,instructor,n,mean_gpa,a_rate,drop_rate\n"
        'C S,312,"SMITH, JOHN",120,3.7,0.6,0.02\nC S,429,,400,2.7,0.15,0.12\nM,408C,,400,2.9,0.2,0.1\n',
        "t",
        "t",
    )
    return S.SignalIndex(con, {"smith|j": {"C S"}, "doe|j": {"C S"}})


def test_easy_course_beats_hard_course_and_is_labeled_with_sources():
    con = connect(":memory:")
    idx = build(con)
    easy = idx.estimate("C S 312", ["SMITH, JOHN"])
    hard = idx.estimate("C S 429", ["SOMEONE, ELSE"])
    assert easy.ease > hard.ease
    assert easy.confidence in ("Medium", "High") and set(easy.signals) == {"grades", "professor ratings"}
    assert hard.signals == ["grades"]


def test_missing_signals_lower_rank_but_do_not_hide_course():
    con = connect(":memory:")
    idx = build(con)
    unknown = idx.estimate("H E 306", ["NOBODY, X"])
    assert unknown.ease is None and unknown.confidence == "None" and unknown.signals == []
    assert unknown.rank_ease < 0.5  # conservative
    known_mid = idx.estimate("M 408C", [])
    assert known_mid.rank_ease > unknown.rank_ease or known_mid.ease < 0.5


def test_few_ratings_are_not_trusted_blindly():
    con = connect(":memory:")
    S.import_ratings_csv(
        con,
        "instructor,avg_rating,avg_difficulty,num_ratings\nA Few,3,4.5,3\nB Many,3,4.5,300\nC Other,3,3,100\n",
    )
    idx = S.SignalIndex(con, {"few|a": {"X"}, "many|b": {"X"}, "other|c": {"X"}})
    few, many = idx.estimate("X 1", ["FEW, A"]), idx.estimate("X 1", ["MANY, B"])
    assert few.rmp_n == 3 and many.rmp_n == 300
    assert few.ease > many.ease  # same raw difficulty; the small sample is pulled toward the department
    assert (few.ease_hi - few.ease_lo) > 2 * (many.ease_hi - many.ease_lo)  # and the interval says so


def test_ambiguous_instructor_name_is_not_matched():
    con = connect(":memory:")
    S.import_ratings_csv(
        con, "instructor,avg_rating,avg_difficulty,num_ratings\nJohn Smith,5,1,100\nJane Smith,1,5,100\n"
    )
    # both are 'smith|j'
    idx = S.SignalIndex(con)
    assert idx.estimate("X 1", ["SMITH, JOHN"]).rmp_rating is None


def test_syllabus_lightness_blends_with_difficulty_and_renormalizes():
    con = connect(":memory:")
    con.execute(
        "CREATE TABLE syllabus(id INTEGER PRIMARY KEY, course TEXT, instructor_key TEXT, lightness REAL, coverage REAL)"
    )
    con.execute(
        "INSERT INTO syllabus(course, instructor_key, lightness, coverage) VALUES('C S 429', NULL, 0.9, 1.0)"
    )
    idx = build(con)
    s = idx.estimate("C S 429", [])
    assert s.lightness == 0.9 and "syllabus" in s.signals
    assert min(s.ease, 0.9) <= s.ease_score <= max(s.ease, 0.9)
    only_syl = idx.estimate("Z 100", [])
    assert only_syl.ease_score is None
    con.execute(
        "INSERT INTO syllabus(course, instructor_key, lightness, coverage) VALUES('Z 100', NULL, 0.2, 0.5)"
    )
    idx2 = S.SignalIndex(con)
    assert idx2.estimate("Z 100", []).ease_score == pytest.approx(
        0.2
    )  # only signal: weight renormalized to 1


def test_instructors_own_syllabus_beats_course_average_and_several_are_averaged():
    con = connect(":memory:")
    con.execute(
        "CREATE TABLE syllabus(id INTEGER PRIMARY KEY, course TEXT, instructor_key TEXT, lightness REAL, coverage REAL)"
    )
    for key, light in [
        ("doe|j", 0.8),
        ("doe|j", 0.6),
        ("roe|r", 0.2),
        ("doe|j", 0.1),
    ]:  # newest first by id order
        con.execute(
            "INSERT INTO syllabus(course, instructor_key, lightness, coverage) VALUES('C S 429', ?, ?, 1.0)",
            (key, light),
        )
    idx = S.SignalIndex(con)
    mine = idx.estimate("C S 429", ["DOE, JANE"])
    assert mine.lightness_scope == "instructor" and mine.lightness == pytest.approx(
        (0.1 + 0.6) / 2
    )  # two newest rows
    other = idx.estimate("C S 429", ["SMITH, SAM"])
    assert other.lightness_scope == "course" and other.lightness is not None
    assert other.rank_lightness <= other.lightness  # course-level evidence is trusted a little less
