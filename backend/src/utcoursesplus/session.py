"""Manual login in a visible browser. The code never sees credentials; it only waits for the
schedule page to load, then saves cookies to data/session/ (gitignored)."""

import os
import shutil
import time

from .config import SCHEDULE_BASE, SESSION_DIR, SESSION_FILE


def login(timeout_s: int = 600) -> None:
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
        print(
            "This program does not read or store them. Waiting for the schedule search page..."
        )
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if (
                    page.url.startswith(SCHEDULE_BASE)
                    and "Search for" in page.title() + page.inner_text("body")[:400]
                ):
                    break
            except PlaywrightError:  # page is mid-navigation during the login redirects
                pass
            time.sleep(1)
        else:
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
