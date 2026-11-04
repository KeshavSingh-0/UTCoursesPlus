import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Copy, RotateCcw, SkipForward, Undo2 } from "lucide-react";
import { api } from "./api";
import type { DropAdvice, GenResult, RegOption, RegPlan, RegStep, Replan, Status } from "./api";
import { NoData, Note, PageHead, StatusText } from "./ui";
import {
  dropSections, empty, full, got, lastCode, nextCursor, planKey, progress, requestBody, skipCourse, touched, undo,
} from "./runner.ts";
import type { Action, Adapt } from "./runner.ts";

const AUTOCOPY_KEY = "utcp.autocopy";
const stateKey = (k: string) => `utcp.adapt.v1:${k}`;

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
      <PageHead title="Registration plan">A keyboard runner that adapts as you go. Tell it what you got and what was full, and it searches again, so the next steps already account for what you missed. It never registers, drops or joins waitlists for you.</PageHead>
      {!plan ? <Note><p>No plan yet. Find schedules on the Ranked schedules screen first; the plan is built from the top schedule.</p></Note> : (
        <>
          <section aria-label="Registration time" style={{ marginBottom: 12 }}>
            <p><b>Registration time:</b> {plan.registration_time ?? <span className="muted">not entered. Add it on the Requirements screen.</span>}</p>
            <p className="small muted" style={{ marginTop: 4, maxWidth: "75ch" }}>{plan.label} Seat status was read when the schedule was fetched and may have changed since, so check the live status as you go.</p>
          </section>
          <Runner initial={plan} result={result} />
        </>
      )}
    </div>
  );
}

function Runner({ initial, result }: { initial: RegPlan; result: GenResult | null }) {
  const key = planKey(initial.steps);
  const [ad, setAd] = useState<Adapt>(() => read(stateKey(key), empty()));
  const [plan, setPlan] = useState<Replan | null>(null);
  const [cur, setCur] = useState(0);
  const [pick, setPick] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [auto, setAuto] = useState<boolean>(() => read(AUTOCOPY_KEY, true));
  const [copied, setCopied] = useState("");

  const steps: RegStep[] = plan ? plan.registration?.steps ?? [] : initial.steps;
  const step = steps[Math.min(cur, steps.length - 1)];
  const opt: RegOption | undefined = step ? step.options[pick[step.code] ?? 0] ?? step.options[0] : undefined;
  const refs = useRef({ ad, steps, step, opt, busy });
  refs.current = { ad, steps, step, opt, busy };

  useEffect(() => { write(stateKey(key), ad); }, [key, ad]);
  useEffect(() => { write(AUTOCOPY_KEY, auto); }, [auto]);

  const search = useCallback(async (next: Adapt, action: Action | "undo" | "load", code?: string) => {
    setBusy(true); setErr("");
    const oldSteps = refs.current.steps;
    try {
      const r = await api<Replan>("/api/plan/replan", { body: requestBody(next, oldSteps.map((s) => s.options[0].unique)) });
      setAd(next); setPlan(r); setPick({});
      const ns = r.registration?.steps ?? [];
      setCur(action === "load" ? 0 : nextCursor(oldSteps, code, action, ns));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { if (touched(ad)) void search(ad, "load"); /* once, to restore a saved session */ }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const say = useCallback((unique: string, ok: boolean) => {
    setCopied(ok ? `Copied ${unique}` : "Could not copy. Select the number and copy it by hand.");
    window.setTimeout(() => setCopied(""), 2500);
  }, []);
  const copyCurrent = useCallback(async () => {
    const o = refs.current.opt;
    if (o) say(o.unique, await copyText(o.unique));
  }, [say]);

  // copy the number whenever the highlighted option changes, but not when the screen first opens
  const lastShown = useRef(opt?.unique);
  useEffect(() => {
    if (opt && opt.unique !== lastShown.current && auto && !busy) void copyCurrent();
    lastShown.current = opt?.unique;
  }, [opt?.unique, auto, busy]); // eslint-disable-line react-hooks/exhaustive-deps

  const doGot = useCallback(() => { const r = refs.current; if (r.opt && r.step && !r.busy) void search(got(r.ad, r.opt.unique, r.step.code), "got", r.step.code); }, [search]);
  const doFull = useCallback(() => { const r = refs.current; if (r.opt && r.step && !r.busy) void search(full(r.ad, r.opt.unique, r.step.code), "full", r.step.code); }, [search]);
  const doSkip = useCallback(() => { const r = refs.current; if (r.step && !r.busy) void search(skipCourse(r.ad, r.step.code), "skip", r.step.code); }, [search]);
  const doUndo = useCallback(() => { const r = refs.current; if (r.ad.history.length && !r.busy) void search(undo(r.ad), "undo", lastCode(r.ad) ?? r.step?.code); }, [search]);
  const doDrop = (d: DropAdvice) => { if (!busy) void search(dropSections(ad, d.drop.map((x) => x.unique)), "drop", step?.code); };
  const startOver = () => { setPlan(null); setAd(empty()); setCur(0); setPick({}); setErr(""); };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((t.tagName === "BUTTON" || t.tagName === "A") && (e.key === " " || e.key === "Enter")) return; // let the focused control act
      const k = e.key.toLowerCase();
      if (k === " ") { e.preventDefault(); doGot(); }
      else if (k === "arrowright" || k === "f") { e.preventDefault(); doFull(); }
      else if (k === "arrowleft" || k === "backspace" || k === "u") { e.preventDefault(); doUndo(); }
      else if (k === "arrowdown") { e.preventDefault(); setCur((c) => Math.min(refs.current.steps.length - 1, c + 1)); }
      else if (k === "arrowup") { e.preventDefault(); setCur((c) => Math.max(0, c - 1)); }
      else if (k === "c") { e.preventDefault(); void copyCurrent(); }
      else if (k === "x") { e.preventDefault(); doSkip(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doGot, doFull, doUndo, doSkip, copyCurrent]);

  const pr = progress(ad, steps);
  const st = plan?.status ?? "ok";
  const blocked = st === "drop_needed" || st === "stuck";
  const registered = plan ? plan.registered : [];

  return (
    <>
      {err ? <Note error><p>{err}</p></Note> : null}
      {plan?.changes.length ? (
        <section className="block" aria-labelledby="chg-h">
          <h2 id="chg-h">What changed</h2>
          <ul className="small" style={{ marginTop: 6 }}>{plan.changes.map((c) => <li key={c}>{c}</li>)}</ul>
        </section>
      ) : null}
      {blocked ? <DropPanel plan={plan!} onDrop={doDrop} onUndo={doUndo} canUndo={!!ad.history.length} busy={busy} onStartOver={startOver} /> : null}
      {st === "better_if_dropped" ? <DropPanel plan={plan!} onDrop={doDrop} busy={busy} optional /> : null}
      {st === "complete" ? <Note><p>Every course in the plan is registered. Nothing is left to try.</p></Note> : null}

      {!blocked ? (
        <section className="block" aria-labelledby="run-h">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2 id="run-h">Runner</h2>
            <p className="small muted" role="status">{busy ? "Updating the plan" : `${pr.registered} registered, ${pr.skipped} given up, ${pr.remaining} to go`}</p>
          </div>
          <p className="small" style={{ margin: "4px 0 12px" }} aria-label="Keyboard shortcuts">
            <kbd>Space</kbd> got it &nbsp; <kbd>→</kbd> it was full, update the plan &nbsp; <kbd>←</kbd> undo the last report &nbsp; <kbd>↓</kbd> <kbd>↑</kbd> change course &nbsp;
            <kbd>C</kbd> copy the unique number &nbsp; <kbd>X</kbd> give up on this course
          </p>
          <div className="runner" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)", gap: 28, alignItems: "start" }}>
            <div>
              {!step || !opt ? (
                <div>
                  <h3>{st === "complete" ? "All courses handled" : "Nothing left to register"}</h3>
                  <p style={{ marginTop: 6 }}>{registered.length ? `Registered: ${registered.map((r) => `${r.code} ${r.unique}`).join("; ")}.` : "Nothing registered."}</p>
                  <div className="row" style={{ marginTop: 12 }}>
                    <button className="btn" onClick={doUndo} disabled={!ad.history.length || busy}>Undo last</button>
                    <button className="btn" onClick={startOver}><RotateCcw size={14} aria-hidden /> Start over</button>
                  </div>
                </div>
              ) : (
                <CurrentCard step={step} opt={opt} idx={pick[step.code] ?? 0} total={steps.length} busy={busy} canUndo={!!ad.history.length}
                  onCopy={() => void copyCurrent()} onGot={doGot} onFull={doFull} onSkip={doSkip} onUndo={doUndo} />
              )}
              <p className="small" style={{ marginTop: 10, minHeight: "1.4em" }} role="status" aria-live="polite">{copied}</p>
              <label className="check small" style={{ marginTop: 6 }}>
                <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
                <span>Copy the unique number automatically whenever the highlighted option changes</span>
              </label>
            </div>
            <div>
              {registered.length ? (
                <>
                  <h3 style={{ fontSize: "0.95rem" }}>Registered so far ({plan?.credits_registered} credits)</h3>
                  <ul className="list-plain small" style={{ margin: "4px 0 12px" }}>
                    {registered.map((r) => <li key={r.unique} style={{ padding: "3px 0" }}><span className="st-open mono">{r.unique}</span> {r.code} <span className="muted">{r.when}</span></li>)}
                  </ul>
                </>
              ) : null}
              <ol className="list-plain" aria-label="Courses still to register, in order">
                {steps.map((s, i) => (
                  <li key={s.code} aria-current={i === cur ? "step" : undefined}
                    style={{ display: "grid", gridTemplateColumns: "22px 1fr auto", gap: 8, padding: "6px 4px", borderBottom: "1px solid var(--line)", background: i === cur ? "var(--primary-tint)" : undefined }}>
                    <span className="mono small">{s.order}.</span>
                    <button className="btn text" style={{ justifyContent: "flex-start", height: "auto", padding: 0 }} onClick={() => setCur(i)}>{s.code}</button>
                    <span className="small muted">Next up: {(s.options[pick[s.code] ?? 0] ?? s.options[0]).unique}</span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </section>
      ) : null}
      {steps.length && !blocked ? (
        <PlanTree steps={steps} cur={cur} pick={pick} result={result} onPick={(i, o) => { setCur(i); setPick({ ...pick, [steps[i].code]: o }); }} />
      ) : null}
    </>
  );
}

function DropPanel({ plan, onDrop, onUndo, canUndo, busy, optional, onStartOver }: {
  plan: Replan; onDrop: (d: DropAdvice) => void; onUndo?: () => void; canUndo?: boolean; busy: boolean; optional?: boolean; onStartOver?: () => void;
}) {
  return (
    <section className="block" aria-labelledby="drop-h">
      <h2 id="drop-h">{optional ? "Optional: a better plan exists if you drop a section" : plan.status === "stuck" ? "No plan fits" : "Drop a section to keep going"}</h2>
      {optional ? (
        <p className="lede">Your registered sections still work, so you do not have to. Dropping one would let the plan reach a higher-scoring schedule. The gain is in the same units as the schedule score.</p>
      ) : plan.status === "stuck" ? (
        <>
          <p className="lede">{plan.problems[0]}</p>
          <div className="row" style={{ marginTop: 8 }}>
            {onUndo ? <button className="btn" onClick={onUndo} disabled={!canUndo || busy}><Undo2 size={14} aria-hidden /> Undo last report</button> : null}
            {onStartOver ? <button className="btn" onClick={onStartOver}><RotateCcw size={14} aria-hidden /> Start over</button> : null}
          </div>
        </>
      ) : (
        <p className="lede">What you hold and what is still open can no longer fit together. The searches below each drop the fewest sections needed and then start a new set of branches from what you keep.</p>
      )}
      {plan.drops.map((d, i) => (
        <div key={i} style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
          <p><b>Drop {d.drop.map((x) => `${x.code} (unique ${x.unique})`).join(" and ")}</b> <span className="muted small">{d.drop.map((x) => x.when).join("; ")}</span></p>
          <p className="small" style={{ marginTop: 4 }}>Then take: {d.then_take.length ? d.then_take.map((t) => `${t.code} ${t.unique}`).join(", ") : "nothing more"}. {d.credits} credits{d.gain !== null ? `, ${d.gain >= 0 ? "+" : ""}${d.gain.toFixed(3)} on the score` : ""}.</p>
          {d.why.length ? <ul className="small muted">{d.why.map((w) => <li key={w}>{w}</li>)}</ul> : null}
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn primary" disabled={busy} onClick={() => onDrop(d)}>I dropped {d.drop.length > 1 ? "them" : "it"}, update the plan</button>
          </div>
        </div>
      ))}
      {!optional && plan.status === "drop_needed" && onUndo ? (
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" onClick={onUndo} disabled={!canUndo || busy}><Undo2 size={14} aria-hidden /> Undo last report instead</button>
        </div>
      ) : null}
    </section>
  );
}

function CurrentCard({ step, opt, idx, total, busy, canUndo, onCopy, onGot, onFull, onSkip, onUndo }: {
  step: RegStep; opt: RegOption; idx: number; total: number; busy: boolean; canUndo: boolean;
  onCopy: () => void; onGot: () => void; onFull: () => void; onSkip: () => void; onUndo: () => void;
}) {
  const n = step.options.length;
  return (
    <div>
      <p className="small muted">Course {step.order} of {total}</p>
      <h3 style={{ marginTop: 2 }}>{step.code} <span style={{ fontWeight: 400 }}>{step.title}</span></h3>
      <div style={{ margin: "10px 0" }}>
        <p className="small muted">{idx === 0 ? "Best section now" : `Option ${idx + 1} of ${n}, chosen from the map`}</p>
        <p className="mono" style={{ fontSize: "2.25rem", lineHeight: 1.15, fontWeight: 400 }} aria-label={`Unique number ${opt.unique}`}>{opt.unique}</p>
        <p style={{ marginTop: 4 }}>{opt.when}</p>
        <p className="small" style={{ marginTop: 2 }}><StatusText status={opt.status} reserved={opt.reserved} /> when the schedule was fetched{opt.instructors.length ? `, ${opt.instructors.join("; ")}` : ""}.</p>
        {opt.conflicts.length ? <p className="small warn" style={{ marginTop: 4 }}>Overlaps the plan for {opt.conflicts.join(", ")}. Registering it changes that course too.</p> : null}
      </div>
      <div className="row">
        <button className="btn primary" onClick={onGot} disabled={busy}><Check size={14} aria-hidden /> Got it (Space)</button>
        <button className="btn" onClick={onFull} disabled={busy}>It was full (→)</button>
        <button className="btn" onClick={onCopy}><Copy size={14} aria-hidden /> Copy unique number (C)</button>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn" onClick={onSkip} disabled={busy}><SkipForward size={14} aria-hidden /> Give up on this course (X)</button>
        <button className="btn" onClick={onUndo} disabled={busy || !canUndo}>Undo last report (←)</button>
      </div>
    </div>
  );
}

function PlanTree({ steps, cur, pick, result, onPick }: { steps: RegStep[]; cur: number; pick: Record<string, number>; result: GenResult | null; onPick: (stepIdx: number, optIdx: number) => void }) {
  const top = result?.schedules[0];
  const topSet = new Set(top?.sections.map((s) => s.unique));
  return (
    <section className="block" aria-labelledby="tree-h">
      <h2 id="tree-h">Every case from here</h2>
      <p className="lede">Read left to right. Each course starts with the section the plan wants. If it fills, tell the runner and the plan is searched again from what you hold, so this map is redrawn. Click a box to pick that section in the runner.</p>
      <div className="rtree">
        <p className="root">Registration opens</p>
        <ul className="branches">
          {steps.map((s, i) => {
            return (
              <li className="branch" key={s.code}>
                <div className="blabel"><b>{s.order}. {s.code}</b><span className="small muted" style={{ display: "block" }}>{s.title}</span></div>
                <div className="chain">
                  {s.options.map((o, j) => {
                    const isCur = i === cur && (pick[s.code] ?? 0) === j;
                    return (
                      <div className="step" key={o.unique}>
                        {j > 0 ? <span className="link" aria-hidden><span>if full</span><span className="line" /></span> : null}
                        <button className={`node${isCur ? " cur" : ""}`} onClick={() => onPick(i, j)}
                          aria-label={`${s.code} option ${j + 1}, unique ${o.unique}`}>
                          <span className="mono">{o.unique}</span>{" "}
                          <StatusText status={o.status} reserved={o.reserved} />
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
