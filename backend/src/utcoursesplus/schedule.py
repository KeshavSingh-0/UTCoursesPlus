"""Deterministic schedule search. The language model never touches this: it only edits the config.

Utility = sum over features of weight * feature value, with features in [0, 1] and weights
renormalized over the features that are available (walking needs building coordinates).
Section-level features (ease, lightness, quality, time of day, seats) are averaged over sections;
schedule-level features (compactness, gaps, walking) are computed on the whole week.
Search is backtracking over slots with pairwise conflict checks, hard-constraint pruning, a credit
ceiling, and branch-and-bound on an optimistic utility."""

import heapq
import itertools
import math
from dataclasses import dataclass, field

from .buildings import Buildings
from .catalog import Catalog, Sec, fmt_time, when_text
from .prefs import WEIGHT_NAMES, PreferenceConfig, TimeBlock
from .requirements import Requirements
from .signals import CourseSignal, SignalIndex, instructor_key

SEAT_SCORE = {"open": 1.0, "waitlisted": 0.25, "closed": 0.1}
RESERVED_SEAT = 0.7
CAND_PER_SLOT = 14
ELECTIVE_POOL = 40
NODE_BUDGET = 600_000
POOL_SIZE = 300

SECTION_FEATURES = ["ease", "syllabus_lightness", "professor_quality", "time_of_day", "seat_availability"]
SCHEDULE_FEATURES = ["compactness", "few_gaps", "walking"]

FEATURE_LABELS = {
    "ease": "Ease (grades and professor difficulty)",
    "syllabus_lightness": "Syllabus lightness",
    "professor_quality": "Professor rating",
    "time_of_day": "Time-of-day fit",
    "compactness": "Fewer days on campus",
    "few_gaps": "Fewer gaps",
    "walking": "Short walks",
    "seat_availability": "Seat availability",
}


# ----------------------------------------------------------------------------- conflicts


def meets_overlap(a: Sec, b: Sec) -> bool:
    """True if any timed meeting of a overlaps any timed meeting of b on a shared day."""
    for ma in a.timed_meets:
        for mb in b.timed_meets:
            if set(ma.days) & set(mb.days) and ma.start < mb.end and mb.start < ma.end:
                return True
    return False


def has_conflict(sections: list[Sec]) -> bool:
    return any(meets_overlap(a, b) for a, b in itertools.combinations(sections, 2))


def day_intervals(sections: list[Sec]) -> dict[str, list[tuple[int, int, Sec]]]:
    out: dict[str, list[tuple[int, int, Sec]]] = {}
    for s in sections:
        for m in s.timed_meets:
            for d in m.days:
                out.setdefault(d, []).append((m.start, m.end, s))
    for v in out.values():
        v.sort(key=lambda x: (x[0], x[1]))
    return out


# ----------------------------------------------------------------------------- hard constraints


def _inst_excluded(s: Sec, banned: list[str]) -> bool:
    keys = {instructor_key(n) for n in s.instructors}
    for b in banned:
        if instructor_key(b) in keys or any(b.strip().upper() in n.upper() for n in s.instructors):
            return True
    return False


def passes_hard(s: Sec, cfg: PreferenceConfig) -> bool:
    h = cfg.hard
    if s.status == "cancelled" or s.unique in h.excluded_sections:
        return False
    if _inst_excluded(s, h.excluded_instructors):
        return False
    for m in s.timed_meets:
        if h.earliest_start_min is not None and m.start < h.earliest_start_min:
            return False
        if h.latest_end_min is not None and m.end > h.latest_end_min:
            return False
        if set(m.days) & set(h.days_off):
            return False
        for tb in h.excluded_times:
            if set(m.days) & set(tb.days) and m.start < tb.end_min and tb.start_min < m.end:
                return False
    return True


# ----------------------------------------------------------------------------- features


@dataclass
class Scorer:
    cfg: PreferenceConfig
    sig: SignalIndex
    buildings: Buildings = field(default_factory=Buildings)
    _cache: dict[str, CourseSignal] = field(default_factory=dict)

    def signal(self, s: Sec) -> CourseSignal:
        k = f"{s.code}|{'/'.join(s.instructors)}"
        if k not in self._cache:
            self._cache[k] = self.sig.estimate(s.code, list(s.instructors))
        return self._cache[k]

    def weights(self) -> dict[str, float]:
        w = {n: getattr(self.cfg.weights, n) for n in WEIGHT_NAMES}
        if not self.buildings.available:
            w["walking"] = 0.0
        tot = sum(w.values())
        return {k: v / tot for k, v in w.items()} if tot else w

    def section_features(self, s: Sec) -> dict[str, float]:
        sg = self.signal(s)
        starts = [m.start for m in s.timed_meets]
        if starts:
            t = max(0.0, min(1.0, (sum(starts) / len(starts) - 480) / 600))
            b = self.cfg.time_bias
            tod = 0.5 + abs(b) * (((1 - t) if b < 0 else t) - 0.5)
        else:
            tod = 0.5
        seat = SEAT_SCORE.get(s.status, 0.5)
        if s.status == "open" and s.reserved:
            seat = RESERVED_SEAT
        return {
            "ease": sg.rank_ease,
            "syllabus_lightness": sg.rank_lightness,
            "professor_quality": sg.rank_quality,
            "time_of_day": tod,
            "seat_availability": seat,
        }

    def schedule_features(self, sections: list[Sec]) -> dict[str, float | None]:
        by_day = day_intervals(sections)
        days = len(by_day)
        compact = max(0.0, min(1.0, 1 - (days - 2) / 3)) if days else 1.0
        gap_total, walk_total = 0, 0.0
        walk_known = self.buildings.available
        for items in by_day.values():
            for (_, e1, s1), (st2, _, s2) in itertools.pairwise(items):
                gap_total += max(0, st2 - e1 - 20)
                if walk_known and s1 is not s2:
                    b1 = (
                        s1.meets[0].building
                        if not s1.timed_meets
                        else next((m.building for m in s1.timed_meets if m.end == e1), None)
                    )
                    b2 = next((m.building for m in s2.timed_meets if m.start == st2), None)
                    w = self.buildings.minutes(b1, b2)
                    if w is not None:
                        walk_total += w
        return {
            "compactness": compact,
            "few_gaps": 1 / (1 + gap_total / 120.0),
            "walking": (1 / (1 + walk_total / 20.0)) if walk_known else None,
        }

    def utility(self, sections: list[Sec]) -> tuple[float, dict[str, float], dict[str, float]]:
        """-> (utility, feature values, weighted contributions)."""
        w = self.weights()
        n = len(sections) or 1
        feats: dict[str, float | None] = {}
        sf = [self.section_features(s) for s in sections]
        for f in SECTION_FEATURES:
            feats[f] = sum(x[f] for x in sf) / n
        feats.update(self.schedule_features(sections))
        contrib = {f: w[f] * v for f, v in feats.items() if v is not None and w.get(f, 0) > 0}
        total_w = sum(w[f] for f in contrib)
        util = sum(contrib.values()) / total_w if total_w else 0.0
        return (
            util,
            {k: v for k, v in feats.items() if v is not None},
            {k: v / total_w for k, v in contrib.items()} if total_w else {},
        )


# ----------------------------------------------------------------------------- slots


@dataclass
class Slot:
    label: str
    kind: str  # required | core | choose | elective
    candidates: list[Sec]
    note: str = ""


def _best_per_course(secs: list[Sec], scorer: Scorer, cap: int) -> list[Sec]:
    """Rank sections by section-level utility and keep the best few per slot."""
    w = scorer.weights()

    def val(s: Sec) -> float:
        f = scorer.section_features(s)
        tot = sum(w[k] for k in SECTION_FEATURES) or 1
        return sum(w[k] * f[k] for k in SECTION_FEATURES) / tot

    return sorted(secs, key=lambda s: -val(s))[:cap]


def build_slots(
    cat: Catalog, req: Requirements, cfg: PreferenceConfig, scorer: Scorer
) -> tuple[list[Slot], list[str]]:
    problems: list[str] = []
    slots: list[Slot] = []
    taken: set[str] = set(req.required_courses)
    ok = lambda s: passes_hard(s, cfg)

    for code in req.required_courses:
        secs = [s for s in cat.by_code.get(code, []) if ok(s)]
        if not secs:
            total = len(cat.by_code.get(code, []))
            problems.append(
                f"{code}: "
                + (
                    "no sections are listed for Spring 2027."
                    if not total
                    else f"all {total} sections break a hard constraint or are cancelled."
                )
            )
        slots.append(Slot(code, "required", _best_per_course(secs, scorer, CAND_PER_SLOT)))

    for g in req.groups:
        if g.kind != "choose_from":
            continue
        pool = [s for c in g.courses for s in cat.by_code.get(c, []) if ok(s) and c not in taken]
        for i in range(g.pick):
            if not pool:
                problems.append(f"{g.name}: no eligible sections.")
            slots.append(
                Slot(
                    f"{g.name} ({i + 1} of {g.pick})", "choose", _best_per_course(pool, scorer, CAND_PER_SLOT)
                )
            )

    from .catalog import CORE_NAMES

    for code in req.core_areas:
        pool = [
            s for s in cat.active() if code in s.core and s.code not in taken and ok(s) and s.level != "G"
        ]
        if not pool:
            problems.append(f"{CORE_NAMES.get(code, code)}: no eligible sections.")
        slots.append(Slot(CORE_NAMES.get(code, code), "core", _best_per_course(pool, scorer, CAND_PER_SLOT)))

    base = sum(min((s.credits for s in sl.candidates), default=3) for sl in slots)
    need = max(0, math.ceil((cfg.hard.credit_min - base) / 3))
    if need:
        used_codes = taken | {s.code for sl in slots for s in sl.candidates if sl.kind == "required"}
        pool = [
            s
            for s in cat.active()
            if ok(s)
            and s.level in ("L", "U")
            and s.code not in used_codes
            and (not req.elective_depts or s.dept in req.elective_depts)
            and s.timed_meets
        ]
        by_course: dict[str, list[Sec]] = {}
        for s in pool:
            by_course.setdefault(s.course_key, []).append(s)
        best = [(_best_per_course(v, scorer, 1)[0], v) for v in by_course.values()]
        wts = scorer.weights()
        tot = sum(wts[k] for k in SECTION_FEATURES) or 1
        best.sort(
            key=lambda t: -sum(wts[k] * scorer.section_features(t[0])[k] for k in SECTION_FEATURES) / tot
        )
        top = [s for _, v in best[:ELECTIVE_POOL] for s in v]
        for i in range(need):
            slots.append(
                Slot(
                    f"Elective {i + 1}",
                    "elective",
                    _best_per_course(top, scorer, CAND_PER_SLOT * 2),
                    "Chosen from the easiest-ranked courses to reach your credit minimum",
                )
            )
    return slots, problems


# ----------------------------------------------------------------------------- search


@dataclass
class Schedule:
    sections: list[Sec]
    slots: list[str]
    credits: int
    utility: float
    features: dict[str, float]
    contributions: dict[str, float]


@dataclass
class Result:
    schedules: list[Schedule]
    pool: list[Schedule]
    problems: list[str]
    truncated: bool
    nodes: int
    notes: list[str] = field(default_factory=list)


def _gaps_ok(sections: list[Sec], max_gap: int | None, max_walk: int | None, b: Buildings) -> bool:
    if max_gap is None and max_walk is None:
        return True
    for items in day_intervals(sections).values():
        for (_, e1, s1), (st2, _, s2) in itertools.pairwise(items):
            if max_gap is not None and st2 - e1 > max_gap:
                return False
            if max_walk is not None and b.available and s1 is not s2:
                w = b.minutes(
                    next((m.building for m in s1.timed_meets if m.end == e1), None),
                    next((m.building for m in s2.timed_meets if m.start == st2), None),
                )
                if w is not None and w > max_walk:
                    return False
    return True


def generate(
    cat: Catalog,
    req: Requirements,
    cfg: PreferenceConfig,
    sig: SignalIndex,
    buildings: Buildings | None = None,
    k: int = 10,
) -> Result:
    scorer = Scorer(cfg, sig, buildings or Buildings())
    slots, problems = build_slots(cat, req, cfg, scorer)
    notes: list[str] = []
    if cfg.hard.max_walk_min is not None and not scorer.buildings.available:
        notes.append("Max walking time was not applied: no building coordinates are loaded.")
    if not slots:
        return Result(
            [],
            [],
            ["Nothing to schedule. Add required courses or Core areas on the Requirements screen."],
            False,
            0,
            notes,
        )
    if any(not sl.candidates for sl in slots):
        return Result([], [], problems, False, 0, notes)

    min_total = sum(min(x.credits for x in sl.candidates) for sl in slots)
    if min_total > cfg.hard.credit_max:
        return Result(
            [],
            [],
            [
                (
                    f"Your requirements need at least {min_total} credit hours ({len(slots)} courses), but your maximum is "
                    f"{cfg.hard.credit_max}. Raise the credit maximum on the Preferences screen or remove a requirement."
                )
            ],
            False,
            0,
            notes,
        )
    order = sorted(slots, key=lambda sl: len(sl.candidates))
    w = scorer.weights()
    sec_w = sum(w[f] for f in SECTION_FEATURES)
    sched_w = sum(w[f] for f in SCHEDULE_FEATURES if f != "walking" or scorer.buildings.available)
    total_w = sec_w + sched_w or 1.0

    def section_value(s: Sec) -> float:
        f = scorer.section_features(s)
        return sum(w[x] * f[x] for x in SECTION_FEATURES)

    slot_max = [max(section_value(s) for s in sl.candidates) for sl in order]
    suffix_max = [0.0] * (len(order) + 1)
    for i in range(len(order) - 1, -1, -1):
        suffix_max[i] = suffix_max[i + 1] + slot_max[i]
    suffix_min_credits = [0] * (len(order) + 1)
    for i in range(len(order) - 1, -1, -1):
        suffix_min_credits[i] = suffix_min_credits[i + 1] + min(s.credits for s in order[i].candidates)
    n_slots = len(order)
    cand_sorted = [sorted(sl.candidates, key=lambda s: -section_value(s)) for sl in order]

    heap: list[tuple[float, int, Schedule]] = []
    counter = itertools.count()
    state = {"nodes": 0, "trunc": False}
    chosen: list[Sec] = []
    used_codes: set[str] = set()

    def worst() -> float:
        return heap[0][0] if len(heap) >= POOL_SIZE else -1.0

    def rec(i: int, credits: int, sec_sum: float) -> None:
        if state["nodes"] >= NODE_BUDGET:
            state["trunc"] = True
            return
        state["nodes"] += 1
        if credits + suffix_min_credits[i] > cfg.hard.credit_max:
            return
        bound = (sec_sum + suffix_max[i]) / n_slots * sec_w / total_w + sched_w / total_w
        if bound <= worst():
            return
        if i == n_slots:
            if credits < cfg.hard.credit_min or not _gaps_ok(
                chosen, cfg.hard.max_gap_min, cfg.hard.max_walk_min, scorer.buildings
            ):
                return
            u, feats, contrib = scorer.utility(chosen)
            sch = Schedule(list(chosen), [sl.label for sl in order], credits, u, feats, contrib)
            item = (u, next(counter), sch)
            if len(heap) < POOL_SIZE:
                heapq.heappush(heap, item)
            elif u > heap[0][0]:
                heapq.heapreplace(heap, item)
            return
        for s in cand_sorted[i]:
            if s.code in used_codes:
                continue
            if any(meets_overlap(s, c) for c in chosen):
                continue
            chosen.append(s)
            used_codes.add(s.code)
            rec(i + 1, credits + s.credits, sec_sum + section_value(s))
            used_codes.discard(s.code)
            chosen.pop()
            if state["trunc"]:
                return

    rec(0, 0, 0.0)
    pool = [t[2] for t in sorted(heap, key=lambda t: -t[0])]
    # same set of sections can arise twice only through different slot labels; dedupe by unique set
    seen, uniq = set(), []
    for sch in pool:
        key = frozenset(s.unique for s in sch.sections)
        if key not in seen:
            seen.add(key)
            uniq.append(sch)
    if not uniq and not problems:
        problems.append(
            "No conflict-free combination meets your hard constraints and credit range. Loosen one constraint "
            "(days off, earliest start, credit minimum) and try again."
        )
    if state["trunc"]:
        notes.append(
            "The search hit its time limit; results are the best found, not guaranteed best overall."
        )
    # The ranked list shows each distinct set of courses once, at its best section choice; the
    # section-level alternatives stay in the pool and feed the backup schedules.
    ranked, seen_courses = [], set()
    for sch in uniq:
        courses = frozenset(s.code for s in sch.sections)
        if courses not in seen_courses:
            seen_courses.add(courses)
            ranked.append(sch)
    return Result(ranked[:k], uniq, problems, state["trunc"], state["nodes"], notes)


# ----------------------------------------------------------------------------- explanations


def explain_vs(a: Schedule, b: Schedule | None, weights: dict[str, float]) -> list[str]:
    """Plain-language reasons a ranks above b, from the features that differed most."""
    if b is None:
        return ["This is the only schedule that satisfies your constraints."]
    diffs = []
    for f in a.contributions.keys() | b.contributions.keys():
        da = a.contributions.get(f, 0.0) - b.contributions.get(f, 0.0)
        diffs.append((da, f))
    diffs.sort(key=lambda t: -abs(t[0]))
    lines = []
    for da, f in diffs[:4]:
        if abs(da) < 0.004:
            continue
        va, vb = a.features.get(f), b.features.get(f)
        if va is None or vb is None:
            continue
        better = "higher" if da > 0 else "lower"
        lines.append(
            f"{FEATURE_LABELS[f]} is {better} ({va:.2f} against {vb:.2f}), worth {da * 100:+.1f} points of utility "
            f"at your weight of {weights.get(f, 0) * 100:.0f}%."
        )
    if not lines:
        lines.append(
            "The two schedules score within 0.4 points of each other, so no single factor separates them."
        )
    only_a = [s for s in a.sections if s.unique not in {x.unique for x in b.sections}]
    only_b = [s for s in b.sections if s.unique not in {x.unique for x in a.sections}]
    if only_a or only_b:
        lines.append(
            "Sections that differ: "
            + ", ".join(f"{s.code} ({s.unique})" for s in only_a)
            + " instead of "
            + (", ".join(f"{s.code} ({s.unique})" for s in only_b) or "nothing")
            + "."
        )
    return lines


def describe_change(old: Schedule | None, new: Schedule | None) -> list[str]:
    if old is None or new is None:
        return []
    ou, nu = {s.unique: s for s in old.sections}, {s.unique: s for s in new.sections}
    if set(ou) == set(nu):
        return ["The top schedule did not change."]
    out = []
    for u in nu.keys() - ou.keys():
        out.append(f"Added {nu[u].code} {nu[u].title} ({u}), {when_text(nu[u])}.")
    for u in ou.keys() - nu.keys():
        out.append(f"Dropped {ou[u].code} {ou[u].title} ({u}).")
    return out


# ----------------------------------------------------------------------------- backups and registration


def backups(pool: list[Schedule], top: Schedule, n: int = 3) -> list[Schedule]:
    """Alternates that share as few sections as possible with the top pick and with each other."""
    chosen: list[Schedule] = []
    ref = [{s.unique for s in top.sections}]
    rest = [p for p in pool if p is not top]
    for _ in range(n):
        if not rest:
            break

        def key(p: Schedule) -> tuple[int, float]:
            mine = {s.unique for s in p.sections}
            return (max(len(mine & r) for r in ref), -p.utility)

        best = min(rest, key=key)
        chosen.append(best)
        ref.append({s.unique for s in best.sections})
        rest.remove(best)
    return chosen


def registration_plan(cat: Catalog, sched: Schedule, req: Requirements, cfg: PreferenceConfig) -> dict:
    """Ordered checklist: scarcest first. A heuristic from current seat status, not a forecast."""
    others = lambda s: [x for x in sched.sections if x is not s]
    rows = []
    for s in sched.sections:
        alts = [
            a
            for a in cat.by_course.get(s.course_key, [])
            if a.unique != s.unique
            and a.status != "cancelled"
            and passes_hard(a, cfg)
            and not has_conflict([a, *others(s)])
        ]
        open_alts = [a for a in alts if a.status == "open"]
        score, why = 0, []
        if s.status in ("closed", "waitlisted"):
            score += 3
            why.append(f"currently {s.status}")
        elif s.reserved:
            score += 1
            why.append("open, but some seats are reserved")
        if not open_alts:
            score += 2
            why.append("no open alternative section that fits the rest of the schedule")
        elif len(open_alts) == 1:
            score += 1
            why.append("only one open alternative section")
        if s.code in req.required_courses:
            score += 1
            why.append("required")
        fallback = None
        if alts:
            alts.sort(key=lambda a: (a.status != "open", a.reserved))
            f = alts[0]
            fallback = {
                "unique": f.unique,
                "when": when_text(f),
                "status": f.status,
                "instructors": list(f.instructors),
            }
        rows.append(
            {
                "unique": s.unique,
                "code": s.code,
                "title": s.title,
                "when": when_text(s),
                "status": s.status,
                "reserved": s.reserved,
                "scarcity": score,
                "reasons": why or ["open with open alternatives"],
                "fallback": fallback,
                "fetched_at": s.fetched_at,
            }
        )
    rows.sort(key=lambda r: (-r["scarcity"], r["code"]))
    for i, r in enumerate(rows, 1):
        r["order"] = i
    return {
        "steps": rows,
        "label": "Heuristic based on seat status when the schedule was fetched. It is not a probability forecast.",
        "registration_time": req.registration_time,
    }


# ----------------------------------------------------------------------------- serialization


def section_json(s: Sec, scorer: Scorer | None = None) -> dict:
    d = {
        "unique": s.unique,
        "code": s.code,
        "title": s.title,
        "credits": s.credits,
        "status": s.status,
        "reserved": s.reserved,
        "mode": s.mode,
        "instructors": list(s.instructors),
        "core": list(s.core),
        "level": s.level,
        "when": when_text(s),
        "meets": [
            {"days": list(m.days), "start": m.start, "end": m.end, "building": m.building, "room": m.room}
            for m in s.meets
            if m.timed
        ],
        "source_url": s.source_url,
        "fetched_at": s.fetched_at,
    }
    if scorer:
        d["signal"] = scorer.signal(s).as_dict()
    return d


def schedule_json(sch: Schedule, scorer: Scorer) -> dict:
    return {
        "credits": sch.credits,
        "utility": round(sch.utility, 4),
        "slots": sch.slots,
        "features": {k: round(v, 3) for k, v in sch.features.items()},
        "contributions": {k: round(v, 4) for k, v in sch.contributions.items()},
        "sections": [section_json(s, scorer) for s in sch.sections],
    }


__all__ = ["TimeBlock", "fmt_time"]
