"""Synthetic sections for tests only. Never used by the app."""

from utcoursesplus.catalog import Catalog, Meet, Sec


def mk(
    unique,
    code="C S 312",
    title=None,
    days=("M", "W"),
    start=540,
    end=600,
    status="open",
    core=(),
    inst=("DOE, JANE",),
    credits=3,
    building="GDC",
    level="L",
    reserved=False,
):
    dept, _, number = code.rpartition(" ")
    meets = (Meet(tuple(days), start, end, building, "1.0"),) if start is not None else ()
    return Sec(
        unique=str(unique),
        code=code,
        dept=dept,
        number=number,
        title=title or code,
        credits=credits,
        level=level,
        mode="Face-to-face",
        status=status,
        reserved=reserved,
        instructors=tuple(inst),
        meets=meets,
        core=tuple(core),
        source_url="x",
        fetched_at="2026-10-08T00:00:00+00:00",
    )


def catalog(secs):
    cat = Catalog()
    for s in secs:
        cat.sections[s.unique] = s
        cat.by_course.setdefault(s.course_key, []).append(s)
        cat.by_code.setdefault(s.code, []).append(s)
    return cat
