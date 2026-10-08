"""Synthetic data for tests only. Never used by the app."""

import io
import zipfile

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


def row(term, course, unique, title, names, syl):
    cells = "<br/>".join(names)
    link = ""
    if syl == "download":
        link = f'<a href="/apps/student/coursedocs/courses/nlogon/download/{unique}9/" title="download syllabus">Download</a>'
    elif syl == "external":
        link = '<a href="https://utexas.simplesyllabus.com/doc/abc" title="view">View</a>'
    return (
        f"<tr><td>{term}</td><td>{course}</td><td>{unique}</td><td>{title}</td><td>{cells}<br/></td>"
        f"<td></td><td>{link}</td><td></td></tr>"
    )


PAGE = (
    "<table id='results_table'><tbody>"
    + "".join(
        [
            row("2026 Fall", "C S 439H", "55320", "Honors", ["Ahmed Gheith"], "download"),
            row("2026 Fall", "C S 439", "55255", "Systems", ["E Elnozahy"], "external"),
            row("2026 Fall", "C S 439", "55250", "Systems", ["Ahmed Gheith"], "download"),
            row("2025 Spring", "C S 439", "55240", "Systems", ["Jane Doe"], "download"),
            row("2013 Fall", "C S 439", "55230", "Systems", ["Old Person"], "download"),
            row("2024 Fall", "C S 439", "55220", "Systems", ["Sam Smith"], None),
        ]
    )
    + "</tbody></table>"
)


def make_docx(text: str) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{ln}</w:t></w:r></w:p>" for ln in text.split("\n"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()
