import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, Copy, RotateCcw, SkipForward } from "lucide-react";
import type { GenResult, RegOption, RegStep, Status } from "./api";
import { NoData, Note, PageHead, StatusText } from "./ui";
import {
  chosen, clashWithPending, clashWithRegistered, confirm, initialState, moveCourse, moveOption, planKey, progress, skip, undo,
} from "./runner.ts";
import type { RunState } from "./runner.ts";

const AUTOCOPY_KEY = "utcp.autocopy";
const stateKey = (k: string) => `utcp.runner.v2:${k}`;

async function copyText(t: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(t);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = t;
    ta.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}
const read = <T,>(k: string, fallback: T): T => {
  try { const v = localStorage.getItem(k); return v ? (JSON.parse(v) as T) : fallback; } catch { return fallback; }
};
const write = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } };

export function RegistrationScreen({ status, result }: { status: Status; result: GenResult | null }) {
  if (!status.has_data) return <div><PageHead title="Registration plan" /><NoData /></div>;
  const plan = result?.registration;
  return (
    <div>
      <PageHead title="Registration plan">A keyboard runner and a map of every fallback, for you to carry out by hand on UT's registration site. This app never registers, drops or joins waitlists for you.</PageHead>
      {!plan ? <Note><p>No plan yet. Find schedules on the Ranked schedules screen first; the plan is built from the top schedule.</p></Note> : (
        <>
          <section aria-label="Registration time" style={{ marginBottom: 12 }}>
            <p><b>Registration time:</b> {plan.registration_time ?? <span className="muted">not entered. Add it on the Requirements screen.</span>}</p>
            <p className="small muted" style={{ marginTop: 4, maxWidth: "75ch" }}>{plan.label} Seat status was read when the schedule was fetched and may have changed since, so check the live status as you go.</p>
          </section>
          <Runner steps={plan.steps} result={result} />
        </>
      )}
    </div>
  );
}

function Runner({ steps, result }: { steps: RegStep[]; result: GenResult | null }) {
  const key = useMemo(() => planKey(steps), [steps]);
  const [st, setSt] = useState<RunState>(() => read(stateKey(key), initialState()));
  const [auto, setAuto] = useState<boolean>(() => read(AUTOCOPY_KEY, true));
  const [copied, setCopied] = useState("");
  const ref = useRef(st);
  ref.current = st;

  useEffect(() => { setSt(read(stateKey(key), initialState())); }, [key]);
  useEffect(() => { write(stateKey(key), st); }, [key, st]);
  useEffect(() => { write(AUTOCOPY_KEY, auto); }, [auto]);

  const say = useCallback((unique: string, ok: boolean) => {
    setCopied(ok ? `Copied ${unique}` : "Could not copy. Select the number and copy it by hand.");
    window.setTimeout(() => setCopied(""), 2500);
  }, []);
  const copyCurrent = useCallback(async (s: RunState) => {
    const step = steps[s.cur];
    if (!step) return;
    const u = chosen(step, s).unique;
    say(u, await copyText(u));
  }, [steps, say]);

  const act = useCallback((fn: (s: RunState) => RunState, copyAfter: boolean) => {
    const prev = ref.current;
    const next = fn(prev);
    if (next === prev) return;
    setSt(next);
    ref.current = next;
    const before = steps[prev.cur] && chosen(steps[prev.cur], prev).unique;
    const after = steps[next.cur] && chosen(steps[next.cur], next).unique;
    if (copyAfter && auto && after && (after !== before || next.cur !== prev.cur)) void copyCurrent(next);
  }, [steps, auto, copyCurrent]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((t.tagName === "BUTTON" || t.tagName === "A") && (e.key === " " || e.key === "Enter")) return; // let the focused control act
      const k = e.key;
      if (k === " ") { e.preventDefault(); act((s) => confirm(steps, s), true); }
      else if (k === "ArrowRight") { e.preventDefault(); act((s) => moveOption(steps, s, 1), true); }
      else if (k === "ArrowLeft") { e.preventDefault(); act((s) => moveOption(steps, s, -1), true); }
      else if (k === "ArrowDown") { e.preventDefault(); act((s) => moveCourse(steps, s, 1), true); }
      else if (k === "ArrowUp") { e.preventDefault(); act((s) => moveCourse(steps, s, -1), true); }
      else if (k === "c" || k === "C") { e.preventDefault(); void copyCurrent(ref.current); }
      else if (k === "x" || k === "X") { e.preventDefault(); act((s) => skip(steps, s), true); }
      else if (k === "Backspace" || k === "u" || k === "U") { e.preventDefault(); act((s) => undo(steps, s), true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [steps, act, copyCurrent]);

  const pr = progress(steps, st);
  const finished = pr.remaining === 0;
  const step = steps[st.cur];
  const opt = step ? chosen(step, st) : null;
  const idx = step ? st.choice[step.code] ?? 0 : 0;
  const reg = steps.filter((s) => typeof st.done[s.code] === "string").map((s) => `${s.code}: ${st.done[s.code]}`);

  return (
    <>
      <section className="block" aria-labelledby="run-h">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 id="run-h">Runner</h2>
          <p className="small muted">{pr.registered} registered, {pr.skipped} skipped, {pr.remaining} to go</p>
        </div>
        <p className="small" style={{ margin: "4px 0 12px" }} aria-label="Keyboard shortcuts">
          <kbd>Space</kbd> got it, next course &nbsp; <kbd>→</kbd> <kbd>←</kbd> next or previous option if a section filled &nbsp; <kbd>↓</kbd> <kbd>↑</kbd> change course &nbsp;
          <kbd>C</kbd> copy the unique number &nbsp; <kbd>X</kbd> skip course &nbsp; <kbd>Backspace</kbd> undo
        </p>
        <div className="runner" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)", gap: 28, alignItems: "start" }}>
          <div>
            {finished || !step || !opt ? (
              <div>
                <h3>All courses handled</h3>
                <p style={{ marginTop: 6 }}>{reg.length ? `Registered: ${reg.join("; ")}.` : "Nothing registered."}</p>
                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn" onClick={() => act((s) => undo(steps, s), false)}>Undo last</button>
                  <button className="btn" onClick={() => setSt(initialState())}><RotateCcw size={14} aria-hidden /> Start over</button>
                </div>
              </div>
            ) : (
              <CurrentCard step={step} opt={opt} idx={idx} st={st} steps={steps}
                onCopy={() => void copyCurrent(st)} onConfirm={() => act((s) => confirm(steps, s), true)}
                onSkip={() => act((s) => skip(steps, s), true)} onUndo={() => act((s) => undo(steps, s), true)}
                onMove={(d) => act((s) => moveOption(steps, s, d), true)} />
            )}
            <p className="small" style={{ marginTop: 10, minHeight: "1.4em" }} role="status" aria-live="polite">{copied}</p>
            <label className="check small" style={{ marginTop: 6 }}>
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              <span>Copy the unique number automatically whenever the highlighted option changes</span>
            </label>
          </div>
          <ol className="list-plain" aria-label="Courses in registration order">
            {steps.map((s, i) => {
              const d = st.done[s.code];
              return (
                <li key={s.code} aria-current={i === st.cur && !finished ? "step" : undefined}
                  style={{ display: "grid", gridTemplateColumns: "22px 1fr auto", gap: 8, padding: "6px 4px", borderBottom: "1px solid var(--line)", background: i === st.cur && !finished ? "var(--primary-tint)" : undefined }}>
                  <span className="mono small">{s.order}.</span>
                  <button className="btn text" style={{ justifyContent: "flex-start", height: "auto", padding: 0 }} onClick={() => act((x) => ({ ...x, cur: i }), true)}>{s.code}</button>
                  <span className="small">{typeof d === "string" ? <span className="st-open">Registered {d}</span> : d === null ? <span className="muted">Skipped</span> : <span className="muted">Next up: {chosen(s, st).unique}</span>}</span>
                </li>
              );
            })}
          </ol>
        </div>
      </section>
      <PlanTree steps={steps} st={st} result={result} onPick={(i, o) => act((x) => ({ ...x, cur: i, choice: { ...x.choice, [steps[i].code]: o } }), true)} />
    </>
  );
}

function CurrentCard({ step, opt, idx, st, steps, onCopy, onConfirm, onSkip, onUndo, onMove }: {
  step: RegStep; opt: RegOption; idx: number; st: RunState; steps: RegStep[];
  onCopy: () => void; onConfirm: () => void; onSkip: () => void; onUndo: () => void; onMove: (d: 1 | -1) => void;
}) {
  const clashReg = clashWithRegistered(steps, st, step, opt);
  const clashPlan = clashWithPending(steps, st, step, opt);
  const n = step.options.length;
  return (
    <div>
      <p className="small muted">Course {step.order} of {steps.length}</p>
      <h3 style={{ marginTop: 2 }}>{step.code} <span style={{ fontWeight: 400 }}>{step.title}</span></h3>
      <div style={{ margin: "10px 0" }}>
        <p className="small muted">{idx === 0 ? "Planned section" : `Fallback ${idx} of ${n - 1}`} (option {idx + 1} of {n})</p>
        <p className="mono" style={{ fontSize: "2.25rem", lineHeight: 1.15, fontWeight: 400 }} aria-label={`Unique number ${opt.unique}`}>{opt.unique}</p>
        <p style={{ marginTop: 4 }}>{opt.when}</p>
        <p className="small" style={{ marginTop: 2 }}><StatusText status={opt.status} reserved={opt.reserved} /> when the schedule was fetched{opt.instructors.length ? `, ${opt.instructors.join("; ")}` : ""}.</p>
        {clashReg.length ? <p className="small warn" style={{ marginTop: 4 }}>Overlaps a section you already registered for {clashReg.join(", ")}.</p> : null}
        {clashPlan.length ? <p className="small warn" style={{ marginTop: 4 }}>Overlaps the section currently planned for {clashPlan.join(", ")}. Choosing it means changing that course too.</p> : null}
      </div>
      <div className="row">
        <button className="btn primary" onClick={onConfirm}><Check size={14} aria-hidden /> Got it (Space)</button>
        <button className="btn" onClick={() => onMove(-1)} disabled={n < 2}>Previous option (←)</button>
        <button className="btn" onClick={() => onMove(1)} disabled={n < 2}>Next option (→)</button>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn" onClick={onCopy}><Copy size={14} aria-hidden /> Copy unique number (C)</button>
        <button className="btn" onClick={onSkip}><SkipForward size={14} aria-hidden /> Skip course (X)</button>
        <button className="btn" onClick={onUndo} disabled={!st.log.length}>Undo (Backspace)</button>
      </div>
    </div>
  );
}

function PlanTree({ steps, st, result, onPick }: { steps: RegStep[]; st: RunState; result: GenResult | null; onPick: (stepIdx: number, optIdx: number) => void }) {
  const top = result?.schedules[0];
  const topSet = new Set(top?.sections.map((s) => s.unique));
  return (
    <section className="block" aria-labelledby="tree-h">
      <h2 id="tree-h">Every case</h2>
      <p className="lede">Read left to right. Each course starts with the section the plan wants. If it fills, move to the next box, which is the best remaining section that still fits the rest of the plan. Click a box to jump to it in the runner.</p>
      <div className="rtree">
        <p className="root">Registration opens</p>
        <ul className="branches">
          {steps.map((s, i) => {
            const d = st.done[s.code];
            return (
              <li className="branch" key={s.code}>
                <div className="blabel"><b>{s.order}. {s.code}</b><span className="small muted" style={{ display: "block" }}>{s.title}</span></div>
                <div className="chain">
                  {s.options.map((o, j) => {
                    const isCur = i === st.cur && (st.choice[s.code] ?? 0) === j && d === undefined;
                    const isDone = d === o.unique;
                    return (
                      <div className="step" key={o.unique}>
                        {j > 0 ? <span className="link" aria-hidden><span>if full</span><span className="line" /></span> : null}
                        <button className={`node${isCur ? " cur" : ""}${isDone ? " done" : ""}`} onClick={() => onPick(i, j)}
                          aria-label={`${s.code} option ${j + 1}, unique ${o.unique}${isDone ? ", registered" : ""}`}>
                          <span className="mono">{o.unique}</span>{" "}
                          {isDone ? <b>Registered</b> : <StatusText status={o.status} reserved={o.reserved} />}
                          <span className="small muted" style={{ display: "block" }}>{o.when}</span>
                          {o.instructors.length ? <span className="small muted" style={{ display: "block" }}>{o.instructors.join("; ")}</span> : null}
                          {o.conflicts.length ? <span className="small warn" style={{ display: "block" }}>Overlaps the plan for {o.conflicts.join(", ")}</span> : null}
                        </button>
                      </div>
                    );
                  })}
                  <div className="step">
                    <span className="link" aria-hidden><span>none left</span><span className="line" /></span>
                    <span className="node end small muted">Take a backup schedule or ask an advisor</span>
                  </div>
                </div>
              </li>
            );
          })}
          {result?.backups.length ? (
            <li className="branch">
              <div className="blabel"><b>If the plan falls apart</b><span className="small muted" style={{ display: "block" }}>Whole backup schedules</span></div>
              <div className="chain">
                {result.backups.map((b, j) => (
                  <div className="step" key={j}>
                    {j > 0 ? <span className="link" aria-hidden><span>or</span><span className="line" /></span> : null}
                    <div className="node">
                      <b>Backup {j + 1}</b>
                      <span className="small muted" style={{ display: "block" }}>{b.credits} credits</span>
                      {b.sections.map((s) => (
                        <span key={s.unique} className="small" style={{ display: "block" }}>
                          <span className="mono">{s.unique}</span> {s.code}{topSet.has(s.unique) ? <span className="muted"> (same as plan)</span> : null}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </li>
          ) : null}
        </ul>
      </div>
    </section>
  );
}
