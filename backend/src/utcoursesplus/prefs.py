"""PreferenceConfig: hard constraints plus soft weights. One typed object, validated everywhere
(UI, API, language-model proposals). Unknown fields are rejected; weights always sum to 1."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Day = Literal["M", "T", "W", "TH", "F"]
WEIGHT_NAMES = [
    "ease",
    "syllabus_lightness",
    "professor_quality",
    "time_of_day",
    "compactness",
    "few_gaps",
    "walking",
    "seat_availability",
]
DEFAULT_WEIGHTS = {
    "ease": 0.24,
    "syllabus_lightness": 0.16,
    "professor_quality": 0.14,
    "time_of_day": 0.10,
    "compactness": 0.10,
    "few_gaps": 0.10,
    "walking": 0.06,
    "seat_availability": 0.10,
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeBlock(Strict):
    days: list[Day] = Field(min_length=1)
    start_min: int = Field(ge=0, le=1440)
    end_min: int = Field(ge=0, le=1440)

    @model_validator(mode="after")
    def _order(self):
        if self.end_min <= self.start_min:
            raise ValueError("end_min must be after start_min")
        return self


class HardCore(Strict):
    """Hard constraints a language model may propose changes to."""

    earliest_start_min: int | None = Field(default=None, ge=360, le=1320)
    latest_end_min: int | None = Field(default=None, ge=420, le=1440)
    days_off: list[Day] = []
    max_gap_min: int | None = Field(default=None, ge=0, le=720)
    max_walk_min: int | None = Field(default=None, ge=0, le=60)
    credit_min: int = Field(default=12, ge=0, le=30)
    credit_max: int = Field(default=18, ge=0, le=30)
    excluded_instructors: list[str] = []
    excluded_sections: list[str] = []
    excluded_times: list[TimeBlock] = []

    @field_validator("excluded_sections")
    @classmethod
    def _five_digits(cls, v: list[str]) -> list[str]:
        for s in v:
            if not (len(s) == 5 and s.isdigit()):
                raise ValueError(f"unique number must be 5 digits: {s!r}")
        return v

    @model_validator(mode="after")
    def _ranges(self):
        if self.credit_min > self.credit_max:
            raise ValueError("credit_min cannot exceed credit_max")
        if (
            self.earliest_start_min is not None
            and self.latest_end_min is not None
            and self.latest_end_min <= self.earliest_start_min
        ):
            raise ValueError("latest_end_min must be after earliest_start_min")
        return self


class HardConstraints(HardCore):
    """Adds required courses, which come from the user's requirements and are never sent to or
    changed by the language model."""

    required_courses: list[str] = []


class SoftWeights(Strict):
    ease: float = Field(default=DEFAULT_WEIGHTS["ease"], ge=0, le=1)
    syllabus_lightness: float = Field(default=DEFAULT_WEIGHTS["syllabus_lightness"], ge=0, le=1)
    professor_quality: float = Field(default=DEFAULT_WEIGHTS["professor_quality"], ge=0, le=1)
    time_of_day: float = Field(default=DEFAULT_WEIGHTS["time_of_day"], ge=0, le=1)
    compactness: float = Field(default=DEFAULT_WEIGHTS["compactness"], ge=0, le=1)
    few_gaps: float = Field(default=DEFAULT_WEIGHTS["few_gaps"], ge=0, le=1)
    walking: float = Field(default=DEFAULT_WEIGHTS["walking"], ge=0, le=1)
    seat_availability: float = Field(default=DEFAULT_WEIGHTS["seat_availability"], ge=0, le=1)

    @model_validator(mode="after")
    def _normalize(self):
        vals = {n: getattr(self, n) for n in WEIGHT_NAMES}
        total = sum(vals.values())
        if total <= 0:
            vals = dict(DEFAULT_WEIGHTS)
            total = 1.0
        for n, v in vals.items():
            object.__setattr__(self, n, round(v / total, 6))
        return self


class PreferenceConfigLLM(Strict):
    hard: HardCore = HardCore()
    weights: SoftWeights = SoftWeights()
    time_bias: float = Field(default=0.0, ge=-1, le=1)  # -1 prefer mornings, +1 prefer afternoons


class PreferenceConfig(Strict):
    hard: HardConstraints = HardConstraints()
    weights: SoftWeights = SoftWeights()
    time_bias: float = Field(default=0.0, ge=-1, le=1)

    def for_llm(self) -> dict[str, Any]:
        d = self.model_dump()
        d["hard"].pop("required_courses", None)
        return d

    def with_llm_proposal(self, proposal: PreferenceConfigLLM) -> "PreferenceConfig":
        d = proposal.model_dump()
        d["hard"]["required_courses"] = list(self.hard.required_courses)
        return PreferenceConfig.model_validate(d)


def flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(d, dict):
        out: dict[str, Any] = {}
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
        return out
    return {prefix[:-1]: d}


def diff(old: PreferenceConfig, new: PreferenceConfig) -> list[dict[str, Any]]:
    a, b = flatten(old.model_dump()), flatten(new.model_dump())
    rows = []
    for path in a:
        if path in b and a[path] != b[path]:
            if isinstance(a[path], float) and isinstance(b[path], float) and abs(a[path] - b[path]) < 1e-4:
                continue
            rows.append({"path": path, "old": a[path], "new": b[path]})
    return rows


# --- persistence: current config is the newest row; undo removes it -------------------------------


def _ensure(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS pref_history(id INTEGER PRIMARY KEY, at TEXT NOT NULL, "
        "config_json TEXT NOT NULL, note TEXT NOT NULL)"
    )


def current(con: sqlite3.Connection) -> PreferenceConfig:
    _ensure(con)
    row = con.execute("SELECT config_json FROM pref_history ORDER BY id DESC LIMIT 1").fetchone()
    return PreferenceConfig.model_validate_json(row[0]) if row else PreferenceConfig()


def save(con: sqlite3.Connection, cfg: PreferenceConfig, note: str = "") -> None:
    _ensure(con)
    with con:
        con.execute(
            "INSERT INTO pref_history(at, config_json, note) VALUES(?,?,?)",
            (datetime.now(UTC).isoformat(), cfg.model_dump_json(), note),
        )


def history(con: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    _ensure(con)
    rows = con.execute("SELECT id, at, note FROM pref_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def undo(con: sqlite3.Connection) -> PreferenceConfig:
    _ensure(con)
    n = con.execute("SELECT COUNT(*) FROM pref_history").fetchone()[0]
    if n:
        with con:
            con.execute("DELETE FROM pref_history WHERE id=(SELECT MAX(id) FROM pref_history)")
    return current(con)


def parse_json(text: str) -> PreferenceConfig:
    return PreferenceConfig.model_validate(json.loads(text))
