"""A structured map of the plan for the interface: what to take, in which group, the fallback sections for each
course, other courses that would also cover a Core area, what was left out and why, and the backup schedules."""

from .catalog import CORE_NAMES, Catalog, Sec, when_text
from .prefs import PreferenceConfig
from .requirements import Requirements
from .schedule import Schedule, Scorer, meets_overlap, passes_hard

GROUP_OF = {
    "required": "required",
    "choose": "required",
    "core": "core",
    "wish": "like",
    "elective": "elective",
}
GROUP_TITLES = {
    "required": "Required courses",
    "core": "Core areas needed now",
    "like": "Like to take, in your ranking",
    "elective": "Electives to reach your credit minimum",
}
AREA_BY_NAME = {v: k for k, v in CORE_NAMES.items()}


def _sec(s: Sec) -> dict:
    return {
        "unique": s.unique,
        "when": when_text(s),
        "status": s.status,
        "reserved": s.reserved,
        "instructors": list(s.instructors),
    }


def _alternatives(
    cat: Catalog,
    cfg: PreferenceConfig,
    scorer: Scorer,
    area: str,
    skip_code: str,
    limit: int = 4,
    exclude: frozenset[str] = frozenset(),
) -> list[dict]:
    groups: dict[str, list[Sec]] = {}
    for s in cat.active():
        if (
            area in s.core
            and s.code != skip_code
            and s.code not in exclude
            and passes_hard(s, cfg)
            and s.level != "G"
        ):
            groups.setdefault(s.course_key, []).append(s)
    rows = []
    for secs in groups.values():
        best = max(
            secs, key=lambda x: 0.65 * scorer.signal(x).rank_ease + 0.35 * scorer.signal(x).rank_lightness
        )
        sg = scorer.signal(best)
        rows.append(
            {
                "code": best.code,
                "title": best.title,
                "credits": best.credits,
                "sections": len(secs),
                "rank": round(0.65 * sg.rank_ease + 0.35 * sg.rank_lightness, 3),
                "ease_score": sg.ease_score,
                "confidence": sg.confidence,
                "best": _sec(best),
            }
        )
    rows.sort(key=lambda r: -r["rank"])
    return rows[:limit]


def _left_out_reason(
    cat: Catalog, top: Schedule, cfg: PreferenceConfig, req: Requirements, token: str
) -> str:
    pins = req.pinned_sections
    if token.startswith("core:"):
        area = token[5:]
        pool = [s for s in cat.active() if area in s.core and passes_hard(s, cfg) and s.level != "G"]
    else:
        pool = [s for s in cat.by_code.get(token, []) if passes_hard(s, cfg) and s.status != "cancelled"]
    pool = [s for s in pool if not pins.get(s.code) or s.unique in pins[s.code]]
    if not pool:
        return "No section is open to you under your time limits and pinned sections."
    best_clash: set[str] | None = None
    for s in pool:
        clash = {x.code for x in top.sections if meets_overlap(s, x)}
        if best_clash is None or len(clash) < len(best_clash):
            best_clash = clash
        if not clash and top.credits + s.credits <= cfg.hard.credit_max:
            return "It would fit, but other choices scored higher overall."
    if best_clash:
        return f"Every allowed section overlaps {', '.join(sorted(best_clash))}."
    return f"Adding it would pass your {cfg.hard.credit_max}-credit maximum."


def plan_tree(
    cat: Catalog,
    req: Requirements,
    cfg: PreferenceConfig,
    scorer: Scorer,
    top: Schedule,
    backups: list[Schedule],
    plan: dict,
) -> dict:
    steps = {s["unique"]: s for s in plan["steps"]}
    groups: dict[str, list[dict]] = {k: [] for k in GROUP_TITLES}
    ranks = {tok: i + 1 for i, tok in enumerate(req.preferred_courses)}
    for sec, (kind, label, wkey) in zip(top.sections, top.meta, strict=False):
        step = steps.get(sec.unique)
        options = [{**o, "planned": j == 0} for j, o in enumerate(step["options"])] if step else []
        item = {
            "key": wkey or sec.code,
            "code": sec.code,
            "title": sec.title,
            "credits": sec.credits,
            "included": True,
            "slot": label,
            "rank": ranks.get(wkey),
            "options": options,
            "alternatives": [],
            "reason": None,
        }
        if kind == "core" or (kind == "wish" and wkey.startswith("core:")):
            area = AREA_BY_NAME.get(label) or (wkey[5:] if wkey.startswith("core:") else "")
            item["area"] = CORE_NAMES.get(area, label)
            item["alternatives"] = _alternatives(
                cat, cfg, scorer, area, sec.code, exclude=frozenset(req.completed_courses)
            )
        groups[GROUP_OF[kind]].append(item)
    included = set(top.wish_included)
    for tok in req.preferred_courses:
        if tok in included:
            continue
        label = CORE_NAMES.get(tok[5:], tok) if tok.startswith("core:") else tok
        title = cat.by_code[tok][0].title if tok in cat.by_code else None
        groups["like"].append(
            {
                "key": tok,
                "code": None if tok.startswith("core:") else tok,
                "title": title,
                "area": label if tok.startswith("core:") else None,
                "credits": None,
                "included": False,
                "slot": label,
                "rank": ranks[tok],
                "options": [],
                "alternatives": [],
                "reason": _left_out_reason(cat, top, cfg, req, tok),
            }
        )
    groups["like"].sort(key=lambda i: i["rank"] or 999)
    topset = {s.unique for s in top.sections}
    return {
        "root": {
            "title": "Spring 2027 plan",
            "credits": top.credits,
            "courses": len(top.sections),
            "utility": round(top.utility, 3),
        },
        "groups": [
            {"id": gid, "title": GROUP_TITLES[gid], "items": items} for gid, items in groups.items() if items
        ],
        "backups": [
            {
                "index": i + 1,
                "credits": b.credits,
                "utility": round(b.utility, 3),
                "sections": [
                    {**_sec(s), "code": s.code, "title": s.title, "shared": s.unique in topset}
                    for s in b.sections
                ],
            }
            for i, b in enumerate(backups)
        ],
    }
