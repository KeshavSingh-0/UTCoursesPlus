import { useState } from "react";
import { api, ApiError } from "./api";
import type { CoreArea, Requirements as Req } from "./api";
import { Note } from "./ui";

type Course = { code: string; title: string; grade: string; term: string; credits: number; in_progress: boolean; alias: boolean };
type Need = { codes: string[]; names: string[]; required_hours: number; lacking_hours: number; text: string };
type Rule = { section: string; text: string; segments: string[][]; lacking: number | null; unit: string };
type Total = { text: string; required: number | null; counted: number | null; lacking: number | null; unit: string };
type Parsed = {
  courses: Course[]; completed_codes: string[]; core_needs: Need[]; course_rules: Rule[];
  notes: { section: string; text: string; lacking: number | null; unit: string }[]; totals: Total[]; program: string | null; warnings: string[];
};
type Mode = "required" | "like" | "defer";

export function IdaImport({ areas, onApplied }: { areas: CoreArea[]; onApplied: (r: Req) => void }) {
  const [res, setRes] = useState<Parsed | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string[]>([]);
  const [core, setCore] = useState<Record<string, Mode>>({});
  const [rules, setRules] = useState<Record<number, Mode>>({});

  const nameOf = (c: string) => areas.find((a) => a.code === c)?.name ?? c;

  const read = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true); setErr(""); setDone([]);
    try {
      const html = await file.text();
      const r = await api<Parsed>("/api/requirements/ida/parse", { body: { html } });
      setRes(r);
      const m: Record<string, Mode> = {};
      for (const n of r.core_needs) for (const c of n.codes) m[c] = "like";
      setCore(m);
      setRules({});
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!res) return;
    const hours: Record<string, number> = {};
    for (const n of res.core_needs) for (const c of n.codes) hours[c] = Math.max(hours[c] ?? 0, n.lacking_hours);
    const body = {
      completed: res.completed_codes,
      core,
      core_hours: hours,
      rules: res.course_rules.map((r, i) => ({ segments: r.segments, mode: rules[i] ?? "defer", text: r.text })),
    };
    const r = await api<{ requirements: Req; warnings: string[] }>("/api/requirements/ida/apply", { body });
    onApplied(r.requirements);
    setDone(r.warnings.length ? r.warnings : ["Saved."]);
    setRes(null);
  };

  return (
    <section className="block" aria-labelledby="ida-h">
      <h2 id="ida-h">Import your degree audit results</h2>
      <p className="lede">Save your audit's Results page from the browser (File, Save Page As, HTML) and choose the file. It is read on this computer without a language model. Courses you have finished or are taking now are hidden from search and plans. Your name and EID are never read or stored, and the file is not kept.</p>
      <label className="field">
        <span>Audit results file</span>
        <input type="file" accept=".html,.htm,text/html" disabled={busy} onChange={(e) => void read(e.target.files?.[0])} />
      </label>
      {err ? <div style={{ marginTop: 10 }}><Note error>{err}</Note></div> : null}
      {done.length ? <div style={{ marginTop: 10 }}><Note>{done.map((d) => <p key={d}>{d}</p>)}</Note></div> : null}
      {res ? (
        <div style={{ marginTop: 14 }}>
          {res.program ? <p className="small muted">{res.program}</p> : null}
          {res.totals.length ? (
            <ul className="small" style={{ marginTop: 6 }}>
              {res.totals.map((t, i) => <li key={i}>{t.text}: {t.counted ?? "?"} of {t.required ?? "?"} {t.unit}, {t.lacking ?? 0} lacking</li>)}
            </ul>
          ) : null}
          <p className="small" style={{ marginTop: 8 }}>{res.completed_codes.length} courses finished or in progress will be excluded: <span className="mono">{res.completed_codes.join(", ")}</span></p>

          {res.core_needs.length ? (
            <>
              <h3 style={{ marginTop: 14 }}>Core requirements still open</h3>
              <table className="t" style={{ marginTop: 6 }}>
                <thead><tr><th>Core area</th><th>Hours lacking</th><th>This semester</th></tr></thead>
                <tbody>
                  {res.core_needs.flatMap((n) => n.codes.map((c) => (
                    <tr key={`${n.text}-${c}`}>
                      <td>{nameOf(c)} <span className="mono muted">{c}</span></td>
                      <td>{n.lacking_hours}</td>
                      <td>
                        <select aria-label={`Mode for ${nameOf(c)}`} value={core[c] ?? "like"} onChange={(e) => setCore({ ...core, [c]: e.target.value as Mode })}>
                          <option value="required">Required now</option>
                          <option value="like">Like to take</option>
                          <option value="defer">Not this semester</option>
                        </select>
                      </td>
                    </tr>
                  )))}
                </tbody>
              </table>
            </>
          ) : null}

          {res.course_rules.length ? (
            <>
              <h3 style={{ marginTop: 14 }}>Course requirements still open</h3>
              <table className="t" style={{ marginTop: 6 }}>
                <thead><tr><th>Requirement</th><th>Options</th><th>This semester</th></tr></thead>
                <tbody>
                  {res.course_rules.map((r, i) => (
                    <tr key={i}>
                      <td>{r.text}</td>
                      <td className="mono">{r.segments.map((s) => s.join(" or ")).join("; ")}</td>
                      <td>
                        <select aria-label={`Mode for ${r.text}`} value={rules[i] ?? "defer"} onChange={(e) => setRules({ ...rules, [i]: e.target.value as Mode })}>
                          <option value="required">Required now</option>
                          <option value="defer">Not this semester</option>
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}

          {res.notes.length ? (
            <details style={{ marginTop: 10 }}>
              <summary>Other open items ({res.notes.length})</summary>
              <ul className="small">{res.notes.map((n, i) => <li key={i}>{n.section}: {n.text}</li>)}</ul>
            </details>
          ) : null}
          {res.warnings.length ? <div style={{ marginTop: 10 }}><Note>{res.warnings.map((w) => <p key={w}>{w}</p>)}</Note></div> : null}

          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn primary" onClick={() => void apply()}>Save</button>
            <button className="btn" onClick={() => setRes(null)}>Discard</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
