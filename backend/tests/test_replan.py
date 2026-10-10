from helpers import catalog, mk

from utcoursesplus import schedule as S
from utcoursesplus.db import connect
from utcoursesplus.prefs import PreferenceConfig
from utcoursesplus.replan import replan
from utcoursesplus.requirements import Requirements
from utcoursesplus.signals import SignalIndex


def go(secs, req, cfg=None, **kw):
    args = {"registered": [], "full": [], "skipped": [], "previous": []}
    args.update(kw)
    return replan(
        catalog(secs), req, cfg or PreferenceConfig(), SignalIndex(connect(":memory:")), None, **args
    )


def three():
    return [
        mk(1, "C S 312", days=("M", "W"), start=540, end=600),
        mk(2, "C S 312", days=("T", "TH"), start=540, end=600),
        mk(3, "M 408C", days=("M", "W"), start=700, end=760),
        mk(4, "E 316L", days=("T", "TH"), start=700, end=760),
    ]


def cfg(lo=0, hi=18):
    c = PreferenceConfig()
    c.hard.credit_min, c.hard.credit_max = lo, hi
    return c


def test_nothing_registered_matches_a_plain_search():
    req = Requirements(required_courses=["C S 312", "M 408C"])
    r = go(three(), req, cfg())
    assert r["status"] == "ok" and r["registered"] == []
    assert {s["code"] for s in r["registration"]["steps"]} == {"C S 312", "M 408C"}


def test_a_full_section_moves_the_plan_to_another_section_and_says_so():
    req = Requirements(required_courses=["C S 312", "M 408C"])
    first = go(three(), req, cfg())
    pick = next(s for s in first["registration"]["steps"] if s["code"] == "C S 312")["unique"]
    r = go(
        three(),
        req,
        cfg(),
        full=[pick],
        previous=[s["unique"] for s in first["registration"]["steps"]],
    )
    now = next(s for s in r["registration"]["steps"] if s["code"] == "C S 312")["unique"]
    assert now != pick
    assert any("was full" in c and pick in c for c in r["changes"])


def test_registered_sections_are_kept_and_not_listed_again():
    req = Requirements(required_courses=["C S 312", "M 408C"])
    r = go(three(), req, cfg(), registered=["2"])
    assert [x["unique"] for x in r["registered"]] == ["2"]
    assert all(s["unique"] != "2" for s in r["registration"]["steps"])
    assert {s["code"] for s in r["registration"]["steps"]} == {"M 408C"}
    assert r["schedules"][0]["credits"] == 6


def test_registered_section_fills_a_core_slot_so_it_is_not_taken_twice():
    secs = [mk(1, "GOV 310L", core=("070",)), mk(2, "GOV 312L", core=("070",), days=("T", "TH"))]
    r = go(secs, Requirements(core_areas=["070"]), cfg(), registered=["2"])
    assert r["registration"]["steps"] == [] and r["status"] == "complete"


def test_a_course_given_up_on_is_replaced_by_another_that_covers_the_area():
    secs = [mk(1, "GOV 310L", core=("070",)), mk(2, "GOV 312L", core=("070",), days=("T", "TH"))]
    r = go(secs, Requirements(core_areas=["070"]), cfg(), skipped=["GOV 310L"])
    assert [s["code"] for s in r["registration"]["steps"]] == ["GOV 312L"]


def test_when_every_section_of_a_needed_course_is_full_it_says_which_registered_course_to_drop():
    # C S 312 only meets Monday and Wednesday at 9; M 408C (registered) sits at the same time
    secs = [
        mk(1, "C S 312", days=("M", "W"), start=540, end=600),
        mk(3, "M 408C", days=("M", "W"), start=550, end=610),
        mk(4, "M 408C", days=("T", "TH"), start=550, end=610),
    ]
    req = Requirements(required_courses=["C S 312", "M 408C"])
    r = go(secs, req, cfg(), registered=["3"])
    assert r["status"] == "drop_needed"
    d = r["drops"][0]
    assert [x["unique"] for x in d["drop"]] == ["3"]
    assert {t["code"] for t in d["then_take"]} == {"C S 312", "M 408C"}
    assert all(t["unique"] != "3" for t in d["then_take"])


def test_no_way_out_is_stated_instead_of_an_empty_plan():
    secs = [mk(1, "C S 312"), mk(2, "M 408C", days=("M", "W"), start=550, end=610)]
    req = Requirements(required_courses=["C S 312", "M 408C"])
    r = go(secs, req, cfg(), registered=["2"])
    assert r["status"] == "stuck" and r["problems"]


def test_a_much_better_plan_is_offered_as_optional_not_forced():
    # registered a 9 a.m. section even though the student wants afternoons; a later one exists
    c = cfg()
    c.weights.time_of_day = 1.0
    c.time_bias = 1.0
    secs = [
        mk(1, "C S 312", days=("M", "W"), start=480, end=540),
        mk(2, "C S 312", days=("M", "W"), start=840, end=900),
    ]
    r = go(secs, Requirements(required_courses=["C S 312"]), c, registered=["1"])
    assert r["registration"]["steps"] == []
    assert r["status"] == "better_if_dropped"
    assert r["drops"][0]["drop"][0]["unique"] == "1" and r["drops"][0]["gain"] > 0


def test_fixed_sections_never_lose_to_the_search():
    secs = three()
    req = Requirements(required_courses=["C S 312", "M 408C"])
    res = S.generate(catalog(secs), req, cfg(), SignalIndex(connect(":memory:")), fixed=[secs[1]])
    assert res.schedules and all("2" in {x.unique for x in s.sections} for s in res.schedules)


def test_giving_up_on_a_required_course_drops_that_requirement_for_the_search():
    req = Requirements(required_courses=["C S 312", "M 408C"])
    r = go(three(), req, cfg(), skipped=["M 408C"])
    assert r["status"] == "ok"
    assert [s["code"] for s in r["registration"]["steps"]] == ["C S 312"]
