import { useEffect, useState } from "react";
import { Undo2 } from "lucide-react";
import { api, FEATURE_LABELS, fmtMin, fromTimeInput, toTimeInput } from "./api";
import type { DiffRow, GenResult, HistoryItem, Prefs, Proposal, Status } from "./api";
import { Note, PageHead, when } from "./ui";

const DAYS = [["M", "Mon"], ["T", "Tue"], ["W", "Wed"], ["TH", "Thu"], ["F", "Fri"]] as const;
const WEIGHTS = Object.keys(FEATURE_LABELS) as (keyof Prefs["weights"])[];

function label(path: string): string {
  const [grp, key] = path.split(".");
  if (grp === "weights") return `Weight: ${FEATURE_LABELS[key] ?? key}`;
  const map: Record<string, string> = {
    earliest_start_min: "Earliest start", latest_end_min: "Latest end", days_off: "Days off", max_gap_min: "Longest gap",
    max_walk_min: "Longest walk", credit_min: "Credit minimum", credit_max: "Credit maximum", excluded_instructors: "Excluded instructors",
    excluded_sections: "Excluded sections", excluded_times: "Excluded times",
  };
  return key === undefined ? (path === "time_bias" ? "Morning or afternoon" : path) : map[key] ?? key;
}
function show(path: string, v: unknown): string {
  if (v === null || v === undefined) return "none";
  if (path.endsWith("_start_min") || path.endsWith("_end_min")) return fmtMin(v as number);
  if (path.startsWith("weights.")) return `${Math.round((v as number) * 100)}%`;
  if (path === "time_bias") return (v as number) < -0.1 ? `Mornings (${v})` : (v as number) > 0.1 ? `Afternoons (${v})` : "No preference";
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : "none";
  return String(v);
}

export function PreferencesScreen({ status, onChanged, last }: { status: Status; onChanged: () => Promise<GenResult | null>; last: GenResult | null }) {
  const [saved, setSaved] = useState<Prefs | null>(null);
  const [draft, setDraft] = useState<Prefs | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [req, setReq] = useState("");
  const [busy, setBusy] = useState(false);
  const [prop, setProp] = useState<Proposal | null>(null);
  const [after, setAfter] = useState<string[] | null>(null);

  const load = async () => {
    const r = await api<{ config: Prefs; history: HistoryItem[] }>("/api/prefs");
    setSaved(r.config); setDraft(r.config); setHistory(r.history);
  };
  useEffect(() => { load().catch((e) => setErr((e as Error).message)); }, []);
  if (!draft || !saved) return <div><PageHead title="Preferences" />{err ? <Note error>{err}</Note> : <p className="muted">Loading.</p>}</div>;

  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const totalW = WEIGHTS.reduce((a, k) => a + draft.weights[k], 0) || 1;
  const setHard = (patch: Partial<Prefs["hard"]>) => setDraft({ ...draft, hard: { ...draft.hard, ...patch } });

  const persist = async (cfg: Prefs, note: string, path = "/api/prefs", method = "PUT") => {
    setErr(""); setMsg("");
    try {
      const r = await api<{ config: Prefs; history: HistoryItem[] }>(path, { method, body: { config: cfg, note } });
      setSaved(r.config); setDraft(r.config); setHistory(r.history);
      const gen = await onChanged();
      setAfter(gen?.change?.length ? gen.change : gen?.schedules.length ? ["The top schedule did not change."] : null);
      return true;
    } catch (e) { setErr((e as Error).message); return false; }
  };

  const propose = async () => {
    setBusy(true); setErr(""); setProp(null); setAfter(null);
    try { setProp(await api<Proposal>("/api/prefs/propose", { body: { request: req } })); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  const apply = async () => {
    if (!prop?.config) return;
    if (await persist(prop.config, `Natural language: ${req.slice(0, 120)}`, "/api/prefs/apply", "POST")) { setProp(null); setReq(""); setMsg("Applied."); }
  };
  const undo = async () => {
    const r = await api<{ config: Prefs; history: HistoryItem[] }>("/api/prefs/undo", { method: "POST" });
    setSaved(r.config); setDraft(r.config); setHistory(r.history);
    const gen = await onChanged();
    setAfter(gen?.change ?? null); setMsg("Reverted to the previous settings.");
  };

  return (
    <div>
      <PageHead title="Preferences">These settings drive every ranking. Hard constraints remove options; weights decide the order among what remains.</PageHead>
      {err ? <Note error>{err}</Note> : null}
      {msg ? <Note>{msg}</Note> : null}

      <section className="block" aria-labelledby="nl-h">
        <h2 id="nl-h">Describe what you want</h2>
        <p className="lede">Type it in plain English, for example: no classes before 10, keep Fridays free, I care more about workload than professor ratings. The language model only proposes new settings; you see exactly what would change and confirm before anything is saved. It never builds or ranks schedules.</p>
        {!status.llm_configured ? <Note><p>ANTHROPIC_API_KEY is not set, so this box is disabled. Set it in the terminal that runs the server and restart. The sliders and fields below work without it.</p></Note> : null}
        <label className="field" style={{ maxWidth: 760, marginTop: 8 }}>
          <span>Your request</span>
          <textarea rows={3} value={req} onChange={(e) => setReq(e.target.value)} disabled={!status.llm_configured} />
        </label>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary" disabled={busy || !req.trim() || !status.llm_configured} onClick={propose}>{busy ? "Reading your request" : "Propose changes"}</button>
        </div>
        {prop ? <ProposalView prop={prop} onApply={apply} onDiscard={() => setProp(null)} /> : null}
        {after && !prop ? (
          <div style={{ marginTop: 12 }}><Note><p><b>Top schedule after this change</b></p>{after.map((a) => <p key={a}>{a}</p>)}</Note></div>
        ) : null}
        {last && !last.schedules.length && after ? <p className="small warn" style={{ marginTop: 8 }}>No schedule satisfies these settings. See the Schedules screen.</p> : null}
      </section>

      <section className="block" aria-labelledby="w-h">
        <h2 id="w-h">How much each factor matters</h2>
        <p className="lede">Drag to set relative importance. Percentages are what the sliders become after they are scaled to total 100%.</p>
        <div style={{ maxWidth: 760 }}>
          {WEIGHTS.map((k) => (
            <div className="slider-row" key={k}>
              <label htmlFor={`w-${k}`}>{FEATURE_LABELS[k]}</label>
              <input id={`w-${k}`} type="range" min={0} max={100} value={Math.round(draft.weights[k] * 100)}
                onChange={(e) => setDraft({ ...draft, weights: { ...draft.weights, [k]: Number(e.target.value) / 100 } })} />
              <span className="pct">{Math.round((draft.weights[k] / totalW) * 100)}%</span>
            </div>
          ))}
          <div className="slider-row">
            <label htmlFor="bias">Morning or afternoon (used by time-of-day fit)</label>
            <input id="bias" type="range" min={-100} max={100} value={Math.round(draft.time_bias * 100)} onChange={(e) => setDraft({ ...draft, time_bias: Number(e.target.value) / 100 })} />
            <span className="pct">{draft.time_bias < -0.1 ? "AM" : draft.time_bias > 0.1 ? "PM" : "None"}</span>
          </div>
          {!status.buildings_loaded ? <p className="small muted" style={{ marginTop: 8 }}>Short walks has no effect until building coordinates are loaded into data/buildings.csv (columns code, lat, lon).</p> : null}
        </div>
      </section>

      <section className="block" aria-labelledby="h-h">
        <h2 id="h-h">Hard constraints</h2>
        <div className="grid2" style={{ marginTop: 10 }}>
          <div className="stack">
            <div className="row">
              <label className="field"><span>Credit hours, minimum</span><input type="number" min={0} max={30} value={draft.hard.credit_min} onChange={(e) => setHard({ credit_min: Number(e.target.value) })} style={{ width: 90 }} /></label>
              <label className="field"><span>Credit hours, maximum</span><input type="number" min={0} max={30} value={draft.hard.credit_max} onChange={(e) => setHard({ credit_max: Number(e.target.value) })} style={{ width: 90 }} /></label>
            </div>
            <div className="row">
              <label className="field"><span>No class starts before</span><input type="time" value={toTimeInput(draft.hard.earliest_start_min)} onChange={(e) => setHard({ earliest_start_min: fromTimeInput(e.target.value) })} /></label>
              <label className="field"><span>No class ends after</span><input type="time" value={toTimeInput(draft.hard.latest_end_min)} onChange={(e) => setHard({ latest_end_min: fromTimeInput(e.target.value) })} /></label>
            </div>
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="small" style={{ fontWeight: 500, marginBottom: 4 }}>Days with no class</legend>
              <div className="row">
                {DAYS.map(([d, n]) => (
                  <label className="check" key={d}><input type="checkbox" checked={draft.hard.days_off.includes(d)}
                    onChange={() => setHard({ days_off: draft.hard.days_off.includes(d) ? draft.hard.days_off.filter((x) => x !== d) : [...draft.hard.days_off, d] })} />{n}</label>
                ))}
              </div>
            </fieldset>
            <div className="row">
              <label className="field"><span>Longest gap between classes (minutes)</span><input type="number" min={0} max={720} value={draft.hard.max_gap_min ?? ""} placeholder="no limit"
                onChange={(e) => setHard({ max_gap_min: e.target.value === "" ? null : Number(e.target.value) })} style={{ width: 130 }} /></label>
              <label className="field"><span>Longest walk between classes (minutes)</span><input type="number" min={0} max={60} disabled={!status.buildings_loaded} value={draft.hard.max_walk_min ?? ""} placeholder={status.buildings_loaded ? "no limit" : "needs building data"}
                onChange={(e) => setHard({ max_walk_min: e.target.value === "" ? null : Number(e.target.value) })} style={{ width: 150 }} /></label>
            </div>
          </div>
          <div className="stack">
            <label className="field"><span>Exclude instructors (one per line, LAST, FIRST or First Last)</span>
              <textarea rows={3} defaultValue={draft.hard.excluded_instructors.join("\n")} key={`i-${saved.hard.excluded_instructors.join()}`}
                onBlur={(e) => setHard({ excluded_instructors: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} /></label>
            <label className="field"><span>Exclude sections by unique number (one per line)</span>
              <textarea rows={2} defaultValue={draft.hard.excluded_sections.join("\n")} key={`s-${saved.hard.excluded_sections.join()}`}
                onBlur={(e) => setHard({ excluded_sections: e.target.value.split(/[\s,]+/).filter(Boolean) })} /></label>
            {draft.hard.excluded_times.length ? (
              <p className="small">Excluded times: {draft.hard.excluded_times.map((t) => `${t.days.join("")} ${fmtMin(t.start_min)} to ${fmtMin(t.end_min)}`).join("; ")}{" "}
                <button className="btn text" onClick={() => setHard({ excluded_times: [] })}>Clear</button></p>
            ) : <p className="small muted">Excluded time blocks can be set by describing them in the box above, for example no classes Tuesday or Thursday from noon to 2.</p>}
          </div>
        </div>
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn primary" disabled={!dirty} onClick={() => persist(draft, "Edited in settings")}>Save settings</button>
          <button className="btn" disabled={!dirty} onClick={() => setDraft(saved)}>Discard edits</button>
          {dirty ? <span className="small warn">Unsaved changes</span> : null}
        </div>
      </section>

      <section className="block" aria-labelledby="hist-h">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 id="hist-h">History</h2>
          <button className="btn" onClick={undo} disabled={history.length < 2}><Undo2 size={14} aria-hidden /> Undo last change</button>
        </div>
        {history.length ? (
          <table className="t" style={{ marginTop: 8, maxWidth: 760 }}>
            <thead><tr><th>When</th><th>Change</th></tr></thead>
            <tbody>{history.map((h) => <tr key={h.id}><td style={{ whiteSpace: "nowrap" }}>{when(h.at)}</td><td>{h.note}</td></tr>)}</tbody>
          </table>
        ) : <p className="muted small">Nothing saved yet. Defaults are in use.</p>}
      </section>
    </div>
  );
}

function ProposalView({ prop, onApply, onDiscard }: { prop: Proposal; onApply: () => void; onDiscard: () => void }) {
  return (
    <div style={{ marginTop: 14, maxWidth: 900 }} className="stack">
      {prop.question ? <Note><p><b>One question before changing anything</b></p><p>{prop.question}</p><p className="small muted">Answer it in the box above and propose again.</p></Note> : null}
      {prop.tradeoff ? <Note><p><b>Tradeoff</b></p><p>{prop.tradeoff}</p></Note> : null}
      {prop.config ? (
        prop.diff.length ? (
          <>
            <table className="t">
              <thead><tr><th>Setting</th><th>Now</th><th>Proposed</th><th>Your words</th><th>Reason</th></tr></thead>
              <tbody>{prop.diff.map((d: DiffRow) => (
                <tr key={d.path}><td>{label(d.path)}</td><td>{show(d.path, d.old)}</td><td><b>{show(d.path, d.new)}</b></td><td>{d.phrase ? `"${d.phrase}"` : <span className="muted">not quoted</span>}</td><td>{d.rationale}</td></tr>
              ))}</tbody>
            </table>
            <div className="row"><button className="btn primary" onClick={onApply}>Apply these changes</button><button className="btn" onClick={onDiscard}>Discard</button></div>
          </>
        ) : <Note>The proposal changes nothing from your current settings.</Note>
      ) : null}
    </div>
  );
}
