import { useState } from "react";
import { api, FEATURE_LABELS, f2 } from "./api";
import type { GenResult, Schedule, Section, Status } from "./api";
import { Calendar } from "./Calendar";
import { NoData, Note, PageHead, StatusText } from "./ui";

export function SchedulesScreen({ status, result, busy, error, onGenerate }: {
  status: Status; result: GenResult | null; busy: boolean; error: string; onGenerate: () => Promise<GenResult | null>;
}) {
  const [idx, setIdx] = useState(0);
  void api;
  if (!status.has_data) return <div><PageHead title="Ranked schedules" /><NoData /></div>;
  const run = async () => { setIdx(0); await onGenerate(); };
  const cur: Schedule | undefined = result?.schedules[idx];

  return (
    <div>
      <PageHead title="Ranked schedules">Conflict-free combinations of your requirements, best first under your current preferences. Every schedule is built by a fixed search, not by the language model.</PageHead>
      <div className="row" style={{ marginBottom: 16 }}>
        <button className="btn primary" onClick={run} disabled={busy}>{busy ? "Searching" : result ? "Search again" : "Find schedules"}</button>
        {result ? <span className="small muted">Looked at {result.searched.toLocaleString()} partial schedules.</span> : null}
      </div>
      {error ? <Note error>{error}</Note> : null}
      {result?.notes.map((n) => <div key={n} style={{ marginBottom: 8 }}><Note>{n}</Note></div>)}
      {result?.problems.length ? <Note error>{result.problems.map((p) => <p key={p}>{p}</p>)}</Note> : null}
      {result && result.change.length ? <div style={{ margin: "8px 0" }}><Note><p><b>How the top schedule changed since the last search</b></p>{result.change.map((c) => <p key={c}>{c}</p>)}</Note></div> : null}

      {result?.schedules.length && cur ? (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 260px) minmax(0, 1fr)", gap: 28, alignItems: "start", marginTop: 8 }} className="sched-grid">
          <nav aria-label="Ranked schedules" className="sched-list">
            {result.schedules.map((s, i) => (
              <button key={i} aria-current={i === idx} onClick={() => setIdx(i)}>
                <b>{i + 1}</b>
                <span>
                  <span style={{ display: "block" }}>{s.credits} credits, utility {f2(s.utility)}</span>
                  <span className="small muted">{s.sections.map((x) => x.code).join(", ")}</span>
                </span>
              </button>
            ))}
          </nav>
          <div className="stack">
            <h2>Schedule {idx + 1}: {cur.credits} credit hours</h2>
            <Calendar sections={cur.sections} label={`Weekly calendar for schedule ${idx + 1}`} />
            <SectionTable sections={cur.sections} />
            <div>
              <h3>Why this ranks {idx === 0 ? "first" : `at ${idx + 1}`}</h3>
              <ul style={{ margin: "6px 0 0", paddingLeft: 20, maxWidth: "80ch" }}>
                {cur.why?.map((w) => <li key={w}>{w}</li>)}
              </ul>
              <p className="small muted" style={{ marginTop: 4 }}>{idx + 1 < result.schedules.length ? `Compared with schedule ${idx + 2}.` : "This is the last schedule in the list."}</p>
            </div>
            <div>
              <h3>Score components</h3>
              <p className="small muted">Each value is 0 to 1. Share is how much of the utility it supplies at your weights. Missing ratings, grades or syllabi count against a course instead of being ignored.</p>
              <div style={{ maxWidth: 640, marginTop: 6 }}>
                {Object.keys(cur.contributions).map((k) => (
                  <div className="bar-row" key={k}>
                    <span>{FEATURE_LABELS[k]}</span>
                    <span className="bar"><i style={{ width: `${Math.round((cur.features[k] ?? 0) * 100)}%` }} /></span>
                    <span className="mono small" style={{ textAlign: "right" }}>{f2(cur.features[k])}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {result?.backups.length ? (
        <section className="block" aria-labelledby="bk-h" style={{ marginTop: 28 }}>
          <h2 id="bk-h">Backup schedules</h2>
          <p className="lede">These share as few sections as possible with schedule 1, in case sections fill before you register.</p>
          <div className="grid2">
            {result.backups.map((b, i) => (
              <div key={i} className="stack">
                <h3>Backup {i + 1}: {b.credits} credits, utility {f2(b.utility)}</h3>
                <Calendar compact sections={b.sections} label={`Weekly calendar for backup ${i + 1}`} />
                <p className="small muted">Different from schedule 1: {b.sections.filter((s) => !result.schedules[0].sections.some((t) => t.unique === s.unique)).map((s) => `${s.code} (${s.unique})`).join(", ") || "none"}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

export function SectionTable({ sections }: { sections: Section[] }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="t">
        <thead><tr><th>Unique</th><th>Course</th><th>Title</th><th>Instructor</th><th>Meets</th><th>Status</th><th>Ease</th><th>Signals</th></tr></thead>
        <tbody>
          {sections.map((s) => (
            <tr key={s.unique}>
              <td className="mono">{s.unique}</td><td className="mono">{s.code}</td><td>{s.title}</td><td>{s.instructors.join("; ") || "Not listed"}</td>
              <td>{s.when}</td><td><StatusText status={s.status} reserved={s.reserved} /></td>
              <td>{s.signal?.ease_score != null ? `${f2(s.signal.ease_score)} (${f2(s.signal.ease_score_lo)} to ${f2(s.signal.ease_score_hi)})` : <span className="muted">none</span>}</td>
              <td className="small">{s.signal?.signals.length ? s.signal.signals.join(", ") : <span className="warn">none</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
