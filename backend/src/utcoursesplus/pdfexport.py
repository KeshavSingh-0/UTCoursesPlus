"""PDF export of every schedule version: the restrictions behind them, the registration backup plans written out
on page one, and for each schedule its sections, times, quality scores and a picture of the week."""

import io
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .catalog import CORE_NAMES, fmt_time
from .prefs import PreferenceConfig
from .requirements import Requirements

NAVY = colors.HexColor("#1B3A5C")
LINE = colors.HexColor("#C9D1DC")
# soft fills with dark text so the preview prints legibly in black and white too
FILLS = ["#D6E4F5", "#FBE0C8", "#D9EFD9", "#F3D9E6", "#E6E0F5", "#F6EFC4", "#D4EEF0", "#E8E1D8"]
DAY_ORDER = ["M", "T", "W", "TH", "F", "S"]
DAY_NAMES = {
    "M": "Monday",
    "T": "Tuesday",
    "W": "Wednesday",
    "TH": "Thursday",
    "F": "Friday",
    "S": "Saturday",
}
WEIGHT_LABELS = {
    "ease": "Course ease",
    "syllabus_lightness": "Syllabus lightness",
    "professor_quality": "Professor quality",
    "time_of_day": "Time of day",
    "compactness": "Compact days",
    "few_gaps": "Few gaps",
    "walking": "Short walks",
    "seat_availability": "Open seats",
    "wishlist": "Like-to-take courses",
}


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica", fontSize=9, leading=12)
    return {
        "b": base,
        "small": ParagraphStyle(
            "s", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#444444")
        ),
        "h1": ParagraphStyle(
            "h1", parent=base, fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=NAVY
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=NAVY,
            spaceBefore=8,
            spaceAfter=3,
        ),
        "cell": ParagraphStyle("c", parent=base, fontSize=8, leading=10),
        "cellb": ParagraphStyle("cb", parent=base, fontSize=8, leading=10, fontName="Helvetica-Bold"),
    }


def p(text: str, style) -> Paragraph:
    return Paragraph(escape(text), style)


def _hm(m: int | None) -> str:
    return fmt_time(m).replace(" a.m.", " am").replace(" p.m.", " pm")


def restrictions(cfg: PreferenceConfig, req: Requirements) -> list[tuple[str, str]]:
    h = cfg.hard
    rows: list[tuple[str, str]] = [("Credit hours", f"{h.credit_min} to {h.credit_max}")]
    rows.append(
        ("Earliest start", _hm(h.earliest_start_min) if h.earliest_start_min is not None else "No limit")
    )
    rows.append(("Latest end", _hm(h.latest_end_min) if h.latest_end_min is not None else "No limit"))
    rows.append(("Days off", ", ".join(DAY_NAMES[d] for d in h.days_off) or "None"))
    rows.append(
        ("Longest gap between classes", f"{h.max_gap_min} min" if h.max_gap_min is not None else "No limit")
    )
    rows.append(
        (
            "Longest walk between classes",
            f"{h.max_walk_min} min" if h.max_walk_min is not None else "No limit",
        )
    )
    if h.excluded_instructors:
        rows.append(("Instructors avoided", "; ".join(h.excluded_instructors)))
    if h.excluded_sections:
        rows.append(("Unique numbers excluded", ", ".join(h.excluded_sections)))
    if h.excluded_times:
        rows.append(
            (
                "Times blocked",
                "; ".join(f"{''.join(t.days)} {_hm(t.start_min)}-{_hm(t.end_min)}" for t in h.excluded_times),
            )
        )
    if req.required_courses:
        rows.append(("Required courses", ", ".join(req.required_courses)))
    if req.core_areas:
        rows.append(
            (
                "Core areas needed now",
                "; ".join(
                    CORE_NAMES.get(a, a) + (f" x{req.core_slots[a]}" if req.core_slots.get(a, 1) > 1 else "")
                    for a in req.core_areas
                ),
            )
        )
    like = [
        CORE_NAMES.get(c[5:], c) + " (Core)" if c.startswith("core:") else c for c in req.preferred_courses
    ]
    if like:
        rows.append(("Like to take, best first", ", ".join(like)))
    if req.pinned_sections:
        rows.append(
            (
                "Sections limited to",
                "; ".join(f"{c}: {', '.join(u)}" for c, u in req.pinned_sections.items() if u),
            )
        )
    if req.completed_courses:
        rows.append(
            ("Already taken (left out)", f"{len(req.completed_courses)} courses from your degree audit")
        )
    w = cfg.weights.model_dump()
    rows.append(
        (
            "What the ranking favours",
            ", ".join(
                f"{WEIGHT_LABELS[k]} {round(v * 100)}%"
                for k, v in sorted(w.items(), key=lambda kv: -kv[1])
                if v >= 0.005
            ),
        )
    )
    return rows


class WeekPreview(Flowable):
    """A weekly grid with one labelled block per meeting."""

    def __init__(self, sections: list[dict], width: float, height: float = 2.9 * inch):
        super().__init__()
        self.sections, self.width, self.height = sections, width, height
        self.order = {}
        for s in sections:
            self.order.setdefault(s["code"], len(self.order))

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        meets = [(s, m) for s in self.sections for m in s["meets"]]
        used = {d for _, m in meets for d in m["days"]}
        days = [d for d in DAY_ORDER[:5]] + (["S"] if "S" in used else [])
        if meets:
            lo = max(7 * 60, min(m["start"] for _, m in meets) // 60 * 60)
            hi = min(23 * 60, -(-max(m["end"] for _, m in meets) // 60) * 60)
        else:
            lo, hi = 8 * 60, 18 * 60
        hi = max(hi, lo + 4 * 60)
        left, top, bottom = 38.0, 14.0, 0.0
        gw = (self.width - left) / len(days)
        gh = self.height - top - bottom
        scale = gh / (hi - lo)
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(NAVY)
        for i, d in enumerate(days):
            c.drawCentredString(left + gw * (i + 0.5), self.height - 10, DAY_NAMES[d])
        c.setStrokeColor(LINE)
        c.setLineWidth(0.4)
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#555555"))
        for t in range(lo, hi + 1, 60):
            y = self.height - top - (t - lo) * scale
            c.line(left, y, self.width, y)
            c.drawRightString(left - 4, y - 2.5, _hm(t))
        for i in range(len(days) + 1):
            c.line(left + gw * i, self.height - top, left + gw * i, 0)
        for s, m in meets:
            for d in m["days"]:
                if d not in days:
                    continue
                x = left + gw * days.index(d) + 1
                y1 = self.height - top - (m["end"] - lo) * scale
                h = (m["end"] - m["start"]) * scale
                c.setFillColor(colors.HexColor(FILLS[self.order[s["code"]] % len(FILLS)]))
                c.setStrokeColor(NAVY)
                c.setLineWidth(0.6)
                c.rect(x, y1, gw - 2, h, fill=1, stroke=1)
                c.setFillColor(colors.black)
                c.setFont("Helvetica-Bold", 7)
                c.drawString(x + 3, y1 + h - 9, s["code"])
                if h > 20:
                    c.setFont("Helvetica", 6.5)
                    c.drawString(x + 3, y1 + h - 17.5, f"#{s['unique']}")
                if h > 30 and m.get("building"):
                    c.drawString(x + 3, y1 + h - 25.5, f"{m['building']} {m.get('room') or ''}".strip())


def _score(sig: dict | None) -> str:
    if not sig or sig.get("ease_score") is None:
        return "no data"
    lo, hi = sig.get("ease_score_lo"), sig.get("ease_score_hi")
    rng = f" ({lo:.2f}-{hi:.2f})" if lo is not None and hi is not None else ""
    return f"{sig['ease_score']:.2f}{rng}, {sig.get('confidence', '')} confidence".rstrip(", ")


def _section_table(sections: list[dict], st, width: float) -> Table:
    head = ["Unique", "Course", "Days and times", "Where", "Instructor", "Hrs", "Seats", "Ease score"]
    rows = [[p(h, st["cellb"]) for h in head]]
    for s in sorted(sections, key=lambda x: (x["meets"][0]["start"] if x["meets"] else 9999, x["code"])):
        where = (
            "; ".join(
                sorted(
                    {
                        f"{m['building']} {m.get('room') or ''}".strip()
                        for m in s["meets"]
                        if m.get("building")
                    }
                )
            )
            or "-"
        )
        seat = s["status"].capitalize() + (", reserved" if s.get("reserved") else "")
        rows.append(
            [
                p(s["unique"], st["cellb"]),
                p(
                    f"{s['code']} {s['title']}" + (f" ({s['counts_as']})" if s.get("counts_as") else ""),
                    st["cell"],
                ),
                p(s["when"], st["cell"]),
                p(where, st["cell"]),
                p("; ".join(s["instructors"]) or "-", st["cell"]),
                p(str(s["credits"]), st["cell"]),
                p(seat, st["cell"]),
                p(_score(s.get("signal")), st["cell"]),
            ]
        )
    cw = [0.62, 1.4, 1.2, 0.8, 1.0, 0.4, 0.6, 1.1]
    tot = sum(cw)
    t = Table(rows, colWidths=[width * c / tot for c in cw], repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6ECF4")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return t


def _backup_plans(out: dict, st) -> list:
    flow: list = [p("Registration backup plans", st["h2"])]
    reg = out.get("registration")
    if not reg or not reg["steps"]:
        return flow + [p("No registration plan is available.", st["b"])]
    flow.append(
        p(
            "Work down the list in order; it starts with the course most likely to fill. For each course, try the "
            "first unique number. If it is full, try the next one on the same line. If every option is full, "
            "switch to a whole backup schedule below, or search again in the app, which re-plans around what you got.",
            st["small"],
        )
    )
    flow.append(Spacer(1, 4))
    rows = [
        [
            p("#", st["cellb"]),
            p("Course", st["cellb"]),
            p("Try first", st["cellb"]),
            p("If it is full, try in this order", st["cellb"]),
        ]
    ]
    for s in reg["steps"]:
        opts = s["options"]
        first = opts[0]
        rest = [
            f"{o['unique']} ({o['when']}{', ' + o['status'] if o['status'] != 'open' else ''}{'; overlaps ' + ', '.join(o['conflicts']) if o['conflicts'] else ''})"
            for o in opts[1:]
        ]
        rows.append(
            [
                p(str(s["order"]), st["cell"]),
                p(f"{s['code']} {s['title']}", st["cellb"]),
                p(
                    f"{first['unique']}  {first['when']}"
                    + ("" if first["status"] == "open" else f" ({first['status']})"),
                    st["cell"],
                ),
                p(
                    "; then ".join(rest) if rest else "No other section fits. Use a backup schedule.",
                    st["cell"],
                ),
            ]
        )
    t = Table(rows, colWidths=[0.25 * inch, 1.6 * inch, 1.7 * inch, 3.95 * inch], repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6ECF4")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    flow.append(t)
    backs = out.get("backups") or []
    if backs:
        flow += [p("If the plan falls apart: whole backup schedules", st["h2"])]
        for i, b in enumerate(backs, 1):
            line = "; ".join(f"{s['code']} {s['unique']} ({s['when']})" for s in b["sections"])
            flow.append(p(f"Backup {i} ({b['credits']} credits, score {b['utility']:.3f}): {line}", st["b"]))
            flow.append(Spacer(1, 2))
    return flow


def build_pdf(out: dict, cfg: PreferenceConfig, req: Requirements, term_label: str = "Spring 2027") -> bytes:
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.65 * inch,
        title=f"{term_label} schedule options",
        author="UT Courses Plus",
    )
    width = letter[0] - 1.2 * inch

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(
            0.6 * inch,
            0.4 * inch,
            "Seat status is a snapshot from when the schedule was fetched. Check live status when you register.",
        )
        canvas.drawRightString(letter[0] - 0.6 * inch, 0.4 * inch, f"Page {d.page}")
        canvas.restoreState()

    scheds = out["schedules"]
    flow: list = [
        p(f"{term_label} schedule options", st["h1"]),
        p(
            f"{len(scheds)} ranked schedules and {len(out.get('backups') or [])} backups. Prepared {datetime.now(UTC):%B %d, %Y}.",
            st["small"],
        ),
        p("Restrictions these schedules respect", st["h2"]),
    ]
    rt = Table(
        [[p(k, st["cellb"]), p(v, st["cell"])] for k, v in restrictions(cfg, req)],
        colWidths=[1.7 * inch, width - 1.7 * inch],
    )
    rt.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ]
        )
    )
    flow.append(rt)
    flow += _backup_plans(out, st)

    def version(title: str, sch: dict, why: list[str] | None):
        parts = [
            p(title, st["h1"]),
            p(
                f"{sch['credits']} credit hours. Schedule score {sch['utility']:.3f} (higher is better; it combines the "
                "ease scores below, time of day, gaps and the other preferences you weighted).",
                st["small"],
            ),
            Spacer(1, 6),
            WeekPreview(sch["sections"], width),
            Spacer(1, 8),
            _section_table(sch["sections"], st, width),
        ]
        if why:
            parts += [p("Why it ranks here", st["h2"])] + [p("- " + w, st["b"]) for w in why]
        flow.append(PageBreak())
        flow.extend(parts[:1])
        flow.extend(parts[1:])

    for i, s in enumerate(scheds, 1):
        version(f"Schedule {i}", s, s.get("why"))
    for i, b in enumerate(out.get("backups") or [], 1):
        version(f"Backup schedule {i}", b, None)
    flow.append(Spacer(1, 10))
    flow.append(
        KeepTogether(
            [
                p("About the scores", st["h2"]),
                p(
                    "Ease score runs from 0 (hardest) to 1 (easiest) and blends grade data, professor ratings and syllabus "
                    "lightness where those were loaded; the range and confidence show how sure the estimate is. A course with no "
                    "data shows 'no data' and is ranked as less certain, never hidden.",
                    st["small"],
                ),
            ]
        )
    )
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
