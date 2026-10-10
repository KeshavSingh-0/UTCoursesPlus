import { useEffect, useState } from "react";
import { api, FEATURE_LABELS, f2 } from "./api";
import type { Compare, GenResult, Requirements, Schedule, Section, Status } from "./api";
import { DeferralNote } from "./Deferrals";
import { Calendar } from "./Calendar";
import { ccClass, NoData, Note, PageHead, StatusText } from "./ui";

export function SchedulesScreen({ status, result, busy, error, onGenerate }: {
  status: Status; result: GenResult | null; busy: boolean; error: string; onGenerate: () => Promise<GenResult | null>;
}) {
  const [idx, setIdx] = useState(0);
  const [tab, setTab] = useState<"ranked" | "compare">(() => {
    try { return sessionStorage.getItem("utcp.compareCode") ? "compare" : "ranked"; } catch { return "ranked"; }
  });
  if (!status.has_data) return <div><PageHead title="Ranked schedules" /><NoData /></div>;
  const run = async () => { setIdx(0); await onGenerate(); };
  const cur: Schedule | undefined = result?.schedules[idx];

  return (
    <div>
      <PageHead title="Ranked schedules">Conflict-free combinations of your requirements, best first under your current preferences. Every schedule is built by a fixed search, not by the language model.</PageHead>
      <div className="tabs" role="tablist" aria-label="Schedule views">
        <button role="tab" aria-selected={tab === "ranked"} onClick={() => setTab("ranked")}>Ranked schedules</button>
        <button role="tab" aria-selected={tab === "compare"} onClick={() => setTab("compare")}>Compare sections of one course</button>
      </div>
      {tab === "compare" ? <ComparePanel /> : null}
      {tab === "ranked" ? (<>
      <div className="row" style={{ marginBottom: 16 }}>
        <button className="btn primary" onClick={run} disabled={busy}>{busy ? "Searching" : result ? "Search again" : "Find schedules"}</button>
        {result ? <span className="small muted">Looked at {result.searched.toLocaleString()} partial schedules.</span> : null}
      </div>
      {error ? <Note error>{error}</Note> : null}
      {result?.notes.map((n) => <div key={n} style={{ marginBottom: 8 }}><Note>{n}</Note></div>)}
      {result?.problems.length ? <Note error>{result.problems.map((p) => <p key={p}>{p}</p>)}</Note> : null}
      {result?.deferrals.length ? <DeferralNote deferrals={result.deferrals} onApplied={() => void run()} /> : null}
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
            {cur.wish_included ? <WishSummary included={cur.wish_included} /> : null}
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
      </>) : null}
    </div>
  );
}

function WishSummary({ included }: { included: string[] }) {
  const [all, setAll] = useState<string[] | null>(null);
  useEffect(() => { api<{ preferred_courses: string[] }>("/api/requirements").then((r) => setAll(r.preferred_courses)).catch(() => setAll(null)); }, []);
  if (!all || !all.length) return null;
  const left = all.filter((c) => !included.includes(c));
  return (
    <p className="small">
      <b>Like to take:</b> {included.length ? `${included.join(", ")} included` : "none included"}
      {left.length ? <span className="muted">; left out: {left.join(", ")} (they clash with higher-ranked choices, or break your credit or time limits)</span> : null}.
    </p>
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


function ComparePanel() {
  const [plan, setPlan] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [rows, setRows] = useState<Section[] | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [res, setRes] = useState<Compare | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Requirements>("/api/requirements").then((r) => {
      const codes = Array.from(new Set([...r.required_courses, ...r.preferred_courses.filter((c) => !c.startsWith("core:")), ...Object.keys(r.pinned_sections)]));
      setPlan(codes);
      let start = "";
      try { start = sessionStorage.getItem("utcp.compareCode") ?? ""; sessionStorage.removeItem("utcp.compareCode"); } catch { /* ignore */ }
      setCode(start || codes.find((c) => (r.pinned_sections[c] ?? []).length > 1) || codes[0] || "");
    }).catch((e) => setErr((e as Error).message));
  }, []);
  useEffect(() => {
    if (!code) return;
    setRes(null); setErr("");
    api<{ code: string; pinned: string[]; sections: Section[] }>(`/api/courses/sections?code=${encodeURIComponent(code)}`).then((r) => {
      const live = r.sections.filter((s) => s.status !== "cancelled");
      setRows(live);
      setTicked(new Set(r.pinned.length > 1 ? r.pinned : live.slice(0, 8).map((s) => s.unique)));
    }).catch((e) => { setRows(null); setErr((e as Error).message); });
  }, [code]);

  const run = async () => {
    setBusy(true); setErr("");
    try { setRes(await api<Compare>("/api/schedules/compare", { body: { code, uniques: [...ticked] } })); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const toggle = (u: string) => { const n = new Set(ticked); if (n.has(u)) n.delete(u); else n.add(u); setTicked(n); };
  const best = res?.rows.find((r) => r.fits);

  return (
    <div>
      <p className="lede" style={{ maxWidth: "78ch", color: "var(--muted)" }}>Pick a course and two or more of its sections. For each one the app finds the best whole schedule you could build if that is the section you get, so you can see what each choice costs the rest of your week.</p>
      <div className="row" style={{ alignItems: "end", margin: "10px 0" }}>
        <label className="field"><span>Course</span>
          <input type="text" list="plan-courses" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} style={{ width: 150 }} />
          <datalist id="plan-courses">{plan.map((c) => <option key={c} value={c} />)}</datalist></label>
        <button className="btn primary" disabled={busy || ticked.size < 2} onClick={run}>{busy ? "Comparing" : `Compare ${ticked.size} sections`}</button>
      </div>
      {err ? <Note error>{err}</Note> : null}
      {rows ? (
        <table className="t" style={{ maxWidth: 900 }}>
          <thead><tr><th>Compare</th><th>Unique</th><th>Meets</th><th>Instructor</th><th>Status</th></tr></thead>
          <tbody>{rows.map((s) => (
            <tr key={s.unique}><td><input type="checkbox" aria-label={`Compare unique ${s.unique}`} checked={ticked.has(s.unique)} onChange={() => toggle(s.unique)} /></td>
              <td className="mono">{s.unique}</td><td>{s.when}</td><td>{s.instructors.join("; ") || "Not listed"}</td><td><StatusText status={s.status} reserved={s.reserved} /></td></tr>))}</tbody>
        </table>
      ) : null}

      {res ? (
        <section className="block" style={{ marginTop: 18 }} aria-labelledby="cmp-h">
          <h2 id="cmp-h">{res.code} ({res.in_plan_as})</h2>
          <table className="t" style={{ marginTop: 8 }}>
            <thead><tr><th>Unique</th><th>Meets</th><th>Result</th><th className="num">Best schedule score</th><th className="num">Against the best section</th><th>What changes</th></tr></thead>
            <tbody>
              {res.rows.map((r) => (
                <tr key={r.unique}>
                  <td className="mono"><b>{r.unique}</b>{best && r.unique === best.unique ? <span className="good small"> Best</span> : null}</td>
                  <td>{r.section?.when}</td>
                  <td>{r.fits ? <span className="good">A schedule exists</span> : <span className="warn">No schedule with this section</span>}</td>
                  <td className="num">{r.utility !== null && r.fits ? r.utility.toFixed(3) : "none"}</td>
                  <td className="num">{r.delta !== null ? (r.delta === 0 ? "0" : r.delta.toFixed(3)) : "none"}</td>
                  <td className="small">{r.fits ? (r.why.length ? <ul style={{ margin: 0, paddingLeft: 16 }}>{r.why.map((w) => <li key={w}>{w}</li>)}</ul> : "This is the best choice.") : r.problems.map((p) => <p key={p}>{p}</p>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="grid2" style={{ marginTop: 18 }}>
            {res.rows.filter((r) => r.fits && r.schedule).map((r) => (
              <div className="stack" key={r.unique}>
                <h3>Unique {r.unique}: {r.schedule!.credits} credits, score {r.utility?.toFixed(3)}</h3>
                <Calendar compact sections={r.schedule!.sections} label={`Best weekly schedule with unique ${r.unique}`} />
                <p className="small muted">The rest of this schedule: {r.schedule!.sections.filter((s) => s.unique !== r.unique).map((s) => <span key={s.unique} className={ccClass(s.code)}><i className="swatch" aria-hidden />{s.code} {s.unique}{"  "}</span>)}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
