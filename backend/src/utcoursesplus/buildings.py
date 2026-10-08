"""Optional building coordinates for rough walking-time estimates. Without data/buildings.csv
(columns: code,lat,lon) walking features are unavailable and are dropped from scoring."""

import csv
import math
from pathlib import Path

from .config import DATA_DIR

WALK_M_PER_MIN = 80.0
DETOUR = 1.3  # straight line to real paths


class Buildings:
    def __init__(self, coords: dict[str, tuple[float, float]] | None = None):
        self.coords = coords or {}

    @classmethod
    def load(cls, path: Path | None = None) -> "Buildings":
        p = path or DATA_DIR / "buildings.csv"
        if not p.exists():
            return cls()
        out = {}
        with p.open(newline="") as f:
            for r in csv.DictReader(f):
                try:
                    out[r["code"].strip().upper()] = (float(r["lat"]), float(r["lon"]))
                except (KeyError, ValueError):
                    continue
        return cls(out)

    @property
    def available(self) -> bool:
        return bool(self.coords)

    def minutes(self, a: str | None, b: str | None) -> float | None:
        if not a or not b:
            return None
        if a == b:
            return 0.0
        pa, pb = self.coords.get(a.upper()), self.coords.get(b.upper())
        if not pa or not pb:
            return None
        (la1, lo1), (la2, lo2) = pa, pb
        r = 6371000.0
        p1, p2 = math.radians(la1), math.radians(la2)
        h = (
            math.sin((p2 - p1) / 2) ** 2
            + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
        )
        return 2 * r * math.asin(math.sqrt(h)) * DETOUR / WALK_M_PER_MIN
