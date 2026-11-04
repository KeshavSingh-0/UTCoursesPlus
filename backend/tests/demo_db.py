"""Writes data/demo.sqlite with SYNTHETIC sections. Run: uv run python tests/demo_db.py
(`uv run utcoursesplus serve --demo` does the same on its own.)"""

from utcoursesplus.config import DATA_DIR
from utcoursesplus.demo import build

print("wrote", DATA_DIR / "demo.sqlite", build(DATA_DIR / "demo.sqlite"), "sections")
