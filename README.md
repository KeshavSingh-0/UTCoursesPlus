# UTCoursesPlus

Local tool for UT Austin students. It builds a Spring 2027 course database with Core curriculum tags,
adds optional professor-rating, grade and syllabus signals, and ranks conflict-free schedules with a
registration checklist. Everything stays on your computer: one SQLite file and a gitignored `data/` folder.
No paid services except an Anthropic API key for three optional features.

## One-time setup

Run these one at a time, and wait for each to finish (do not join them with a single `&`).

    cd backend
    uv sync
    uv run playwright install chromium
    cd ../frontend
    npm install
    npm run build

`playwright install` is only needed for the manual login window.

## 1. Load the Spring 2027 schedule

The schedule at utdirect.utexas.edu requires your EID, so there is no public source. UT's acceptable-use policy
(https://security.utexas.edu/policies/aup, sections 5.7 and 5.10) prohibits "unauthorized automated use of a
service intended solely for human interaction", and UT has not published terms saying scripted access to the
schedule is allowed. Automated crawling is your decision and your account's risk. The crawler is read-only (GET
only), identifies itself honestly, waits 3 seconds between requests, caches every page, and stops on 403, 429,
CAPTCHA or a login redirect. It never registers, adds, drops or joins a waitlist.

    cd backend
    uv run utcoursesplus login
    uv run utcoursesplus crawl
    uv run utcoursesplus clear-session

`login` opens a visible browser; you type your EID, password and Duo yourself. `crawl` reads every department at
lower, upper and graduate level plus each Core area; add `--only "C S" 020` to limit it to some departments or Core
codes. `clear-session` deletes the saved cookies in `data/session/`.

If login does not finish by itself, open the schedule search page in the window and press Enter in the terminal.
The crawl resumes from `data/cache/`. Without automation: save result pages from your own browser and run
`uv run utcoursesplus import-html FILE...`, or `import-json FILE`.

    uv run utcoursesplus quality
    uv run utcoursesplus reparse
    uv run utcoursesplus diagnose

`quality` prints counts, parse failures and missing times. `reparse` rebuilds from cached pages after a parser update
(no requests). `diagnose` writes raw example rows for anomalies to `data/diagnose.txt`.

## 2. Run the app

    cd backend
    uv run utcoursesplus serve

Then open http://127.0.0.1:8000. The three language-model features (plain-English preferences, audit parsing, syllabus
reading) need an Anthropic API key. Paste it on the AI models screen, where you can also choose which model runs each
job; it is saved in `data/settings.json` on this computer and never shown again. Setting `ANTHROPIC_API_KEY` in the
terminal before `serve` also works, and a key saved in the app takes precedence. Keep keys out of chat and out of the
repository.

Screens:

- Requirements: triage the Core. Each Core area you still need is Required now, Like to take (included only if it fits,
  ranked with your courses) or Not this semester. Then keep two lists of courses. Required courses are in every schedule. Like to take
  courses are optional and ranked: drag them (or use the move buttons) and the app keeps as many as fit, preferring the
  higher-ranked one when two clash. A pasted degree audit can be parsed for review.
- Courses and sections: filterable table; each course can be added to either list.
- Preferences: sliders (including how much Like to take matters), hard constraints, and the plain-English box with a diff and undo.
- Ranked schedules: calendar, why each ranks where it does, backups. If nothing fits, it names the required items that, if put
  off, would let a schedule exist. The second tab compares the sections of one course.
- Plan map: one picture of the whole plan (see below).
- Registration plan: a keyboard runner plus a map of every fallback (see below).
- Syllabi: choose a subset of courses, read UT's syllabus site for just those, and get a difficulty score (see below).
- Data sources: what was loaded, when, and what is missing.
- AI models: your API key and the model for each job.

### Specific sections

On Requirements, open Sections beside any course and tick the unique numbers you would accept; only those are used for
that course. Type a unique number under Add a specific section to pin it directly. With two or more sections pinned,
Compare (on that row, or the second tab of Ranked schedules) finds the best whole schedule for each one and explains
what each choice changes.

### Plan map

Required courses, Core areas, like-to-take courses and electives as a tree: each course shows the section the plan wants and
the fallbacks in order, a Core area also shows other courses that would cover it, left-out items say why, and the backup
schedules sit alongside. Click a box to see its details or copy a unique number.

### Registration runner

On the Registration plan screen, with focus not in a text box: Space marks the shown section as registered and moves
to the next course; Right and Left Arrow move to the next or previous option when a section fills (options that
overlap a section you already registered are skipped); Up and Down change course; C copies the unique number; X skips a
course; Backspace undoes. The unique number is also copied automatically whenever the highlighted option changes
(a checkbox turns that off). Progress is kept in your browser. The tree below the runner shows every case at a glance.

### Syllabi from UT's syllabus site

The site (utdirect.utexas.edu/apps/student/coursedocs) needs your EID, like the schedule, and UT has not said in
writing that scripts may read it. So it works only on courses you select, only while you are logged in
(`uv run utcoursesplus login` first), one request every 3 seconds: one search per selected course, then one download per
syllabus you tick. Recommended picks are each current instructor's newest syllabus, then the newest recent ones.
Downloads are cached locally, turned into text on your computer, and read by the model, which must quote the text for
every value it reports. Syllabus hosted on Simple Syllabus (an outside site) and old .doc files cannot be read here.

## Optional signals (everything works without them)

- Professor ratings: RateMyProfessors' terms prohibit automated collection, so the app only imports a CSV you fill
  in (`import-ratings FILE`, or the Data sources screen) and shows a "Look up on RMP" link per instructor.
- Grade distributions: UT's official dashboard is at https://reports.utexas.edu/spotlight-data/ut-course-grade-distributions.
  Reuse terms for exported data are not stated there. `import-grades FILE --source "..." --license-note "..."` records both.
- Syllabi: `add-syllabus "C S 312" --url PUBLIC_URL` (or `--file`, or pasted text on the Data sources screen). Only public
  pages are fetched, after checking robots.txt. `gold-sheet out.csv` writes a sheet to label about 10 syllabi by hand, and
  `gold-eval out.csv` reports per-field accuracy.
- Building coordinates for walking time: `data/buildings.csv` with columns code, lat, lon. Without it that feature is dropped.

## Tests and checks

    cd backend && uv run pytest && uv run ruff check src tests
    cd frontend && npm run typecheck && npm test && npm run contrast

`backend/tests/demo_db.py` builds a synthetic database for trying the interface; it is development-only.
Every change is recorded in `CHANGELOG.json`.
