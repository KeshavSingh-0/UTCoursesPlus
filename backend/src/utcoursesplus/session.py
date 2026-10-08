"""Manual login in a visible browser. The code never sees credentials; it only waits for the
schedule page to load, then saves cookies to data/session/ (gitignored)."""

import os
import select
import shutil
import sys
import time
from urllib.parse import urlparse

from .config import SCHEDULE_BASE, SCHEDULE_HOST, SESSION_DIR, SESSION_FILE


def is_schedule_page(url: str, title: str) -> bool:
    """True once the browser is on a logged-in registrar schedule page (not the UT login host)."""
    u = urlparse(url)
    return (
        u.hostname == SCHEDULE_HOST
        and "/course_schedule/" in u.path
        and (
            "Course Search" in title
            or "Search Results" in title
            or "Course Schedule" in title
        )
    )


def _enter_pressed() -> bool:
    try:
        return bool(select.select([sys.stdin], [], [], 0)[0]) and bool(
            sys.stdin.readline() is not None
        )
    except (
        OSError,
        ValueError,
    ):  # no select on stdin (Windows): rely on auto-detection only
        return False


def login(timeout_s: int = 900) -> None:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(SCHEDULE_BASE)
        print(
            "A browser window is open. Log in with your EID, password and Duo yourself."
        )
        print("This program does not read or store them.")
        print(
            "It saves your session automatically once the schedule search page loads."
        )
        print(
            "If it does not, open the schedule search page in that window and press Enter here."
        )
        deadline = time.time() + timeout_s
        saved = False
        while time.time() < deadline:
            try:
                url, title = page.url, page.title()
                if is_schedule_page(url, title):
                    saved = True
                    break
                if _enter_pressed():
                    if urlparse(url).hostname == SCHEDULE_HOST:
                        saved = True
                        break
                    print(
                        f"The browser is on {urlparse(url).hostname}, not the schedule. Finish logging in, then press Enter."
                    )
            except PlaywrightError:  # page is mid-navigation during the login redirects
                pass
            time.sleep(1)
        if not saved:
            browser.close()
            raise SystemExit(
                "Timed out waiting for login. Run the login command again."
            )
        ctx.storage_state(path=str(SESSION_FILE))
        os.chmod(SESSION_FILE, 0o600)
        browser.close()
    print(
        f"Session saved to {SESSION_FILE}. Remove it any time with: uv run utcoursesplus clear-session"
    )


def clear_session() -> bool:
    existed = SESSION_DIR.exists()
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    return existed
