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


def ida_html(extra_remaining: str = "") -> str:
    """A small stand-in for a saved IDA results page. Not a real audit; no real names or EIDs."""

    def crow(code, title, grade, unique, kind, hours, alias=False, prog=False):
        icon = '<img alt="In Progress icon" src="x.png"/>' if prog else ""
        return (
            f'<tr class="{"alias" if alias else ""}"><td class="course_num">{icon} {code}</td><td>{title}</td><td>{grade}</td>'
            f"<td>{unique}</td><td>{kind}</td><td>&nbsp; {hours}</td><td></td></tr>"
        )

    def rule(num, status, text, req, got, lack, courses, cls=""):
        img = f'<img alt="{status}" src="x.png"/>'
        return (
            f'<tr class="rule {cls}"><td class="line_num">{num}</td><td class="status">{img}</td><td>{text}</td>'
            f"<td>{req}</td><td>{got}</td><td>{lack}</td><td>{courses}</td><td>d</td></tr>"
        )

    return f"""<html><body>
<span class="major">ENTRY-LEVEL requirements for Computer Sciences</span>
<strong class="student_name">Test Student</strong> (<span class="student_eid">xx00000</span>)
<div id="coursework"><table class="results"><tbody>
<tr><th colspan="9" class="section_title">Fall 2025 Courses</th></tr>
{crow("RHE  306", "COMPOSITION 1", "A", "00000", "Transfer", 3)}
{crow("E  306", "RHETORIC AND COMPOSITION", "A", "00000", "Transfer", 3, alias=True)}
{crow("C S  312", "INTRODUCTION TO PROGRAMMING", "CR", "24971", "Credit by Exam", 3)}
{crow("M  408C", "CALCULUS", "F", "26050", "In-Residence", 4)}
<tr><th colspan="9" class="section_title">Fall 2026 Courses</th></tr>
{crow("C S  314", "DATA STRUCTURES", "", "54995", "In-Residence", 3, prog=True)}
{crow("C S  314H", "DATA STRUCTURES: HONORS", "", "00000", "In-Residence", 3, alias=True, prog=True)}
</tbody></table></div>
<div id="categories"><table class="results">
<thead><tr><th colspan="7" class="section_title">Core Curriculum (42 hours required with a letter grade)</th></tr></thead>
<tbody class="section">
{rule(1, "completed", "CORE (010): RHE 306 or its equivalent are required.", "3 hours", "3 hours", "0 hours", "RHE 306", "fulfilled")}
{rule(4, "not completed", "CORE (070): 6 hours in American &amp; Texas government, generally GOV 310L and GOV 312L.", "6 hours", "none", "6 hours", "No courses used")}
{rule(9, "not completed", "CORE (050): 3 hours in the visual and performing arts are required.", "3 hours", "none", "3 hours", "No courses used")}
{rule(10, "not completed", "CORE (030 and 031/093): 9 hrs Science and Technology.", "9 hours", "6 hours", "3 hours", "BIO 311C")}
{rule(11, "partial", "42 hours are required to complete the core curriculum", "42 hours", "33 hours", "9 hours", "...", "partial")}
</tbody></table>
<table class="results"><thead><tr><th colspan="7" class="section_title">General Education</th></tr></thead><tbody class="section">
{rule(1, "not completed", "3 Hrs in a different field from that used in CORE, chosen from the Social Science Approved list.", "3 hours", "none", "3 hours", "No courses used")}
{rule(2, "not completed", "C S 311 or 311H or 313K; 312 or 312H or 307.", "6 hours", "3 hours", "3 hours", "C S 311")}
{rule(3, "completed", "ENTRY-LEVEL REQUIREMENT: M 408C or M 408N.", "2 courses", "2 courses", "0 courses", "M 408C", "fulfilled")}
{extra_remaining}
</tbody></table>
<table class="results"><thead><tr><th colspan="7" class="section_title">Credit Hour Totals</th></tr></thead><tbody class="section">
{rule(1, "partial", "SIXTY semester hours in residence are required.", "60 hours", "17 hours", "43 hours", "x", "partial")}
</tbody></table>
</div></body></html>"""
