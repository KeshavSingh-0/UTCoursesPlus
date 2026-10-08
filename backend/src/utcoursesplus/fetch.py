"""Throttled, cached, read-only HTTP GET. Stops on any sign of a block."""

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .config import (
    CACHE_DIR,
    MIN_INTERVAL_SECONDS,
    SCHEDULE_HOST,
    SESSION_FILE,
    USER_AGENT,
)


class BlockedError(RuntimeError):
    """403/429/CAPTCHA/warning page. The crawl must stop and the user must be told."""


class SessionExpired(RuntimeError):
    """Redirected to the UT login page. The user must log in again."""


@dataclass
class Fetched:
    url: str
    text: str
    fetched_at: datetime
    from_cache: bool


def load_cookies(path: Path = SESSION_FILE) -> httpx.Cookies:
    """Load cookies from Playwright storage_state. Values are never logged."""
    if not path.exists():
        raise SessionExpired("No saved session. Run: uv run utcoursesplus login")
    state = json.loads(path.read_text())
    jar = httpx.Cookies()
    for c in state.get("cookies", []):
        jar.set(
            c["name"],
            c["value"],
            domain=c["domain"].lstrip("."),
            path=c.get("path", "/"),
        )
    return jar


class Fetcher:
    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        cookies: httpx.Cookies | None = None,
        min_interval: float = MIN_INTERVAL_SECONDS,
        client: httpx.Client | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._sleep, self._clock = sleep, clock
        self._last = None
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            cookies=cookies,
            follow_redirects=False,
            timeout=30.0,
        )

    def _paths(self, url: str, ext: str = "html") -> tuple[Path, Path]:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / f"{h}.{ext}", self.cache_dir / f"{h}.json"

    def _throttle(self) -> None:
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def _request(self, url: str) -> httpx.Response:
        """One throttled GET with backoff; raises BlockedError / SessionExpired on any sign of a block."""
        backoff = 5.0
        for attempt in range(4):
            self._throttle()
            try:
                r = self.client.get(url)
            except httpx.TransportError:
                if attempt == 3:
                    raise
                self._sleep(backoff)
                backoff *= 2
                continue
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("location", "")
                if "login" in loc or "SAML" in loc:
                    raise SessionExpired("Redirected to UT login. Run: uv run utcoursesplus login")
                raise BlockedError(f"Unexpected redirect to {loc[:80]} for {url}")
            if r.status_code in (403, 429):
                raise BlockedError(f"HTTP {r.status_code} for {url}")
            if r.status_code >= 500:
                if attempt == 3:
                    raise BlockedError(f"HTTP {r.status_code} after retries for {url}")
                self._sleep(backoff)
                backoff *= 2
                continue
            r.raise_for_status()
            return r
        raise BlockedError(f"Gave up on {url}")

    def get(self, url: str) -> Fetched:
        body, meta = self._paths(url)
        if body.exists() and meta.exists():
            m = json.loads(meta.read_text())
            return Fetched(url, body.read_text(), datetime.fromisoformat(m["fetched_at"]), True)
        r = self._request(url)
        text = r.text
        low = text.lower()
        if "captcha" in low or "access denied" in low or "unusual traffic" in low:
            raise BlockedError(f"Block or CAPTCHA page returned for {url}")
        if "samlrequest" in low:
            raise SessionExpired("Login page returned. Run: uv run utcoursesplus login")
        now = datetime.now(UTC)
        body.write_text(text)
        meta.write_text(json.dumps({"url": url, "fetched_at": now.isoformat(), "host": SCHEDULE_HOST}))
        return Fetched(url, text, now, False)

    def get_bytes(self, url: str) -> tuple[bytes, str, datetime, bool]:
        """Binary GET (PDFs). Returns (content, content_type, fetched_at, from_cache)."""
        body, meta = self._paths(url, "bin")
        if body.exists() and meta.exists():
            m = json.loads(meta.read_text())
            return body.read_bytes(), m.get("content_type", ""), datetime.fromisoformat(m["fetched_at"]), True
        r = self._request(url)
        ctype = r.headers.get("content-type", "")
        if "text/html" in ctype and "captcha" in r.text.lower():
            raise BlockedError(f"Block or CAPTCHA page returned for {url}")
        now = datetime.now(UTC)
        body.write_bytes(r.content)
        meta.write_text(json.dumps({"url": url, "fetched_at": now.isoformat(), "content_type": ctype}))
        return r.content, ctype, now, False
