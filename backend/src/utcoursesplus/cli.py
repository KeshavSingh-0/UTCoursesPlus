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
    h = sub.add_parser(
        "import-html", help="parse result pages you saved from your own browser"
    )
    h.add_argument("files", nargs="+", type=Path)
    j = sub.add_parser("import-json", help="load sections from a JSON file")
    j.add_argument("file", type=Path)
    sub.add_parser("quality", help="data-quality report")
    sub.add_parser(
        "reparse", help="rebuild crawled sections from cached pages (no requests)"
    )
    sub.add_parser(
        "diagnose", help="write raw example rows of anomalies to data/diagnose.txt"
    )
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
    con = connect()
    if a.cmd == "import-html":
        n = import_html_files(con, a.files)
        print(f"Imported {n} sections.")
    elif a.cmd == "import-json":
        print(f"Imported {import_json(con, a.file)} sections.")
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
