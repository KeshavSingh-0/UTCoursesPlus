"""Builds data/demo.sqlite with SYNTHETIC sections, for exercising the UI during development only.
Never used by the app by default. Run: uv run python tests/demo_db.py"""

import random
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from utcoursesplus import signals, syllabus
from utcoursesplus.db import connect, upsert_section
from utcoursesplus.models import Course, Instructor, Meeting, Section, Tag

random.seed(7)
OUT = Path(__file__).resolve().parents[2] / "data" / "demo.sqlite"
OUT.unlink(missing_ok=True)
con = connect(OUT)
PATTERNS = [(["M", "W", "F"], 50), (["T", "TH"], 75), (["M", "W"], 75), (["F"], 170)]
DEPTS = {
    "C S": ["312", "314", "429", "439", "331", "311"],
    "M": ["408C", "408D", "340L"],
    "GOV": ["310L", "312L"],
    "HIS": ["315K", "315L"],
    "E": ["316L", "316M", "603B"],
    "PSY": ["301", "304"],
    "ART": ["301"],
    "RHE": ["306"],
    "SDS": ["302", "320E"],
    "BIO": ["311C", "311D"],
    "PHL": ["301", "313"],
    "ECO": ["304K", "304L"],
}
CORE = {
    "GOV 310L": "070",
    "GOV 312L": "070",
    "HIS 315K": "060",
    "HIS 315L": "060",
    "E 316L": "040",
    "E 316M": "040",
    "PHL 301": "040",
    "PHL 313": "040",
    "PSY 301": "080",
    "PSY 304": "080",
    "ECO 304K": "080",
    "ECO 304L": "080",
    "ART 301": "050",
    "RHE 306": "010",
    "M 408C": "020",
    "M 408D": "020",
    "SDS 302": "020",
    "BIO 311C": "030",
    "BIO 311D": "093",
    "C S 312": "093",
}
NAMES = [
    "DOE, JANE",
    "SMITH, JOHN",
    "ROE, RICHARD",
    "LEE, ANN",
    "KIM, SOO",
    "PATEL, ASHA",
    "GARCIA, LUIS",
    "NGUYEN, TAN",
    "BROWN, KARA",
    "OKAFOR, ADA",
    "WANG, LI",
    "COHEN, DAN",
]
BLDG = ["GDC", "PMA", "BUR", "WEL", "JES", "RLP", "MEZ", "CAL"]
uid = 40000
for dept, nums in DEPTS.items():
    for n in nums:
        code = f"{dept} {n}"
        for _ in range(random.randint(2, 5)):
            uid += 5
            days, length = random.choice(PATTERNS)
            start = random.choice(range(8 * 60, 17 * 60, 30))
            online = random.random() < 0.08
            status = random.choices(["open", "closed", "waitlisted"], [8, 1.5, 1])[0]
            lvl = "L" if n[1] in "01" else "U"
            tags = [Tag(kind="core", code=CORE[code], label="x")] if code in CORE else []
            s = Section(
                unique=str(uid),
                term="20272",
                course=Course(dept=dept, number=n, title=f"{code} DEMO TITLE", credit_hours=int(n[0])),
                meetings=[]
                if online
                else [
                    Meeting(
                        days=days,
                        start_min=start,
                        end_min=start + length,
                        building=random.choice(BLDG),
                        room=f"{random.randint(1, 4)}.{random.randint(100, 400)}",
                    )
                ],
                instructors=[Instructor(name=random.choice(NAMES))],
                mode="Internet" if online else "Face-to-face",
                status=status,
                status_raw=status + ("; reserved" if random.random() < 0.15 else ""),
                reserved=random.random() < 0.15,
                level=lvl,
                tags=tags,
                source_url="https://example.invalid/demo",
                fetched_at=datetime(2026, 10, 8, tzinfo=UTC),
                source="file",
            )
            upsert_section(con, s)
con.commit()
signals.import_ratings_csv(
    con,
    "instructor,avg_rating,avg_difficulty,num_ratings,would_take_again\n"
    + "\n".join(
        f'"{n}",{random.uniform(2.5, 4.9):.1f},{random.uniform(1.8, 4.4):.1f},{random.choice([3, 8, 30, 120])},{random.randint(40, 95)}'
        for n in NAMES[:9]
    ),
)
signals.import_grades_csv(
    con,
    "dept,number,n,mean_gpa,a_rate,drop_rate\n"
    + "\n".join(
        f"{d},{n},{random.randint(80, 900)},{random.uniform(2.6, 3.8):.2f},0.3,0.06"
        for d, ns in DEPTS.items()
        for n in ns[:2]
    ),
    "synthetic demo",
    "synthetic data for UI development",
)
con.executescript(syllabus.SCHEMA_SQL)
ex = syllabus.SyllabusExtraction(
    exam_count=syllabus.QInt(value=2, quote="q"), group_work=syllabus.QBool(value=False, quote="q")
)
syllabus.store(
    con, "C S 312", "demo", ex, [], instructor=None, term=None, source_url=None, source_kind="synthetic demo"
)
print("wrote", OUT, uid - 40000, "ids")
