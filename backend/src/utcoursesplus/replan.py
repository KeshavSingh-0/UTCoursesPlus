"""Registration that adapts as it goes. After each attempt the student reports what happened: sections they got
(fixed from then on), sections that were full, and courses they gave up on. The plan is searched again with those
facts, so the next steps already account for what was missed. If what is already registered blocks every full
schedule, or one registered course is holding the rest back, it names the section to drop and the new plan that
follows from dropping it. Nothing here touches the student's account."""

import itertools
from dataclasses import dataclass

from . import plantree, schedule
from .buildings import Buildings
from .catalog import Catalog, Sec, when_text
from .prefs import PreferenceConfig
from .requirements import Requirements
from .schedule import Schedule, Scorer
from .signals import SignalIndex

DROP_MARGIN = 0.02  # a drop that is not at least this much better is not worth suggesting
SEARCH_BUDGET = 60_000  # nodes per alternative while testing drops


@dataclass
class DropOption:
    drop: list[Sec]
    schedule: Schedule
    gain: (
        float | None
    )  # utility gained over the best plan that keeps every registered section; None if there is none


def _cfg_without(cfg: PreferenceConfig, blocked: set[str]) -> PreferenceConfig:
    c = cfg.model_copy(deep=True)
    c.hard.excluded_sections = sorted({*c.hard.excluded_sections, *blocked})
    return c


def _best(cat, req, cfg, sig, buildings, fixed: list[Sec], k: int = 1, budget: int = SEARCH_BUDGET):
    return schedule.generate(
        cat, req, cfg, sig, buildings, k=k, node_budget=budget, diagnose=False, fixed=fixed
    )


def _drop_options(
    cat, req, cfg, sig, buildings, fixed: list[Sec], base_utility: float | None
) -> list[DropOption]:
    """Best plan after dropping each single registered section (then each pair, if no single drop is enough)."""
    out: list[DropOption] = []
    for size in (1, 2):
        if size > len(fixed):
            break
        for combo in itertools.combinations(fixed, size):
            keep = [f for f in fixed if f not in combo]
            c2 = _cfg_without(cfg, {x.unique for x in combo})
            res = _best(cat, req, c2, sig, buildings, keep)
            if not res.schedules:
                continue
            top = res.schedules[0]
            if {x.unique for x in top.sections} & {x.unique for x in combo}:
                continue
            gain = None if base_utility is None else top.utility - base_utility
            if gain is not None and gain < DROP_MARGIN:
                continue
            out.append(DropOption(list(combo), top, gain))
        if out:
            break
    out.sort(key=lambda o: -o.schedule.utility)
    return out


def _changes(
    cat: Catalog, previous: list[str], top: Schedule, full: set[str], registered: set[str]
) -> list[str]:
    """Plain sentences about how the remaining steps differ from the plan the student was following."""
    new = {s.unique: s for s in top.sections if s.unique not in registered}
    old = {u: cat.sections[u] for u in previous if u in cat.sections and u not in registered}
    new_by_course = {s.course_key: s for s in new.values()}
    old_by_course = {s.course_key: s for s in old.values()}
    lines: list[str] = []
    for key, o in old_by_course.items():
        n = new_by_course.get(key)
        if n and n.unique == o.unique:
            continue
        why = "was full" if o.unique in full else "no longer fits"
        if n:
            lines.append(f"{o.code}: unique {o.unique} {why}. Try unique {n.unique} next ({when_text(n)}).")
        else:
            lines.append(f"{o.code} ({o.unique}) {why} and is no longer in the plan.")
    for key, n in new_by_course.items():
        if key not in old_by_course:
            lines.append(f"New in the plan: {n.code} {n.title}, unique {n.unique} ({when_text(n)}).")
    return lines


def replan(
    cat: Catalog,
    req: Requirements,
    cfg: PreferenceConfig,
    sig: SignalIndex,
    buildings: Buildings | None,
    registered: list[str],
    full: list[str],
    skipped: list[str],
    previous: list[str],
    dropped: list[str] | None = None,
    k: int = 8,
) -> dict:
    reg_set = {u for u in registered if u in cat.sections}
    fixed = [cat.sections[u] for u in registered if u in cat.sections]
    blocked = {u for u in [*full, *(dropped or [])] if u not in reg_set}
    skip_codes = {" ".join(c.upper().split()) for c in skipped}
    for s in cat.sections.values():
        if s.code in skip_codes and s.unique not in reg_set:
            blocked.add(s.unique)
    cfg2 = _cfg_without(cfg, blocked)
    # giving up on a course also gives up the requirement it stood for
    req = req.model_copy(
        update={
            "required_courses": [c for c in req.required_courses if c not in skip_codes],
            "preferred_courses": [c for c in req.preferred_courses if c not in skip_codes],
        }
    )
    res = schedule.generate(cat, req, cfg2, sig, buildings, k=k, diagnose=False, fixed=fixed)
    scorer = Scorer(cfg2, sig, buildings or Buildings())
    scorer.wish = schedule.wish_weights(req)

    out: dict = {
        "status": "ok",
        "problems": res.problems,
        "notes": res.notes,
        "changes": [],
        "drops": [],
        "registered": [
            {"unique": f.unique, "code": f.code, "title": f.title, "when": when_text(f), "credits": f.credits}
            for f in fixed
        ],
        "schedules": [],
        "registration": None,
        "plan_tree": None,
        "credits_registered": sum(f.credits for f in fixed),
    }
    base_utility = res.schedules[0].utility if res.schedules else None
    options = _drop_options(cat, req, cfg2, sig, buildings, fixed, base_utility) if fixed else []

    def drop_json(o: DropOption) -> dict:
        keep = [s for s in o.schedule.sections if s.unique not in reg_set]
        return {
            "drop": [
                {"unique": x.unique, "code": x.code, "title": x.title, "when": when_text(x)} for x in o.drop
            ],
            "gain": o.gain,
            "utility": o.schedule.utility,
            "credits": o.schedule.credits,
            "then_take": [
                {"unique": s.unique, "code": s.code, "title": s.title, "when": when_text(s)} for s in keep
            ],
            "why": schedule.explain_vs(
                o.schedule, res.schedules[0] if res.schedules else None, scorer.weights()
            ),
        }

    if not res.schedules:
        out["status"] = "drop_needed" if options else "stuck"
        out["drops"] = [drop_json(o) for o in options[:3]]
        if not options:
            out["problems"] = res.problems or [
                "No schedule fits what you have registered and what is still open, even after dropping one or two sections. Loosen a constraint on the Preferences screen or defer a requirement."
            ]
        return out

    top = res.schedules[0]
    backs = schedule.backups(res.pool, top, 3)
    reg = schedule.registration_plan(cat, top, req, cfg2)
    reg["steps"] = [r for r in reg["steps"] if r["unique"] not in reg_set]
    for i, r in enumerate(reg["steps"], 1):
        r["order"] = i
    out["registration"] = reg
    out["schedules"] = [schedule.schedule_json(s, scorer) for s in res.schedules[:3]]
    out["plan_tree"] = plantree.plan_tree(cat, req, cfg2, scorer, top, backs, reg)
    out["changes"] = _changes(cat, previous, top, blocked, reg_set)
    if options:
        out["status"] = "better_if_dropped"
        out["drops"] = [drop_json(o) for o in options[:2]]
    elif not reg["steps"]:
        out["status"] = "complete"
    return out
