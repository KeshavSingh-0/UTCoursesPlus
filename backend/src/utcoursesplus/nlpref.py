"""Natural-language tuning of PreferenceConfig. The model proposes a config and reasons; Python
validates it, computes the real diff, and nothing is applied until the user confirms."""

import json
from typing import Any

from pydantic import ValidationError

from . import llm
from .prefs import PreferenceConfig, PreferenceConfigLLM, Strict, diff


class FieldChange(Strict):
    path: str  # dotted path, e.g. 'weights.ease' or 'hard.days_off'
    phrase: str  # words from the user's request that caused it
    rationale: str


class PrefProposal(Strict):
    clarifying_question: str | None = None  # set when the request is ambiguous or contradictory
    tradeoff_note: str | None = None  # set when two asks pull against each other
    config: PreferenceConfigLLM | None = None
    changes: list[FieldChange] = []


SYSTEM = """You edit a schedule-preferences object for a UT Austin student. You only propose \
a new preferences object and a short reason per changed field. You never create, rank or edit \
schedules or courses.

Rules:
- Return the full proposed config, changing only what the request implies. Leave everything else \
exactly as given.
- Times are minutes from midnight (10:00 a.m. = 600, 5:00 p.m. = 1020). Days are M, T, W, TH, F.
- weights are relative importance; they will be renormalized, so set the ones that matter and \
keep the others near their current values. time_bias: -1 prefers mornings, +1 prefers afternoons.
- "No classes before 10" -> hard.earliest_start_min = 600. "Keep Fridays free" -> hard.days_off \
includes F. "Care more about workload than professor ratings" -> raise weights.ease and \
weights.syllabus_lightness, lower weights.professor_quality.
- weights.wishlist is how much the student values getting the courses they ranked as "like to take"; \
raise it for requests such as "prioritize the classes I want".
- For every changed field add a change entry: path, the exact phrase of the request that caused \
it, and a one-sentence rationale.
- If the request is ambiguous, or two asks contradict each other (for example the lightest \
possible classes and the highest rated professors), do not guess silently. Either set \
clarifying_question to ONE short question and leave config null, or apply a reasonable balance and \
state the tradeoff in tradeoff_note.
- If nothing in the request maps to a field, return config null and a clarifying_question."""


class ProposalError(ValueError):
    pass


def check_proposal(raw: dict[str, Any] | PrefProposal) -> PrefProposal:
    """Validate model output (also used directly on untrusted dicts in tests)."""
    try:
        p = raw if isinstance(raw, PrefProposal) else PrefProposal.model_validate(raw)
    except ValidationError as e:
        raise ProposalError(f"Proposal rejected: {e.errors()[0]['msg']} at {e.errors()[0]['loc']}") from e
    if p.config is None and not p.clarifying_question:
        raise ProposalError("Proposal had neither a config nor a clarifying question.")
    return p


def propose(request: str, current: PreferenceConfig, client=None) -> dict[str, Any]:
    """Returns {question, tradeoff, config, diff, reasons}; config is None when a question is asked.
    Only the request and the current preferences (without required courses) reach the model."""
    if not request.strip():
        raise ProposalError("Type what you want first.")
    client = client or llm.get_client("preferences")
    user = f"Request: {request.strip()}\n\nCurrent config:\n{json.dumps(current.for_llm())}"
    p = check_proposal(llm.structured(client, PrefProposal, SYSTEM, user, task="preferences"))
    new = current.with_llm_proposal(p.config) if p.config else None
    rows = diff(current, new) if new else []
    reasons = {c.path: c for c in p.changes}
    for r in rows:
        c = reasons.get(r["path"])
        r["phrase"] = c.phrase if c else None
        r["rationale"] = c.rationale if c else "No reason given by the model."
    # weight renormalization shifts every weight; report only those the model meant to change
    if new and any(r["path"].startswith("weights.") for r in rows):
        rows = [
            r
            for r in rows
            if not r["path"].startswith("weights.") or r["path"] in reasons or abs(r["new"] - r["old"]) > 0.02
        ]
    return {
        "question": p.clarifying_question,
        "tradeoff": p.tradeoff_note,
        "config": new.model_dump() if new else None,
        "diff": rows,
    }
