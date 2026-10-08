import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Note, PageHead, when } from "./ui";

type Sources = {
  schedule: { by_source: { source: string; sections: number; first_fetch: string; last_fetch: string }[];
    pages: { source: string; pages: number; sections: number; parse_failures: number; first_fetch: string; last_fetch: string }[]; recent_urls: string[]; note: string | null };
  ratings: { rows: number; instructors_in_schedule: number; matched: number; how: string };
  grades: { sources: { id: number; name: string; license_note: string; imported_at: string; n_rows: number }[]; courses_covered: number };
  syllabi: { id: number; course: string; instructor: string | null; source_url: string | null; source_kind: string; fetched_at: string; lightness: number | null; coverage: number | null }[];
  missing: string[];
};
const ORIGIN: Record<string, string> = { authenticated: "Registrar schedule, read in your logged-in session", public: "Public page", file: "Saved page or file you imported", json: "JSON file you imported" };

export function SourcesScreen() {
  const [d, setD] = useState<Sources | null>(null);
  const [err, setErr] = useState("");
  const load = () => api<Sources>("/api/sources").then(setD).catch((e) => setErr((e as Error).message));
  useEffect(() => { void load(); }, []);

  return (
    <div>
      <PageHead title="Data sources">What was loaded, when, from where, and which optional signals are missing. Anything missing is left out of scores, and courses without it rank lower rather than being hidden.</PageHead>
      {err ? <Note error>{err}</Note> : null}
      {d ? (
        <>
          <section className="block">
            <h2>Schedule</h2>
            {d.schedule.by_source.length ? (
              <table className="t" style={{ marginTop: 8 }}>
                <thead><tr><th>Origin</th><th className="num">Sections</th><th>First fetched</th><th>Last fetched</th></tr></thead>
                <tbody>{d.schedule.by_source.map((s) => <tr key={s.source}><td>{ORIGIN[s.source] ?? s.source}</td><td className="num">{s.sections.toLocaleString()}</td><td>{when(s.first_fetch)}</td><td>{when(s.last_fetch)}</td></tr>)}</tbody>
              </table>
            ) : <p className="muted">No sections loaded.</p>}
            {d.schedule.pages.length ? (
              <p className="small muted" style={{ marginTop: 8 }}>
                {d.schedule.pages.map((p) => `${p.pages} pages from ${ORIGIN[p.source] ?? p.source}, ${p.parse_failures} parse failures`).join("; ")}.
              </p>
            ) : null}
            {d.schedule.note ? <p className="small" style={{ marginTop: 6 }}>{d.schedule.note}</p> : null}
            {d.schedule.recent_urls.length ? (
              <details style={{ marginTop: 8 }}><summary className="small">Recent source addresses</summary>
                <ul className="small mono" style={{ wordBreak: "break-all" }}>{d.schedule.recent_urls.map((u) => <li key={u}>{u}</li>)}</ul></details>
            ) : null}
          </section>

          <section className="block">
            <h2>Missing signals</h2>
            {d.missing.length ? <p>{d.missing.join(", ")} {d.missing.length === 1 ? "is" : "are"} not loaded. Ease then rests on whatever else is available, and courses show "none" or low confidence.</p> : <p>All three optional signals have some data.</p>}
          </section>

          <section className="block">
            <h2>Professor ratings</h2>
            <p className="lede">{d.ratings.how} Ratings loaded: {d.ratings.rows.toLocaleString()}. Instructors matched to the schedule: {d.ratings.matched.toLocaleString()} of {d.ratings.instructors_in_schedule.toLocaleString()}. Names that match two different people are skipped.</p>
            <Importer title="Import ratings CSV" help="Columns: instructor, avg_rating, avg_difficulty, num_ratings, would_take_again, source_url. Instructor may be LAST, FIRST or First Last. Look an instructor up with the link on the Courses screen, then copy their numbers in." endpoint="/api/import/ratings" onDone={load} />
          </section>

          <section className="block">
            <h2>Grade distributions</h2>
            <p className="lede">UT publishes an official dashboard at reports.utexas.edu (UT Course Grade Distributions). Whether its exported data may be reused is not stated there, so each import records where it came from and the terms you believe apply. Courses covered: {d.grades.courses_covered.toLocaleString()}.</p>
            {d.grades.sources.length ? (
              <table className="t" style={{ marginBottom: 10 }}>
                <thead><tr><th>Source</th><th>License or terms note</th><th className="num">Rows</th><th>Imported</th></tr></thead>
                <tbody>{d.grades.sources.map((g) => <tr key={g.id}><td>{g.name}</td><td>{g.license_note}</td><td className="num">{g.n_rows.toLocaleString()}</td><td>{when(g.imported_at)}</td></tr>)}</tbody>
              </table>
            ) : null}
            <Importer title="Import grades CSV" help="Columns: dept, number, instructor (optional), term (optional), then either letter-grade counts (A, A-, B+, ... F, W) or n, mean_gpa, a_rate, drop_rate." endpoint="/api/import/grades" onDone={load} withSource />
          </section>

          <section className="block">
            <h2>Syllabi</h2>
            <p className="lede">Syllabi are read on the Syllabi screen, which can search UT's syllabus site for the courses you choose. Everything read so far is listed here with where it came from. Any value the model cannot back with a quote found in the text is discarded.</p>
            {d.syllabi.length ? (
              <table className="t" style={{ marginBottom: 12 }}>
                <thead><tr><th>Course</th><th>Instructor</th><th>Source</th><th className="num">Lightness</th><th className="num">Coverage</th><th>Added</th></tr></thead>
                <tbody>{d.syllabi.map((s) => (
                  <tr key={s.id}><td className="mono">{s.course}</td><td>{s.instructor ?? "Any"}</td>
                    <td className="small" style={{ wordBreak: "break-all" }}>{s.source_url ?? s.source_kind}</td>
                    <td className="num">{s.lightness !== null ? s.lightness.toFixed(2) : "none"}</td><td className="num">{s.coverage !== null ? `${Math.round(s.coverage * 100)}%` : "none"}</td><td>{when(s.fetched_at)}</td></tr>))}</tbody>
              </table>
            ) : <p className="muted small">None read yet.</p>}
          </section>
        </>
      ) : !err ? <p className="muted">Loading.</p> : null}
    </div>
  );
}

function Importer({ title, help, endpoint, onDone, withSource }: { title: string; help: string; endpoint: string; onDone: () => void; withSource?: boolean }) {
  const [csv, setCsv] = useState("");
  const [source, setSource] = useState("");
  const [lic, setLic] = useState("");
  const [msg, setMsg] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const go = async () => {
    setErr(""); setMsg([]);
    try {
      const r = await api<{ imported: number; rejected: string[] }>(endpoint, { body: withSource ? { csv, source, license_note: lic || "not stated" } : { csv } });
      setMsg([`Imported ${r.imported} rows.`, ...r.rejected.slice(0, 8)]);
      if (r.imported) { setCsv(""); onDone(); }
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <details>
      <summary style={{ cursor: "pointer" }}>{title}</summary>
      <div className="stack" style={{ marginTop: 8, maxWidth: 760 }}>
        <p className="small muted">{help}</p>
        <input ref={file} type="file" accept=".csv,text/csv" aria-label="Choose a CSV file" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setCsv(await f.text()); }} />
        <label className="field"><span>Or paste CSV</span><textarea rows={5} value={csv} onChange={(e) => setCsv(e.target.value)} /></label>
        {withSource ? (
          <div className="row">
            <label className="field" style={{ flex: 1, minWidth: 220 }}><span>Where it came from (required)</span><input type="text" value={source} onChange={(e) => setSource(e.target.value)} /></label>
            <label className="field" style={{ flex: 1, minWidth: 220 }}><span>License or terms note</span><input type="text" value={lic} onChange={(e) => setLic(e.target.value)} placeholder="not stated" /></label>
          </div>
        ) : null}
        <div><button className="btn primary" disabled={!csv.trim() || (withSource && !source.trim())} onClick={go}>Import</button></div>
        {err ? <Note error>{err}</Note> : null}
        {msg.length ? <Note>{msg.map((m) => <p key={m}>{m}</p>)}</Note> : null}
      </div>
    </details>
  );
}

export function SyllabusForm({ onDone }: { onDone: () => void }) {
  const [course, setCourse] = useState("");
  const [instr, setInstr] = useState("");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [out, setOut] = useState<{ lightness: number | null; coverage: number; dropped_unverified: string[]; components: { name: string; weight: number; value: number | null; note: string }[] } | null>(null);
  const go = async () => {
    setBusy(true); setErr(""); setOut(null);
    try {
      setOut(await api("/api/syllabus", { body: { course, instructor: instr || null, url: url || null, text: url ? null : text } }));
      onDone();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <details>
      <summary style={{ cursor: "pointer" }}>Add a syllabus</summary>
      <div className="stack" style={{ marginTop: 8, maxWidth: 760 }}>
        <div className="row">
          <label className="field"><span>Course (required)</span><input type="text" value={course} onChange={(e) => setCourse(e.target.value)} placeholder="C S 312" /></label>
          <label className="field"><span>Instructor (optional)</span><input type="text" value={instr} onChange={(e) => setInstr(e.target.value)} placeholder="LAST, FIRST" /></label>
        </div>
        <label className="field"><span>Public address of the syllabus (HTML or PDF)</span><input type="text" value={url} onChange={(e) => setUrl(e.target.value)} /></label>
        <label className="field"><span>Or paste the syllabus text</span><textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} disabled={!!url} /></label>
        <div><button className="btn primary" disabled={busy || !course.trim() || (!url.trim() && text.trim().length < 200)} onClick={go}>{busy ? "Reading syllabus" : "Extract and score"}</button></div>
        {err ? <Note error>{err}</Note> : null}
        {out ? (
          <div>
            <p><b>Lightness {out.lightness !== null ? out.lightness.toFixed(2) : "none"}</b> from {Math.round(out.coverage * 100)}% of the scored fields. {out.dropped_unverified.length ? `Discarded for lacking a matching quote: ${out.dropped_unverified.join(", ")}.` : ""}</p>
            <table className="t" style={{ marginTop: 6 }}>
              <thead><tr><th>Component</th><th className="num">Weight</th><th className="num">Value</th><th>Rule</th></tr></thead>
              <tbody>{out.components.map((c) => <tr key={c.name}><td>{c.name}</td><td className="num">{Math.round(c.weight * 100)}%</td><td className="num">{c.value !== null ? c.value.toFixed(2) : "not stated"}</td><td className="small muted">{c.note}</td></tr>)}</tbody>
            </table>
          </div>
        ) : null}
      </div>
    </details>
  );
}
