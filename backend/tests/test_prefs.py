import pytest
from pydantic import ValidationError

from utcoursesplus import nlpref, prefs
from utcoursesplus.db import connect
from utcoursesplus.prefs import PreferenceConfig, SoftWeights


def test_weights_normalize_and_default_sum_to_one():
    assert sum(SoftWeights().model_dump().values()) == pytest.approx(1.0, abs=1e-4)
    w = SoftWeights(
        ease=1,
        syllabus_lightness=1,
        professor_quality=0,
        time_of_day=0,
        compactness=0,
        few_gaps=0,
        walking=0,
        seat_availability=0,
    )
    assert w.ease == pytest.approx(0.5) and w.syllabus_lightness == pytest.approx(0.5)


def test_all_zero_weights_fall_back_to_defaults():
    z = SoftWeights(**{n: 0 for n in prefs.WEIGHT_NAMES})
    assert z.ease == pytest.approx(prefs.DEFAULT_WEIGHTS["ease"], abs=1e-4)


@pytest.mark.parametrize(
    "bad",
    [
        {"hard": {"credit_min": 19, "credit_max": 12}},
        {"hard": {"earliest_start_min": 100}},
        {"hard": {"days_off": ["Sunday"]}},
        {"hard": {"excluded_sections": ["123"]}},
        {"hard": {"surprise": 1}},
        {"weights": {"ease": -0.1}},
        {"weights": {"vibes": 0.5}},
        {"time_bias": 2},
        {"nope": 1},
    ],
)
def test_malformed_config_rejected(bad):
    with pytest.raises(ValidationError):
        PreferenceConfig.model_validate(bad)


def test_diff_ignores_unchanged_and_reports_changes():
    a = PreferenceConfig()
    b = PreferenceConfig.model_validate(
        {**a.model_dump(), "hard": {**a.model_dump()["hard"], "days_off": ["F"]}}
    )
    assert [r["path"] for r in prefs.diff(a, b)] == ["hard.days_off"]


def test_history_and_undo():
    con = connect(":memory:")
    assert prefs.current(con) == PreferenceConfig()
    c1 = PreferenceConfig.model_validate({"hard": {"days_off": ["F"]}})
    prefs.save(con, PreferenceConfig(), "initial")
    prefs.save(con, c1, "friday off")
    assert prefs.current(con).hard.days_off == ["F"]
    assert prefs.undo(con).hard.days_off == []


def test_llm_view_hides_required_courses_and_proposal_cannot_change_them():
    cfg = PreferenceConfig.model_validate({"hard": {"required_courses": ["C S 429"]}})
    assert "required_courses" not in cfg.for_llm()["hard"]
    prop = prefs.PreferenceConfigLLM.model_validate(
        {**cfg.for_llm(), "hard": {**cfg.for_llm()["hard"], "days_off": ["F"]}}
    )
    out = cfg.with_llm_proposal(prop)
    assert out.hard.required_courses == ["C S 429"] and out.hard.days_off == ["F"]


def test_check_proposal_rejects_malformed_output():
    for bad in [
        {"config": {"hard": {"credit_min": 99}}},  # out of range
        {"config": None, "changes": []},  # nothing useful
        {"config": {"weights": {"ease": 1}}, "extra": 1},  # unknown field
        {"config": {"hard": {"required_courses": ["X 1"]}}},  # model may not touch required courses
        "not a dict",
    ]:
        with pytest.raises((nlpref.ProposalError, TypeError)):
            nlpref.check_proposal(bad)


class FakeClient:
    """Stands in for the SDK: returns a canned parsed proposal."""

    def __init__(self, parsed):
        self.parsed = parsed
        self.last = None
        self.messages = self

    def parse(self, **kw):
        self.last = kw

        class R:
            stop_reason = "end_turn"
            parsed_output = self.parsed

        return R()


def test_propose_builds_diff_with_phrases_and_never_sends_required_courses():
    cur = PreferenceConfig.model_validate({"hard": {"required_courses": ["C S 429"]}})
    new = prefs.PreferenceConfigLLM.model_validate(
        {
            **cur.for_llm(),
            "hard": {
                **cur.for_llm()["hard"],
                "earliest_start_min": 600,
                "days_off": ["F"],
            },
        }
    )
    parsed = nlpref.PrefProposal(
        config=new,
        changes=[
            nlpref.FieldChange(
                path="hard.earliest_start_min",
                phrase="no classes before 10",
                rationale="10:00 = 600",
            ),
            nlpref.FieldChange(path="hard.days_off", phrase="keep Fridays free", rationale="Friday off"),
        ],
    )
    fc = FakeClient(parsed)
    out = nlpref.propose("no classes before 10, keep Fridays free", cur, client=fc)
    paths = {r["path"]: r for r in out["diff"]}
    assert paths["hard.earliest_start_min"]["phrase"] == "no classes before 10"
    assert out["config"]["hard"]["required_courses"] == ["C S 429"]
    assert "C S 429" not in fc.last["messages"][0]["content"]


def test_propose_passes_clarifying_question_through_without_config():
    parsed = nlpref.PrefProposal(clarifying_question="Lightest classes or best-rated professors first?")
    out = nlpref.propose(
        "lightest possible but highest rated professors",
        PreferenceConfig(),
        client=FakeClient(parsed),
    )
    assert out["config"] is None and out["question"] and out["diff"] == []
