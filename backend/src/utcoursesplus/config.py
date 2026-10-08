"""Paths and constants. All local state lives under <repo>/data (gitignored)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
SESSION_DIR = DATA_DIR / "session"
SESSION_FILE = SESSION_DIR / "state.json"
SAMPLES_DIR = DATA_DIR / "samples"
DB_PATH = DATA_DIR / "utcoursesplus.sqlite"

TERM = "20272"  # Spring 2027
CONTACT = "ks62852@eid.utexas.edu"
USER_AGENT = f"ut-schedule-mvp/0.1 (personal student project; contact: {CONTACT})"

SCHEDULE_HOST = "utdirect.utexas.edu"
SCHEDULE_BASE = f"https://{SCHEDULE_HOST}/apps/registrar/course_schedule/{TERM}/"
RESULTS_URL = SCHEDULE_BASE + "results/"

MIN_INTERVAL_SECONDS = 3.0
