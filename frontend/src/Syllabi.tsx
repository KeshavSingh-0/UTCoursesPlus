import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { SyllabusForm } from "./Sources";
import { Note, PageHead } from "./ui";

type Reading = { id: number; term: string | null; instructor: string | null; source_url: string | null; lightness: number | null; coverage: number | null;
  components: { name: string; weight: number; value: number | null; note: string }[] };
type Course = { code: string; role: string | null; title: string | null; instructors: string[]; docs: Record<string, number>; syllabi: Reading[]; difficulty: number | null };
type Overview = { courses: Course[]; session_saved: boolean; llm_configured: boolean };
type Doc = { id: number; term_text: string; unique_no: string | null; title: string | null; instructors: string; url: string; kind: string; recommended: number; status: string; error: string | null };
type Job = { id: string; kind: string; state: "running" | "done" | "error"; lines: string[]; error: string | null };

const f2 = (x: number | null) => (x === null ? "none" : x.toFixed(2));

export function SyllabiScreen() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [err, setErr] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [extra, setExtra] = useState("");
  const [docs, setDocs] = useState<Record<string, Doc[]>>({});
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [job, setJob] = useState<Job | null>(null);
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    const r = await api<Overview>("/api/syllabi/overview");
    setOv(r);
    return r;
  }, []);
  const loadDocs = useCallback(async (codes: string[]) => {
    const out: Record<string, Doc[]> = {};
    for (const c of codes) out[c] = await api<Doc[]>(`/api/syllabi/docs?course=${encodeURIComponent(c)}`);
    setDocs(out);
    setTicked(new Set(Object.values(out).flat().filter((d) => d.recommended && d.status === "found" && d.kind === "download").map((d) => d.id)));
  }, []);

  useEffect(() => {
    load().then((r) => {
      const planned = r.courses.filter((c) => c.role).map((c) => c.code);
      setPicked(new Set(planned));
      const withDocs = r.courses.filter((c) => (c.docs.found ?? 0) + (c.docs.read ?? 0) + (c.docs.failed ?? 0) > 0).map((c) => c.code);
      if (withDocs.length) void loadDocs(withDocs);
    }).catch((e) => setErr((e as Error).message));
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [load, loadDocs]);

  const follow = (id: string, after: () => Promise<void>) => {
    if (timer.current) window.clearInterval(timer.current);
    const tick = async () => {
      try {
        const j = await api<Job>(`/api/jobs/${id}`);
        setJob(j);
        if (j.state !== "running") {
          if (timer.current) window.clearInterval(timer.current);
          await after();
        }
      } catch (e) { setErr((e as Error).message); if (timer.current) window.clearInterval(timer.current); }
    };
    void tick();
    timer.current = window.setInterval(tick, 1000);
  };

  const find = async () => {
    setErr(""); setJob(null);
    try {
      const codes = [...picked];
      const r = await api<{ job: string }>("/api/syllabi/find", { body: { courses: codes } });
      follow(r.job, async () => { await load(); await loadDocs(codes); });
    } catch (e) { setErr((e as Error).message); }
  };
  const read = async () => {
    setErr(""); setJob(null);
    try {
      const r = await api<{ job: string }>("/api/syllabi/read", { body: { doc_ids: [...ticked] } });
      follow(r.job, async () => { await load(); await loadDocs(Object.keys(docs)); });
    } catch (e) { setErr((e as Error).message); }
  };
  const toggle = <T,>(set: Set<T>, v: T, setter: (s: Set<T>) => void) => { const n = new Set(set); if (n.has(v)) n.delete(v); else n.add(v); setter(n); };

  if (!ov) return <div><PageHead title="Syllabi" />{err ? <Note error>{err}</Note> : <p className="muted">Loading.</p>}</div>;
  const running = job?.state === "running";
  const courses = ov.courses;
  const docCourses = Object.keys(docs).filter((c) => docs[c].length);

  return (
    <div>
      <PageHead title="Syllabi">Pick the courses you care about, and the app reads UT's syllabus site for just those and scores how heavy each looks. The score comes only from what the syllabi state, and anything they do not state is left out rather than guessed.</PageHead>
      {err ? <Note error>{err}</Note> : null}
      {!ov.session_saved ? <Note><p>No saved UT login was found on this computer. The syllabus site needs your EID. In a terminal, in the <code>backend</code> folder, run <code>uv run utcoursesplus login</code>, log in yourself in the window that opens, then come back here.</p></Note> : null}
      <p className="small muted" style={{ margin: "10px 0", maxWidth: "80ch" }}>
        This reads only while you are logged in as yourself, one request every 3 seconds, one search per selected course and one download per syllabus you tick. Files stay on this computer and are never shared. UT has not said in writing that scripts may read this site, so keep the selection small.
      </p>

      <section className="block" aria-labelledby="s1-h">
        <h2 id="s1-h">1. Choose courses</h2>
        <p className="lede">Your required and like-to-take courses are ticked. Add any other course by its code.</p>
        {courses.length ? (
          <table className="t" style={{ maxWidth: 980 }}>
            <thead><tr><th>Read</th><th>Course</th><th>Your list</th><th>Title</th><th>Instructors this spring</th><th className="num">Syllabi read</th><th className="num">Difficulty</th></tr></thead>
            <tbody>
              {courses.map((c) => (
                <tr key={c.code}>
                  <td><input type="checkbox" aria-label={`Include ${c.code}`} checked={picked.has(c.code)} onChange={() => toggle(picked, c.code, setPicked)} /></td>
                  <td className="mono">{c.code}</td><td>{c.role ?? <span className="muted">added</span>}</td><td>{c.title ?? <span className="muted">not in the schedule</span>}</td>
                  <td>{c.instructors.join("; ") || <span className="muted">not listed</span>}</td>
                  <td className="num">{c.syllabi.length}</td><td className="num">{f2(c.difficulty)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">No courses selected yet. Add required or like-to-take courses on the Requirements screen, or add one below.</p>}
        <div className="row" style={{ marginTop: 10 }}>
          <label className="field"><span className="xs">Another course code</span>
            <input type="text" value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="C S 439"
              onKeyDown={(e) => { if (e.key === "Enter") addExtra(); }} /></label>
          <button className="btn" style={{ alignSelf: "end" }} onClick={() => addExtra()}>Add</button>
          <button className="btn primary" style={{ alignSelf: "end" }} disabled={!picked.size || running || !ov.session_saved} onClick={find}>
            {running && job?.kind === "find" ? "Searching" : `Find syllabi for ${picked.size} course${picked.size === 1 ? "" : "s"}`}
          </button>
        </div>
      </section>

      {docCourses.length ? (
        <section className="block" aria-labelledby="s2-h">
          <h2 id="s2-h">2. Choose which syllabi to read</h2>
          <p className="lede">Recommended ones are ticked: the newest syllabus from each instructor teaching it this spring, then the newest recent ones. Older than 2022 is left unticked.</p>
          {docCourses.map((code) => (
            <details key={code} open style={{ marginBottom: 12 }}>
              <summary><b className="mono">{code}</b> <span className="muted small">{docs[code].length} on the site</span></summary>
              <table className="t" style={{ marginTop: 6, maxWidth: 980 }}>
                <thead><tr><th>Read</th><th>Term</th><th>Instructor</th><th>Section title</th><th>File</th><th>Status</th></tr></thead>
                <tbody>
                  {docs[code].map((d) => (
                    <tr key={d.id}>
                      <td><input type="checkbox" aria-label={`Read ${code} ${d.term_text} ${d.instructors}`} disabled={d.kind !== "download" || d.status === "read"} checked={ticked.has(d.id)} onChange={() => toggle(ticked, d.id, setTicked)} /></td>
                      <td>{d.term_text}</td><td>{d.instructors || <span className="muted">not listed</span>}</td><td>{d.title}</td>
                      <td>{d.kind === "download" ? "UT file" : <span className="muted">Outside site (Simple Syllabus); cannot be read here</span>}</td>
                      <td>{d.status === "read" ? "Read" : d.status === "failed" ? <span className="warn">Could not read: {d.error}</span> : d.recommended ? "Recommended" : <span className="muted">Not read</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))}
          {!ov.llm_configured ? <Note><p>ANTHROPIC_API_KEY is not set, so reading is disabled. Set it in the terminal that runs the server and restart.</p></Note> : null}
          <p className="small muted" style={{ margin: "6px 0", maxWidth: "75ch" }}>Each syllabus is turned into text on this computer and sent to the model once. That is usually a few cents each, so ten syllabi is typically under a dollar.</p>
          <button className="btn primary" disabled={!ticked.size || running || !ov.llm_configured || !ov.session_saved} onClick={read}>
            {running && job?.kind === "read" ? "Reading" : `Read ${ticked.size} syllabus${ticked.size === 1 ? "" : "es"}`}
          </button>
        </section>
      ) : null}

      {job ? (
        <section className="block" aria-labelledby="log-h">
          <h2 id="log-h">Progress</h2>
          {job.error ? <Note error>{job.error}</Note> : null}
          <pre className="log" aria-live="polite">{job.lines.join("\n") || "Starting"}{job.state === "done" ? "\nDone." : ""}</pre>
        </section>
      ) : null}

      <section className="block" aria-labelledby="s3-h">
        <h2 id="s3-h">3. Difficulty from the syllabi</h2>
        <p className="lede">Difficulty is 1 minus syllabus lightness, from 0 (light) to 1 (heavy). Lightness weighs exam count and weight, final exam, attendance, participation, late policy, weekly hours, projects and group work. Only fields a syllabus states count, and coverage says how many did. These scores feed the ease score on the Courses and Ranked schedules screens.</p>
        {courses.some((c) => c.syllabi.length) ? courses.filter((c) => c.syllabi.length).map((c) => (
          <details key={c.code} style={{ marginBottom: 10 }}>
            <summary><b className="mono">{c.code}</b> difficulty {f2(c.difficulty)} <span className="muted small">from {c.syllabi.length} syllabus{c.syllabi.length === 1 ? "" : "es"}{c.syllabi.length < 2 ? "; one syllabus is thin evidence" : ""}</span></summary>
            <table className="t" style={{ marginTop: 6, maxWidth: 980 }}>
              <thead><tr><th>Term</th><th>Instructor</th><th className="num">Difficulty</th><th className="num">Fields found</th><th>Source</th></tr></thead>
              <tbody>{c.syllabi.map((r) => (
                <tr key={r.id}><td>{r.term ?? ""}</td><td>{r.instructor ?? "Any"}</td><td className="num">{r.lightness === null ? "none" : (1 - r.lightness).toFixed(2)}</td>
                  <td className="num">{r.coverage === null ? "none" : `${Math.round(r.coverage * 100)}%`}</td><td className="small" style={{ wordBreak: "break-all" }}>{r.source_url ?? "pasted"}</td></tr>))}</tbody>
            </table>
            <table className="t" style={{ marginTop: 8, maxWidth: 760 }}>
              <thead><tr><th>Newest syllabus: component</th><th className="num">Weight</th><th className="num">Lightness</th><th>Rule</th></tr></thead>
              <tbody>{c.syllabi[0].components.map((k) => (
                <tr key={k.name}><td>{k.name}</td><td className="num">{Math.round(k.weight * 100)}%</td><td className="num">{k.value === null ? "not stated" : k.value.toFixed(2)}</td><td className="small muted">{k.note}</td></tr>))}</tbody>
            </table>
          </details>
        )) : <p className="muted">Nothing read yet.</p>}
      </section>

      <section className="block" aria-labelledby="s4-h">
        <h2 id="s4-h">Add a syllabus by hand</h2>
        <p className="lede">For a syllabus on a public page, or one you downloaded yourself and pasted.</p>
        <SyllabusForm onDone={() => void load()} />
      </section>
    </div>
  );

  function addExtra() {
    const code = extra.trim().toUpperCase().replace(/\s+/g, " ");
    if (!code) return;
    setExtra("");
    setPicked(new Set([...picked, code]));
    setOv((o) => (o && !o.courses.some((c) => c.code === code) ? { ...o, courses: [...o.courses, { code, role: null, title: null, instructors: [], docs: {}, syllabi: [], difficulty: null }] } : o));
  }
}
