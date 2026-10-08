"""Data-quality report over the local database."""

import sqlite3


def report(con: sqlite3.Connection) -> dict:
    q = lambda sql: con.execute(sql).fetchall()
    one = lambda sql: con.execute(sql).fetchone()[0]
    r = {
        "sections": one("SELECT COUNT(*) FROM section"),
        "courses": one("SELECT COUNT(*) FROM course"),
        "distinct_course_numbers": one(
            "SELECT COUNT(DISTINCT dept||' '||number) FROM course"
        ),
        "departments": one("SELECT COUNT(DISTINCT dept) FROM course"),
        "instructors": one("SELECT COUNT(*) FROM instructor"),
        "pages_logged": one("SELECT COUNT(*) FROM crawl_log"),
        "empty_pages": one("SELECT COUNT(*) FROM crawl_log WHERE n_sections=0"),
        "parse_failures": one("SELECT COUNT(*) FROM parse_failure"),
        "sections_missing_times": one(
            "SELECT COUNT(*) FROM section s WHERE NOT EXISTS (SELECT 1 FROM meeting m WHERE m.unique_no=s.unique_no "
            "AND m.term=s.term AND m.start_min IS NOT NULL)"
        ),
        "sections_no_instructor": one(
            "SELECT COUNT(*) FROM section s WHERE NOT EXISTS (SELECT 1 FROM section_instructor i "
            "WHERE i.unique_no=s.unique_no AND i.term=s.term)"
        ),
        "sections_no_level": one("SELECT COUNT(*) FROM section WHERE level IS NULL"),
        "sections_with_core_tag": one(
            "SELECT COUNT(DISTINCT unique_no) FROM section_tag WHERE kind='core'"
        ),
        "by_status": {
            row[0]: row[1]
            for row in q("SELECT status, COUNT(*) FROM section GROUP BY status")
        },
        "by_source": {
            row[0]: row[1]
            for row in q("SELECT source, COUNT(*) FROM section GROUP BY source")
        },
        "by_core_area": {
            row[0]: row[1]
            for row in q(
                "SELECT a.name, COUNT(DISTINCT t.unique_no) FROM core_area a LEFT JOIN section_tag t "
                "ON t.kind='core' AND t.code=a.code GROUP BY a.code ORDER BY a.name"
            )
        },
    }
    r["missing_times_by_mode"] = {
        str(row[0]): row[1]
        for row in q(
            "SELECT mode, COUNT(*) FROM section s WHERE NOT EXISTS (SELECT 1 FROM meeting m "
            "WHERE m.unique_no=s.unique_no AND m.term=s.term AND m.start_min IS NOT NULL) GROUP BY mode"
        )
    }
    r["no_instructor_by_status"] = {
        row[0]: row[1]
        for row in q(
            "SELECT status, COUNT(*) FROM section s WHERE NOT EXISTS (SELECT 1 FROM section_instructor i "
            "WHERE i.unique_no=s.unique_no AND i.term=s.term) GROUP BY status"
        )
    }
    r["unmapped_core_labels"] = {
        f"{row[0]}  [{row[1]}]": row[2]
        for row in q(
            "SELECT label, title, COUNT(DISTINCT unique_no) FROM section_tag "
            "WHERE kind='core' AND code='unmapped' GROUP BY label, title"
        )
    }
    r["flag_titles"] = {
        f"{row[0]}  [{row[1]}]": row[2]
        for row in q(
            "SELECT label, title, COUNT(DISTINCT unique_no) FROM section_tag "
            "WHERE kind='flag' GROUP BY label, title"
        )
    }
    r["unparseable_pages"] = [
        dict(x)
        for x in q("SELECT url, n_failures FROM crawl_log WHERE n_failures>0 LIMIT 20")
    ]
    r["failure_samples"] = [
        f"{x[0][-60:]}: {x[1]}"
        for x in q("SELECT url, detail FROM parse_failure LIMIT 10")
    ]
    return r


def print_report(r: dict) -> None:
    for k, v in r.items():
        if isinstance(v, dict):
            print(f"{k}:")
            for kk, vv in v.items():
                print(f"  {kk}: {vv}")
        elif isinstance(v, list):
            print(f"{k}: {len(v)}")
            for x in v:
                print(f"  {x}")
        else:
            print(f"{k}: {v}")
