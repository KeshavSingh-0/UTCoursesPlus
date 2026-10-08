import { useEffect, useState } from "react";
import type { GenResult, Status } from "./api";
import { NoData, Note, PageHead, StatusText, when } from "./ui";

const KEY = "utcp.regchecklist.v1";

export function RegistrationScreen({ status, result }: { status: Status; result: GenResult | null }) {
  const [done, setDone] = useState<Record<string, boolean>>({});
  useEffect(() => {
    try { setDone(JSON.parse(localStorage.getItem(KEY) ?? "{}")); } catch { /* storage unavailable */ }
  }, []);
  const toggle = (u: string) => {
    const next = { ...done, [u]: !done[u] };
    setDone(next);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* ignore */ }
  };
  if (!status.has_data) return <div><PageHead title="Registration plan" /><NoData /></div>;
  const plan = result?.registration;

  return (
    <div>
      <PageHead title="Registration plan">An ordered checklist for you to carry out by hand on UT's registration site. This app never registers, drops or joins waitlists for you.</PageHead>
      {!plan ? <Note><p>No plan yet. Find schedules on the Ranked schedules screen first; the plan is built from the top schedule.</p></Note> : (
        <>
          <section aria-label="Registration time" style={{ marginBottom: 18 }}>
            <p><b>Registration time:</b> {plan.registration_time ?? <span className="muted">not entered. Add it on the Requirements screen.</span>}</p>
            <p className="small muted" style={{ marginTop: 4, maxWidth: "75ch" }}>{plan.label} Seat status was read when the schedule was fetched and may have changed since; check the live status when you register.</p>
          </section>
          <ol className="checklist">
            {plan.steps.map((s) => (
              <li key={s.unique} className={done[s.unique] ? "done" : ""}>
                <input type="checkbox" id={`step-${s.unique}`} checked={!!done[s.unique]} onChange={() => toggle(s.unique)} aria-label={`Mark ${s.code} done`} style={{ marginTop: 4 }} />
                <div>
                  <label htmlFor={`step-${s.unique}`} className="what" style={{ display: "block" }}>
                    <b>{s.order}. {s.code}</b> {s.title}, unique <span className="mono">{s.unique}</span>
                  </label>
                  <p className="small">{s.when}. <StatusText status={s.status} reserved={s.reserved} /> as of {when(s.fetched_at)}.</p>
                  <p className="small muted">Why this order: {s.reasons.join("; ")}.</p>
                  <p className="small">
                    {s.fallback ? <>If it fails, try unique <span className="mono">{s.fallback.unique}</span> ({s.fallback.when}, <StatusText status={s.fallback.status} />
                      {s.fallback.instructors.length ? `, ${s.fallback.instructors.join("; ")}` : ""}).</> : <span className="warn">No fallback section fits the rest of this schedule. Consider a backup schedule.</span>}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <button className="btn" style={{ marginTop: 14 }} onClick={() => { setDone({}); try { localStorage.removeItem(KEY); } catch { /* ignore */ } }}>Clear checkmarks</button>
        </>
      )}
    </div>
  );
}
