"""Command line: uv run utcoursesplus <command>."""

import argparse
import sys
from pathlib import Path

from . import config
from .crawl import crawl_all, parse_departments
from .db import connect
from .fetch import BlockedError, Fetcher, SessionExpired, load_cookies
from .importers import import_html_files, import_json
from .quality import print_report, report


def _samples(con) -> None:
    rows = con.execute(
        "SELECT s.unique_no, c.dept||' '||c.number AS course, c.title, "
        "(SELECT group_concat(days||' '||COALESCE(printf('%d:%02d-%d:%02d',start_min/60,start_min%60,end_min/60,end_min%60),'TBA')"
        "||' '||COALESCE(building||' '||room,''),' / ') "
        "FROM meeting m WHERE m.unique_no=s.unique_no AND m.term=s.term) AS meets, "
        "(SELECT group_concat(name,'; ') FROM section_instructor i WHERE i.unique_no=s.unique_no AND i.term=s.term) AS instr, "
        "s.status, s.level, "
        "(SELECT group_concat(label,', ') FROM section_tag t WHERE t.unique_no=s.unique_no AND t.term=s.term) AS tags "
        "FROM section s JOIN course c USING(course_id) ORDER BY RANDOM() LIMIT 5"
    ).fetchall()
    for r in rows:
        print(" | ".join(str(x) for x in tuple(r)))


def serve(port: int, demo: bool, open_browser: bool) -> int:
    import threading
    import webbrowser

    import uvicorn

    from .api import DIST_DIR, create_app
    from .seed import bootstrap, sections_in

    if demo:
        from .demo import build

        if not sections_in(config.DEMO_DB):
            print(f"Building synthetic demo data at {config.DEMO_DB} ...")
            build(config.DEMO_DB)
        db = config.DEMO_DB
        print("DEMO MODE: the courses, instructors, times and seats are invented. Not UT data.")
    else:
        db = config.DB_PATH
        copied = bootstrap(db)
        if copied:
            print(f"Loaded {copied} sections from {config.SEED_DB} (first run on this computer).")
        n = sections_in(db)
        print(
            f"{n} sections loaded."
            if n
            else "No schedule loaded yet. The app will explain how; see README section 1."
        )
    if not (DIST_DIR / "index.html").exists():
        print(
            "The interface is not built yet. In another terminal run: cd frontend && npm install && npm run build",
            file=sys.stderr,
        )
    url = f"http://127.0.0.1:{port}"
    print(f"Open {url}   (press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(db, demo=demo), host="127.0.0.1", port=port, log_level="warning")
    return 0


def doctor() -> int:
    import shutil

    from . import settings
    from .api import DIST_DIR
    from .seed import sections_in

    rows: list[tuple[bool, str]] = []
    rows.append((sys.version_info >= (3, 12), f"Python {sys.version.split()[0]} (3.12 or newer needed)"))
    rows.append((bool(shutil.which("node")), "Node.js found (needed once, to build the interface)"))
    rows.append(((DIST_DIR / "index.html").exists(), "Interface built (frontend/dist)"))
    n = sections_in(config.DB_PATH)
    seeded = sections_in(config.SEED_DB)
    rows.append((n > 0 or seeded > 0, f"Class database: {n} sections in your data, {seeded} in seed/"))
    rows.append((settings.configured(), "AI key set (optional; only the three AI features need it)"))
    for ok, text in rows:
        print(("ok      " if ok else "MISSING ") + text)
    if not rows[3][0]:
        print(
            "\nNo classes yet: run `uv run utcoursesplus serve --demo` to try the app, or follow README section 1."
        )
    return 0 if all(ok for ok, _ in rows[:4]) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="utcoursesplus")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "login",
        help="open a visible browser; you log in by hand; cookies are saved locally",
    )
    sub.add_parser("clear-session", help="delete saved session cookies")
    c = sub.add_parser(
        "crawl",
        help="read-only crawl of every department and core area (needs a session)",
    )
    c.add_argument(
        "--only",
        nargs="*",
        help="limit to these department or core codes, e.g. 'C S' 090",
    )
    c.add_argument(
        "--homepage",
        type=Path,
        help="saved search home page, used if the live one is unavailable",
    )
    h = sub.add_parser("import-html", help="parse result pages you saved from your own browser")
    h.add_argument("files", nargs="+", type=Path)
    j = sub.add_parser("import-json", help="load sections from a JSON file")
    j.add_argument("file", type=Path)
    sub.add_parser("quality", help="data-quality report")
    sv = sub.add_parser("serve", help="run the local web app")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--demo", action="store_true", help="use synthetic sample data instead of your own")
    sv.add_argument("--open", action="store_true", help="open the app in your browser")
    sub.add_parser("doctor", help="check that everything needed to run the app is in place")
    sd = sub.add_parser(
        "export-seed", help="write seed/spring2027.sqlite (schedule facts only) to commit and share"
    )
    sd.add_argument("--db", type=Path, help="database to export (default: your own)")
    for name, hlp in (
        ("import-ratings", "CSV of professor ratings"),
        ("import-grades", "CSV of grade distributions"),
    ):
        ip = sub.add_parser(name, help=hlp)
        ip.add_argument("file", type=Path)
        if name == "import-grades":
            ip.add_argument("--source", required=True, help="where the data came from")
            ip.add_argument("--license-note", default="not stated", help="license or terms of the source")
    sy = sub.add_parser(
        "add-syllabus", help="extract fields from a public syllabus URL, a file, or pasted text"
    )
    sy.add_argument("course", help='e.g. "C S 312"')
    sy.add_argument("--instructor")
    sy.add_argument("--term")
    sy.add_argument("--url")
    sy.add_argument("--file", type=Path)
    gs = sub.add_parser("gold-sheet", help="write a CSV to hand-label stored syllabi")
    gs.add_argument("out", type=Path)
    ge = sub.add_parser("gold-eval", help="per-field accuracy of extraction against your labels")
    ge.add_argument("file", type=Path)
    sub.add_parser("reparse", help="rebuild crawled sections from cached pages (no requests)")
    sub.add_parser("diagnose", help="write raw example rows of anomalies to data/diagnose.txt")
    sub.add_parser("samples", help="print 5 random section rows")
    a = ap.parse_args(argv)

    if a.cmd == "login":
        from .session import login

        login()
        return 0
    if a.cmd == "clear-session":
        from .session import clear_session

        print("Session deleted." if clear_session() else "No saved session.")
        return 0
    if a.cmd == "doctor":
        return doctor()
    if a.cmd == "export-seed":
        from .seed import export_seed

        try:
            dest, n = export_seed(a.db or config.DB_PATH)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"Wrote {n} sections to {dest}.")
        print("It holds schedule facts only: no ratings, grades, syllabi, requirements, settings or keys.")
        print(
            f"To share it: git add {dest.parent.name}/{dest.name} && git commit -m 'data: Spring 2027 schedule' && git push"
        )
        return 0
    if a.cmd == "serve":
        return serve(a.port, a.demo, a.open)
    con = connect()
    if a.cmd == "import-html":
        n = import_html_files(con, a.files)
        print(f"Imported {n} sections.")
    elif a.cmd == "import-json":
        print(f"Imported {import_json(con, a.file)} sections.")
    elif a.cmd == "import-ratings":
        from .signals import import_ratings_csv

        print(import_ratings_csv(con, a.file.read_text()))
    elif a.cmd == "import-grades":
        from .signals import import_grades_csv

        print(import_grades_csv(con, a.file.read_text(), a.source, a.license_note))
    elif a.cmd == "add-syllabus":
        from .syllabus import add_syllabus, pdf_text

        text = None
        if a.file:
            text = pdf_text(a.file.read_bytes()) if a.file.suffix.lower() == ".pdf" else a.file.read_text()
        elif not a.url:
            text = sys.stdin.read()
        print(add_syllabus(con, a.course, text=text, url=a.url, instructor=a.instructor, term=a.term))
    elif a.cmd == "gold-sheet":
        from .syllabus import gold_sheet

        print(
            f"Wrote {gold_sheet(con, a.out)} rows to {a.out}. Fill the field columns; leave blank to skip, NA if not stated."
        )
    elif a.cmd == "gold-eval":
        from .syllabus import gold_eval

        for f, st in gold_eval(con, a.file).items():
            print(
                f"{f:24s} labeled {st['labeled']:3d}  accuracy {st['accuracy']}  false values {st['false_values']}  missed {st['missed']}"
            )
    elif a.cmd == "reparse":
        from .rebuild import reparse_cache

        reparse_cache(con)
        print_report(report(con))
    elif a.cmd == "diagnose":
        from .rebuild import diagnose

        print(f"Wrote {diagnose()}")
    elif a.cmd == "quality":
        print_report(report(con))
    elif a.cmd == "samples":
        _samples(con)
    elif a.cmd == "crawl":
        try:
            f = Fetcher(cookies=load_cookies())
            depts = parse_departments(f.get(config.SCHEDULE_BASE).text)
            if not depts and a.homepage:
                depts = parse_departments(a.homepage.read_text())
            if not depts:
                print(
                    "Could not read the department list from the search home page.",
                    file=sys.stderr,
                )
                return 2
            print(
                f"{len(depts)} fields of study. About {len(depts) * 3 + 10}+ requests at 1 per "
                f"{config.MIN_INTERVAL_SECONDS:.0f}s; cached pages are free, so you can stop and resume."
            )
            crawl_all(f, con, depts, only=set(a.only) if a.only else None)
        except SessionExpired as e:
            print(f"STOPPED: {e}", file=sys.stderr)
            return 3
        except BlockedError as e:
            print(
                f"STOPPED, possible block: {e}\nDo not retry now. Wait, then check the site in your browser.",
                file=sys.stderr,
            )
            return 4
        print_report(report(con))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
