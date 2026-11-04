# UTCoursesPlus

A tool for UT Austin students, run entirely on your own computer. It keeps a database of every Spring 2027 class with
its Core curriculum tags, optionally adds professor-rating, grade and syllabus signals, and ranks conflict-free
schedules with a registration plan that adapts as you register. Your data stays in a local SQLite file and the
gitignored `data/` folder. The only paid service is an optional AI key for three features.

## Quick start

You need three free tools, installed once:

- **uv** (runs the Python side): https://docs.astral.sh/uv/getting-started/installation/
- **Node.js 20 or newer** (builds the interface once): https://nodejs.org/
- **git**, to download the project.

Then, in a terminal on macOS or Linux (on Windows, use WSL):

    git clone https://github.com/KeshavSingh-0/UTCoursesPlus.git
    cd UTCoursesPlus
    ./start.sh --demo

The first run installs everything (a few minutes) and opens http://127.0.0.1:8000 in your browser. `--demo` uses
invented sample classes so you can look around right away; a banner on every screen says so. Stop the app with Ctrl+C.
Later runs start in seconds.

To use real classes instead, leave off `--demo` (see "Get the class database" below):

    ./start.sh

If something does not work, run `cd backend && uv run utcoursesplus doctor`. It lists what is missing.

### Without the script

Run these one at a time and wait for each to finish.

    cd backend
    uv sync
    cd ../frontend
    npm install
    npm run build
    cd ../backend
    uv run utcoursesplus serve --open

Add `--demo` for sample data or `--port 9000` to change the port.

## Get the class database

The app needs the Spring 2027 sections. There are three ways, easiest first.

**A. Use a shared database (no login, no crawl).** If the repository contains `seed/spring2027.sqlite`, the app copies
it into place the first time you start it without `--demo`, and you will see "Loaded N sections". It holds schedule
facts only: courses, sections, times, rooms, instructors and Core tags. If the `seed` folder is empty, nobody has
shared one yet; use B or C, then share yours (below).

**B. Crawl it yourself (needs your UT login).** The schedule at utdirect.utexas.edu requires your EID, so there is
no public source. UT's acceptable-use policy (https://security.utexas.edu/policies/aup, sections 5.7 and 5.10) prohibits
"unauthorized automated use of a service intended solely for human interaction", and UT has not published terms saying
scripted access to the schedule is allowed. Crawling is your decision and your account's risk. The crawler is
read-only (GET only), identifies itself honestly, waits 3 seconds between requests, caches every page, and stops on 403,
429, CAPTCHA or a login redirect. It never registers, adds, drops or joins a waitlist.

    cd backend
    uv run playwright install chromium
    uv run utcoursesplus login
    uv run utcoursesplus crawl
    uv run utcoursesplus clear-session

`playwright install` is needed once. `login` opens a visible browser: you type your EID, password and Duo yourself, and
the app never sees them. `crawl` reads every department at lower, upper and graduate level plus each Core area and can
take a while; it is safe to stop and run again, because cached pages are free. Add `--only "C S" 020` to limit it to some
departments or Core codes. `clear-session` deletes the saved cookies in `data/session/`. If login does not finish by
itself, open the schedule search page in that window and press Enter in the terminal.

**C. Save pages from your own browser.** Open the schedule results in your browser, save each page (File, Save Page As,
HTML), and load them: `uv run utcoursesplus import-html FILE...` (or `import-json FILE`).

Check the result with:

    uv run utcoursesplus quality      # counts, parse failures, missing times
    uv run utcoursesplus reparse      # rebuild from cached pages after a parser update (no requests)
    uv run utcoursesplus diagnose     # writes raw example rows for anomalies to data/diagnose.txt

### Share your class database

Once you have loaded the schedule, anyone who clones the project can skip the crawl:

    cd backend
    uv run utcoursesplus export-seed
    git add ../seed/spring2027.sqlite
    git commit -m "data: Spring 2027 schedule"
    git push

`export-seed` writes `seed/spring2027.sqlite` with schedule facts only. Your ratings, grades, syllabi, requirements,
preferences, settings and API keys are removed, and nothing else under `data/` is ever committed. The schedule
itself came from a login-only UT site, so check that sharing it is acceptable to you before you push it. Seat status
in a shared copy is a snapshot; recrawl to refresh it.

## Using the app

Work down the left menu. Everything saves as you go.

1. **Requirements.** Choose which Core areas you need and how each counts this semester: Required now, Like to take, or
   Not this semester. Add courses to Required or Like to take (drag to rank). To skip typing, choose your saved
   degree-audit Results page under "Import your degree audit results"; finished courses are then hidden everywhere.
   For "this class or that one", use **Either/or choices**: add two or more courses and every schedule takes exactly one.
   Only what you pick is scheduled; suggested filler electives are off unless you tick the box under Electives. Each
   section in a schedule shows what it counts as (Required, Either/or, Core, Like to take, or Filler elective).
   Add your registration time if you want it shown on the plan.
2. **Preferences.** Set credit range, earliest start, days off and the importance sliders, or type what you want in
   plain English (needs an AI key) and approve the proposed changes.
3. **Ranked schedules.** Press Find schedules. You get ranked, conflict-free schedules with the reasons, backups, and
   a comparison tab for choosing between sections of one course. If nothing fits, it says which requirement to put off.
   **Export PDF** (button beside Find schedules) downloads every ranked schedule and the backups: page one lists your
   restrictions and writes out the registration backup plans; each schedule then gets a weekly picture, its unique
   numbers, times, seat status and ease scores, and the schedule score.
4. **Registration plan.** On registration day, work through the runner by hand on UT's registration site (see below).
5. **Optional:** Syllabi, Data sources (ratings, grades) and AI models.

Language-model features (plain-English preferences, audit text parsing, syllabus reading) need an API key from any one
provider: Anthropic (Claude), OpenAI, Google (Gemini), xAI (Grok), or any OpenAI-compatible service. Paste a key on the AI
models screen and choose the provider and model for each job. Keys are saved in `data/settings.json` on this computer,
never shown again, and never committed. The variables `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` and
`XAI_API_KEY` also work. Everything else in the app works with no key. Keep keys out of chat and out of git.

Degree audit import reads your saved Results page on this computer with no AI. Name and EID are never read, and the file is
not kept.

## Troubleshooting

- **"No sections are loaded yet"**: you started without `--demo` and have no data. Use "Get the class database".
- **Page not found or blank**: the interface is not built. Run `cd frontend && npm install && npm run build`, then restart.
- **`uv` or `node` not found**: install them (links above) and open a new terminal.
- **Port already in use**: `./start.sh --port 9000`.
- **Stop with Ctrl+C**, restart with `./start.sh`. Your requirements and preferences are kept in `data/utcoursesplus.sqlite`.
- **Start over**: delete the `data/` folder (this removes your data and settings, not the code).
- **Crawl stopped with a message**: it stops on purpose when the site blocks or logs you out. Wait, log in again, and rerun;
  cached pages are not requested again.

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
- Registration plan: an adaptive keyboard runner plus a map of every fallback (see below).
- Syllabi: choose a subset of courses, read UT's syllabus site for just those, and get a difficulty score (see below).
- Data sources: what was loaded, when, and what is missing.
- AI models: API keys for any provider, and the provider and model for each job.

### Specific sections

On Requirements, open Sections beside any course and tick the unique numbers you would accept; only those are used for
that course. Type a unique number under Add a specific section to pin it directly. With two or more sections pinned,
Compare (on that row, or the second tab of Ranked schedules) finds the best whole schedule for each one and explains
what each choice changes.

### Plan map

Required courses, Core areas, like-to-take courses and electives as a tree: each course shows the section the plan wants and
the fallbacks in order, a Core area also shows other courses that would cover it, left-out items say why, and the backup
schedules sit alongside. Click a box to see its details or copy a unique number.

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

`uv run utcoursesplus serve --demo` runs the app on invented sample data (see `backend/src/utcoursesplus/demo.py`).
Every change is recorded in `CHANGELOG.json`.

### Adaptive registration

In the runner, Space means you got the section, the right arrow means it was full, X means you give up on the course,
and the left arrow undoes the last report. After each report the plan is searched again with what you hold fixed and
what failed removed, so the next steps already account for it, and a short list says what changed. If your registered
sections leave no possible schedule, it names the fewest sections to drop and the new plan that follows; press the
button once you have dropped them yourself. If a drop would reach a clearly better schedule it offers that as optional.
Reports are saved in this browser and restored if you reload. The app never registers or drops anything.
