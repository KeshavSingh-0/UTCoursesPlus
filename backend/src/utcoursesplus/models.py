"""Canonical schema. Everything crossing a boundary (parser, importer, DB) is validated here."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["open", "closed", "waitlisted", "cancelled", "unknown"]
Level = Literal["L", "U", "G"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Meeting(Strict):
    days: list[str]
    start_min: int | None = Field(default=None, ge=0, lt=24 * 60)
    end_min: int | None = Field(default=None, ge=0, le=24 * 60)
    building: str | None = None
    room: str | None = None


class Tag(Strict):
    """A flag shown on a section: a core curriculum area, or another flag (writing, ethics...)."""

    kind: Literal["core", "flag"]
    code: str  # core area code like '090'; 'unmapped' for a core-titled tag not in CORE_AREAS; css class for flags
    label: str
    title: str = ""  # tooltip text on the registrar page, kept for diagnosis


class Instructor(Strict):
    name: str  # as printed: LAST, FIRST MIDDLE


class Course(Strict):
    dept: str
    number: str
    title: str
    credit_hours: int | None = None

    @property
    def course_id(self) -> str:
        return f"{self.dept} {self.number}|{self.title}"

    @property
    def code(self) -> str:
        return f"{self.dept} {self.number}"


class Section(Strict):
    unique: str = Field(pattern=r"^\d{5}$")
    term: str = Field(pattern=r"^\d{5}$")
    course: Course
    meetings: list[Meeting] = []
    instructors: list[Instructor] = []
    mode: str | None = None
    status: Status = "unknown"
    status_raw: str = ""
    reserved: bool = False
    level: Level | None = None
    tags: list[Tag] = []
    source_url: str
    fetched_at: datetime
    source: Literal["authenticated", "public", "file", "json"] = "authenticated"

    @field_validator("tags")
    @classmethod
    def _dedupe_tags(cls, v: list[Tag]) -> list[Tag]:
        seen: dict[tuple[str, str], Tag] = {}
        for t in v:
            seen.setdefault((t.kind, t.code), t)
        return list(seen.values())


class CoreArea(Strict):
    code: str
    name: str


class RequirementGroup(Strict):
    """Filled in Stage 2."""

    name: str
    kind: Literal["core_area", "course_list", "elective", "other"]
    core_code: str | None = None
    courses: list[str] = []
    credit_hours_needed: int | None = None
    remaining: bool = True


# Core areas as listed in the registrar's Core curriculum search (homepage select).
CORE_AREAS = [
    CoreArea(code="090", name="First-Year Signature Course"),
    CoreArea(code="010", name="Communication"),
    CoreArea(code="040", name="Humanities"),
    CoreArea(code="070", name="American and Texas Government"),
    CoreArea(code="060", name="U.S. History"),
    CoreArea(code="080", name="Social and Behavioral Sciences"),
    CoreArea(code="020", name="Mathematics"),
    CoreArea(code="030", name="Natural Science and Technology, Part I"),
    CoreArea(code="093", name="Natural Science and Technology, Part II"),
    CoreArea(code="050", name="Visual and Performing Arts"),
]
