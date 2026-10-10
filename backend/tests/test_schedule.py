import itertools

import pytest
from helpers import catalog, mk
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from utcoursesplus import schedule as S
from utcoursesplus.db import connect
from utcoursesplus.prefs import PreferenceConfig
from utcoursesplus.requirements import Requirements
from utcoursesplus.signals import SignalIndex


def idx():
    return SignalIndex(connect(":memory:"))


def run(secs, req=None, cfg=None, k=10):
    return S.generate(catalog(secs), req or Requirements(), cfg or PreferenceConfig(), idx(), k=k)


# ------------------------------------------------------------------ conflict detection


def test_overlap_rules():
    a = mk(1, days=("M", "W"), start=540, end=630)
    assert S.meets_overlap(a, mk(2, days=("W",), start=600, end=660))  # overlaps Wednesday
    assert not S.meets_overlap(a, mk(3, days=("W",), start=630, end=700))  # back to back is fine
    assert not S.meets_overlap(a, mk(4, days=("T", "TH"), start=540, end=630))  # different days
    assert not S.meets_overlap(a, mk(5, start=None))  # no meeting time never conflicts
    assert S.has_conflict([a, mk(6, days=("M",), start=540, end=541)])


def test_thursday_does_not_clash_with_tuesday():
    assert not S.meets_overlap(mk(1, days=("T",)), mk(2, days=("TH",)))


meeting = st.tuples(
    st.lists(st.sampled_from(["M", "T", "W", "TH", "F"]), min_size=1, max_size=3, unique=True),
    st.integers(8 * 60, 18 * 60),
    st.integers(30, 120),
)


@st.composite
def catalogs(draw):
    n_courses = draw(st.integers(2, 4))
    secs, uid = [], 1000
    for c in range(n_courses):
        for _ in range(draw(st.integers(1, 4))):
            days, start, length = draw(meeting)
            secs.append(
                mk(
                    uid,
                    code=f"C S {300 + c}",
                    days=tuple(days),
                    start=start,
                    end=start + length,
                    status=draw(st.sampled_from(["open", "closed", "waitlisted"])),
                )
            )
            uid += 1
    return secs, n_courses


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(catalogs(), st.booleans())
def test_no_generated_schedule_has_a_time_conflict(data, tight):
    secs, n = data
    req = Requirements(required_courses=[f"C S {300 + c}" for c in range(n)])
    cfg = PreferenceConfig.model_validate(
        {"hard": {"credit_min": 0, "credit_max": 18, "days_off": ["F"] if tight else []}}
    )
    res = S.generate(catalog(secs), req, cfg, idx(), k=20)
    for sch in res.pool:
        assert not S.has_conflict(sch.sections)
        assert len({s.code for s in sch.sections}) == len(sch.sections)
        assert sch.credits <= cfg.hard.credit_max
        if tight:
            assert all("F" not in m.days for s in sch.sections for m in s.timed_meets)


def test_generator_matches_brute_force_on_a_small_case():
    secs = [
        mk(1, "C S 312", days=("M", "W"), start=540, end=600),
        mk(2, "C S 312", days=("T", "TH"), start=540, end=600),
        mk(3, "M 408C", days=("M", "W"), start=570, end=630),
        mk(4, "M 408C", days=("T", "TH"), start=600, end=660),
        mk(5, "E 316", days=("M", "W"), start=700, end=760),
    ]
    req = Requirements(required_courses=["C S 312", "M 408C", "E 316"])
    cfg = PreferenceConfig.model_validate({"hard": {"credit_min": 0}})
    res = run(secs, req, cfg, k=50)
    by = {c: [s for s in secs if s.code == c] for c in req.required_courses}
    valid = [combo for combo in itertools.product(*by.values()) if not S.has_conflict(list(combo))]
    assert {frozenset(s.unique for s in sch.sections) for sch in res.pool} == {
        frozenset(s.unique for s in c) for c in valid
    }


# ------------------------------------------------------------------ hard constraints


def test_hard_constraints_filter():
    cfg = PreferenceConfig.model_validate(
        {
            "hard": {
                "earliest_start_min": 600,
                "days_off": ["F"],
                "excluded_sections": ["00009"],
                "excluded_instructors": ["Bad Prof"],
                "excluded_times": [{"days": ["T"], "start_min": 700, "end_min": 800}],
            }
        }
    )
    assert not S.passes_hard(mk(1, start=540, end=600), cfg)
    assert not S.passes_hard(mk(2, days=("F",), start=700, end=760), cfg)
    assert not S.passes_hard(mk("00009", start=700, end=760), cfg)
    assert not S.passes_hard(mk(3, start=700, end=760, inst=("PROF, BAD",)), cfg)
    assert not S.passes_hard(mk(4, days=("T",), start=750, end=850), cfg)
    assert not S.passes_hard(mk(5, start=700, end=760, status="cancelled"), cfg)
    assert S.passes_hard(mk(6, start=700, end=760), cfg)
    assert S.passes_hard(mk(7, start=None), cfg)  # online without a time passes


def test_credit_range_respected_and_electives_fill_to_minimum():
    secs = [mk(1, "C S 312", days=("M",), start=540, end=600)]
    for i in range(6):
        secs.append(mk(100 + i, f"E 31{i}", days=("T", "TH"), start=540 + 70 * i, end=600 + 70 * i))
    req = Requirements(required_courses=["C S 312"])
    res = run(secs, req, PreferenceConfig.model_validate({"hard": {"credit_min": 12, "credit_max": 12}}))
    assert res.schedules and all(s.credits == 12 for s in res.schedules)
    assert all(len(s.sections) == 4 for s in res.schedules)


def test_unsatisfiable_reports_why_instead_of_empty():
    res = run([mk(1, "C S 312")], Requirements(required_courses=["C S 429"]))
    assert not res.schedules and any("C S 429" in p for p in res.problems)
    res2 = run(
        [mk(1, "C S 312", days=("F",))],
        Requirements(required_courses=["C S 312"]),
        PreferenceConfig.model_validate({"hard": {"days_off": ["F"], "credit_min": 0}}),
    )
    assert not res2.schedules and any("break a hard constraint" in p for p in res2.problems)


def test_core_area_slot_uses_tagged_sections_and_not_a_required_course_twice():
    secs = [
        mk(1, "C S 312", core=("020",)),
        mk(2, "M 408C", days=("T", "TH"), core=("020",)),
        mk(3, "GOV 310L", days=("T", "TH"), start=700, end=760, core=("070",)),
    ]
    req = Requirements(required_courses=["C S 312"], core_areas=["020", "070"])
    res = run(secs, req, PreferenceConfig.model_validate({"hard": {"credit_min": 0}}))
    assert res.schedules
    top = {s.code for s in res.schedules[0].sections}
    assert top == {"C S 312", "M 408C", "GOV 310L"}


# ------------------------------------------------------------------ scoring


def test_preferences_change_the_winner():
    early = mk(1, "C S 312", days=("M", "W"), start=480, end=540)
    late = mk(2, "C S 312", days=("M", "W"), start=840, end=900)
    req = Requirements(required_courses=["C S 312"])
    base = {"hard": {"credit_min": 0}}
    morning = run(
        [early, late],
        req,
        PreferenceConfig.model_validate({**base, "time_bias": -1, "weights": {"time_of_day": 1}}),
    )
    afternoon = run(
        [early, late],
        req,
        PreferenceConfig.model_validate({**base, "time_bias": 1, "weights": {"time_of_day": 1}}),
    )
    assert morning.schedules[0].sections[0].unique == "1" and afternoon.schedules[0].sections[0].unique == "2"


def test_open_section_beats_closed_when_seats_matter():
    res = run(
        [mk(1, status="closed"), mk(2, status="open", days=("T", "TH"))],
        Requirements(required_courses=["C S 312"]),
        PreferenceConfig.model_validate({"hard": {"credit_min": 0}, "weights": {"seat_availability": 1}}),
    )
    assert [s.unique for s in res.schedules[0].sections] == ["2"]


def test_utility_bounded_and_sorted():
    secs = [mk(i, "C S 312", days=("M", "W"), start=480 + 60 * i, end=540 + 60 * i) for i in range(5)]
    res = run(
        secs,
        Requirements(required_courses=["C S 312"]),
        PreferenceConfig.model_validate({"hard": {"credit_min": 0}}),
    )
    us = [s.utility for s in res.schedules]
    assert us == sorted(us, reverse=True) and all(0 <= u <= 1 for u in us)


def test_compactness_prefers_fewer_days():
    a = [
        mk(1, "C S 312", days=("M", "W"), start=540, end=600),
        mk(2, "M 408C", days=("M", "W"), start=700, end=760),
    ]
    b = [
        mk(3, "C S 312", days=("T", "TH"), start=540, end=600),
        mk(4, "M 408C", days=("F",), start=700, end=760),
    ]
    sc = S.Scorer(PreferenceConfig(), idx())
    assert sc.schedule_features(a)["compactness"] > sc.schedule_features(b)["compactness"]


def test_walking_feature_dropped_without_coordinates_and_used_with_them():
    from utcoursesplus.buildings import Buildings

    secs = [
        mk(1, "C S 312", days=("M",), start=540, end=600, building="GDC"),
        mk(2, "M 408C", days=("M",), start=610, end=670, building="PMA"),
    ]
    off = S.Scorer(PreferenceConfig(), idx())
    assert off.schedule_features(secs)["walking"] is None and off.weights()["walking"] == 0
    on = S.Scorer(
        PreferenceConfig(), idx(), Buildings({"GDC": (30.2863, -97.7365), "PMA": (30.2901, -97.7366)})
    )
    far = on.schedule_features(secs)["walking"]
    near = S.Scorer(
        PreferenceConfig(), idx(), Buildings({"GDC": (30.2863, -97.7365), "PMA": (30.2864, -97.7365)})
    ).schedule_features(secs)["walking"]
    assert 0 < far < near <= 1


def test_max_gap_constraint():
    secs = [
        mk(1, "C S 312", days=("M",), start=540, end=600),
        mk(2, "M 408C", days=("M",), start=840, end=900),
    ]
    req = Requirements(required_courses=["C S 312", "M 408C"])
    free = run(secs, req, PreferenceConfig.model_validate({"hard": {"credit_min": 0}}))
    tight = run(secs, req, PreferenceConfig.model_validate({"hard": {"credit_min": 0, "max_gap_min": 120}}))
    assert free.schedules and not tight.schedules


# ------------------------------------------------------------------ explanations, backups, registration


def test_explanation_names_features_and_sections():
    early = mk(1, "C S 312", days=("M", "W"), start=480, end=540)
    late = mk(2, "C S 312", days=("T", "TH"), start=840, end=900)
    cfg = PreferenceConfig.model_validate(
        {"hard": {"credit_min": 0}, "time_bias": 1, "weights": {"time_of_day": 1}}
    )
    res = run([early, late], Requirements(required_courses=["C S 312"]), cfg)
    lines = S.explain_vs(res.pool[0], res.pool[1], S.Scorer(cfg, idx()).weights())
    assert any("Time-of-day fit is higher" in ln for ln in lines) and any(
        "Sections that differ" in ln for ln in lines
    )
    assert S.explain_vs(res.schedules[0], None, {})[0].startswith("This is the only")


def test_backups_share_as_few_sections_as_possible():
    secs = []
    for c, code in enumerate(["C S 312", "M 408C", "E 316"]):
        for j in range(3):
            secs.append(
                mk(
                    10 * c + j,
                    code,
                    days=("M", "W", "F")[j : j + 1] or ("M",),
                    start=480 + 200 * c + 5 * j,
                    end=540 + 200 * c + 5 * j,
                )
            )
    res = run(
        secs,
        Requirements(required_courses=["C S 312", "M 408C", "E 316"]),
        PreferenceConfig.model_validate({"hard": {"credit_min": 0}}),
        k=50,
    )
    top = res.schedules[0]
    alts = S.backups(res.pool, top, 3)
    assert len(alts) == 3
    top_set = {s.unique for s in top.sections}
    assert max(len(top_set & {s.unique for s in a.sections}) for a in alts) <= 1


def test_registration_plan_orders_scarcest_first_with_fallbacks():
    scarce = mk(1, "C S 312", status="waitlisted", days=("M", "W"), start=540, end=600)
    scarce_alt = mk(2, "C S 312", status="open", days=("T", "TH"), start=540, end=600)
    easy = mk(3, "M 408C", status="open", days=("M", "W"), start=700, end=760)
    easy_alt = mk(4, "M 408C", status="open", days=("M", "W"), start=800, end=860)
    cat = catalog([scarce, scarce_alt, easy, easy_alt])
    sch = S.Schedule([scarce, easy], ["a", "b"], 6, 0.5, {}, {})
    req = Requirements(required_courses=["C S 312", "M 408C"], registration_time="Nov 16, 8:00 a.m.")
    plan = S.registration_plan(cat, sch, req, PreferenceConfig())
    assert plan["steps"][0]["code"] == "C S 312" and plan["steps"][0]["fallback"]["unique"] == "2"
    assert plan["registration_time"] == "Nov 16, 8:00 a.m." and "not a probability" in plan["label"]
    assert plan["steps"][1]["fallback"]["unique"] == "4"


def test_describe_change():
    a = S.Schedule([mk(1, "C S 312")], ["x"], 3, 0.5, {}, {})
    b = S.Schedule([mk(2, "C S 312", days=("T",))], ["x"], 3, 0.5, {}, {})
    assert S.describe_change(a, a) == ["The top schedule did not change."]
    assert len(S.describe_change(a, b)) == 2


@pytest.mark.parametrize("n", [3])
def test_generation_is_fast_enough_on_a_realistic_pool(n):
    import time

    secs, uid = [], 0
    for c in range(8):
        for j in range(8):
            uid += 1
            secs.append(
                mk(
                    uid,
                    f"X {300 + c}",
                    days=[("M", "W"), ("T", "TH"), ("M", "W", "F")][j % 3],
                    start=480 + 60 * (j % 8),
                    end=540 + 60 * (j % 8),
                )
            )
    req = Requirements(required_courses=[f"X {300 + c}" for c in range(5)], core_areas=[])
    t = time.time()
    res = S.generate(catalog(secs), req, PreferenceConfig.model_validate({"hard": {"credit_min": 0}}), idx())
    assert res.schedules and time.time() - t < 20


def test_requirements_that_exceed_the_credit_maximum_say_so():
    secs = [mk(1, "C S 312"), mk(2, "M 408C", days=("T", "TH"), credits=4)]
    res = run(
        secs,
        Requirements(required_courses=["C S 312", "M 408C"]),
        PreferenceConfig.model_validate({"hard": {"credit_min": 0, "credit_max": 6}}),
    )
    assert not res.schedules and "at least 7 credit hours" in res.problems[0]


def test_ranked_list_has_one_schedule_per_course_set_but_pool_keeps_alternatives():
    secs = [
        mk(1, "C S 312", days=("M", "W"), start=540, end=600),
        mk(2, "C S 312", days=("M", "W"), start=545, end=605),
        mk(3, "M 408C", days=("T", "TH"), start=540, end=600),
    ]
    res = run(
        secs,
        Requirements(required_courses=["C S 312", "M 408C"]),
        PreferenceConfig.model_validate({"hard": {"credit_min": 0}}),
    )
    assert len(res.schedules) == 1 and len(res.pool) == 2


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(catalogs(), st.integers(1, 4))
def test_small_result_pool_returns_the_same_top_as_exhaustive_search(data, pool_size):
    """Regression: the optimistic bound was scaled down, so once the pool was full the search pruned
    branches that could still enter the top results."""
    secs, n = data
    req = Requirements(required_courses=[f"C S {300 + c}" for c in range(n)])
    cfg = PreferenceConfig.model_validate({"hard": {"credit_min": 0}, "time_bias": -0.5})
    original = S.POOL_SIZE
    try:
        S.POOL_SIZE = 10_000
        full = S.generate(catalog(secs), req, cfg, idx(), k=pool_size)
        S.POOL_SIZE = pool_size
        small = S.generate(catalog(secs), req, cfg, idx(), k=pool_size)
    finally:
        S.POOL_SIZE = original
    top = lambda r: [round(x.utility, 9) for x in r.pool][:pool_size]
    assert top(small) == top(full)


def test_like_to_take_courses_are_optional_and_rank_order_breaks_conflicts():
    must = mk(1, "C S 312", days=("M", "W"), start=540, end=600)
    first = mk(2, "ART 301", days=("T", "TH"), start=540, end=600)
    second = mk(3, "PHL 301", days=("T", "TH"), start=550, end=610)  # clashes with the first choice
    req = Requirements(required_courses=["C S 312"], preferred_courses=["ART 301", "PHL 301"])
    cfg = PreferenceConfig.model_validate(
        {"hard": {"credit_min": 0, "credit_max": 18}, "weights": {"wishlist": 1}}
    )
    res = run([must, first, second], req, cfg)
    top = res.schedules[0]
    assert {s.code for s in top.sections} == {"C S 312", "ART 301"} and top.wish_included == ["ART 301"]
    req2 = Requirements(required_courses=["C S 312"], preferred_courses=["PHL 301", "ART 301"])
    assert {s.code for s in run([must, first, second], req2, cfg).schedules[0].sections} == {
        "C S 312",
        "PHL 301",
    }


def test_like_to_take_skipped_when_it_would_break_the_credit_maximum():
    secs = [mk(1, "C S 312"), mk(2, "M 408C", days=("T", "TH"), credits=4), mk(3, "ART 301", days=("F",))]
    req = Requirements(required_courses=["C S 312"], preferred_courses=["M 408C", "ART 301"])
    cfg = PreferenceConfig.model_validate(
        {"hard": {"credit_min": 0, "credit_max": 6}, "weights": {"wishlist": 1}}
    )
    top = run(secs, req, cfg).schedules[0]
    assert top.credits <= 6 and top.wish_included == [
        "ART 301"
    ]  # the top-ranked 4-credit course does not fit


def test_wish_course_with_no_eligible_section_is_reported_not_fatal():
    req = Requirements(required_courses=["C S 312"], preferred_courses=["Z 999"])
    res = run([mk(1, "C S 312")], req, PreferenceConfig.model_validate({"hard": {"credit_min": 0}}))
    assert res.schedules and any("Z 999" in n for n in res.notes)


def test_interchangeable_elective_slots_do_not_repeat_the_same_schedule():
    secs = [mk(1, "C S 312", days=("M",), start=540, end=600)]
    for i in range(5):
        secs.append(mk(100 + i, f"E 31{i}", days=("T", "TH"), start=480 + 70 * i, end=540 + 70 * i))
    req = Requirements(required_courses=["C S 312"])
    cfg = PreferenceConfig.model_validate({"hard": {"credit_min": 9, "credit_max": 9}})
    res = run(secs, req, cfg, k=50)
    sets = [frozenset(s.unique for s in sch.sections) for sch in res.pool]
    assert len(sets) == len(set(sets)) == 10  # choose 2 of 5 electives, once each
    assert res.nodes < 200


# ------------------------------------------------------------------ pinned sections, Core triage, deferrals, comparison


def test_pinned_sections_restrict_a_course_to_the_uniques_you_accept():
    a = mk("00001", "C S 312", days=("M", "W"), start=540, end=600)
    b = mk("00002", "C S 312", days=("T", "TH"), start=540, end=600)
    c = mk("00003", "C S 312", days=("F",), start=540, end=600)
    req = Requirements(required_courses=["C S 312"], pinned_sections={"C S 312": ["00002", "00003"]})
    res = run([a, b, c], req, PreferenceConfig.model_validate({"hard": {"credit_min": 0}}), k=10)
    assert {s.sections[0].unique for s in res.pool} == {"00002", "00003"}
    one = Requirements(required_courses=["C S 312"], pinned_sections={"C S 312": ["00001"]})
    assert [
        s.sections[0].unique
        for s in run([a, b, c], one, PreferenceConfig.model_validate({"hard": {"credit_min": 0}})).pool
    ] == ["00001"]


def test_pins_that_cannot_be_satisfied_are_explained():
    a = mk("00001", "C S 312", days=("F",), start=540, end=600)
    req = Requirements(required_courses=["C S 312"], pinned_sections={"C S 312": ["00001"]})
    res = run([a], req, PreferenceConfig.model_validate({"hard": {"credit_min": 0, "days_off": ["F"]}}))
    assert not res.schedules and any("you pinned (00001)" in p for p in res.problems)


def test_core_area_can_be_like_to_take_instead_of_required():
    must = mk(1, "C S 312", days=("M", "W"), start=540, end=600)
    gov = mk(2, "GOV 310L", days=("T", "TH"), start=540, end=600, core=("070",))
    clash = mk(3, "HIS 315K", days=("M", "W"), start=550, end=610, core=("060",))
    req = Requirements(required_courses=["C S 312"], preferred_courses=["core:060", "core:070"])
    cfg = PreferenceConfig.model_validate({"hard": {"credit_min": 0}, "weights": {"wishlist": 1}})
    top = run([must, gov, clash], req, cfg).schedules[0]
    assert {s.code for s in top.sections} == {
        "C S 312",
        "GOV 310L",
    }  # History clashes with the required course
    assert top.wish_included == ["core:070"]
    only_req = run([must, clash], Requirements(required_courses=["C S 312"], core_areas=["060"]), cfg)
    assert not only_req.schedules  # the same area as a hard requirement leaves nothing


def test_when_nothing_fits_the_search_names_what_to_defer():
    cs = mk(1, "C S 312", days=("M", "W"), start=540, end=600)
    m = mk(2, "M 408C", days=("M", "W"), start=550, end=610)
    gov = mk(3, "GOV 310L", days=("T", "TH"), start=540, end=600, core=("070",))
    req = Requirements(required_courses=["C S 312", "M 408C"], core_areas=["070"])
    res = run([cs, m, gov], req, PreferenceConfig.model_validate({"hard": {"credit_min": 0}}))
    assert not res.schedules
    labels = {d["label"] for d in res.deferrals}
    assert labels == {
        "C S 312",
        "M 408C",
    }  # dropping either course frees a schedule; dropping the Core area does not


def test_compare_sections_shows_how_each_unique_reshapes_the_schedule():
    cs_a = mk("00001", "C S 312", days=("M", "W"), start=540, end=600)  # clashes with calculus
    cs_b = mk("00002", "C S 312", days=("T", "TH"), start=540, end=600)
    m = mk(3, "M 408C", days=("M", "W"), start=560, end=620)
    only = mk(4, "E 316L", days=("T", "TH"), start=540, end=600)  # clashes with cs_b
    req = Requirements(required_courses=["C S 312", "M 408C"], preferred_courses=["E 316L"])
    cfg = PreferenceConfig.model_validate({"hard": {"credit_min": 0}, "weights": {"wishlist": 1}})
    rows, _ = S.compare_sections(
        catalog([cs_a, cs_b, m, only]), req, cfg, idx(), None, "C S 312", ["00001", "00002"]
    )
    by = {r.unique: r for r in rows}
    assert by["00001"].schedule is None  # clashes with the required calculus section
    assert by["00002"].schedule is not None and by["00002"].delta == 0
    assert (
        "E 316L" not in by["00002"].schedule.wish_included
    )  # E 316L now clashes with the section you picked
    assert rows[0].unique == "00002"


def test_compare_sections_orders_by_utility_and_explains_the_gap():
    early = mk("00001", "C S 312", days=("M", "W"), start=480, end=540)
    late = mk("00002", "C S 312", days=("M", "W"), start=840, end=900)
    cfg = PreferenceConfig.model_validate(
        {"hard": {"credit_min": 0}, "time_bias": 1, "weights": {"time_of_day": 1}}
    )
    rows, _ = S.compare_sections(
        catalog([early, late]),
        Requirements(required_courses=["C S 312"]),
        cfg,
        idx(),
        None,
        "C S 312",
        ["00001", "00002"],
    )
    assert [r.unique for r in rows] == ["00002", "00001"]
    assert rows[1].delta < 0 and any("Time-of-day fit" in w for w in rows[1].why)
