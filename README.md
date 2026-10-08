# UTCoursesPlus

Local tool that builds a Spring 2027 UT Austin course database (with Core curriculum tags),
adds optional rating, grade and syllabus signals, and ranks conflict-free schedules.
Everything stays on your machine: SQLite plus a gitignored `data/` folder. No paid services.

Status: Stage 1 (course database). Later stages: requirements, ratings and grades, syllabus
analysis, ranking and schedule generation, web UI.

## Setup (Python 3.12, uv)

    cd backend
    uv sync
    uv run playwright install chromium     # used only for the manual login window
    uv run pytest                          # 23 tests

## Stage 1: load the Spring 2027 schedule

The schedule at utdirect.utexas.edu requires your EID, so there is no public crawl source.
UT's acceptable-use policy (https://security.utexas.edu/policies/aup, sections 5.7 and 5.10)
prohibits "unauthorized automated use of a service intended solely for human interaction",
and UT has not published terms saying scripted access to the schedule is allowed. Automated
crawling is therefore your decision and your account's risk. The crawler is read-only (GET only),
sends an honest User-Agent, waits 3 seconds between requests, caches every page, and stops on
403, 429, CAPTCHA or a login redirect.

Option A, automated crawl after you log in by hand:

    uv run utcoursesplus login          # visible browser; you type EID, password, Duo
    uv run utcoursesplus crawl          # every department x lower/upper/grad, plus each Core area
    uv run utcoursesplus crawl --only "C S" 020     # limit to some departments or Core codes
    uv run utcoursesplus clear-session  # deletes saved cookies (data/session/)

The crawl is resumable: finished pages come from `data/cache/` and cost nothing. It does not
automate any registration, add, drop or waitlist action.

Option B, no automation: save result pages from your own browser (File > Save Page As, HTML only)
and import them:

    uv run utcoursesplus import-html path/to/page1.html path/to/page2.html

Option C: `uv run utcoursesplus import-json sections.json` (list of Section objects, see `models.py`).

Check the data:

    uv run utcoursesplus quality
    uv run utcoursesplus samples

After a parser update, rebuild from already-fetched pages (no requests):

    uv run utcoursesplus reparse
    uv run utcoursesplus diagnose     # writes data/diagnose.txt with raw example rows
