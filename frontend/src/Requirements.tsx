import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, GripVertical, Trash2 } from "lucide-react";
import { api, ApiError, f2 } from "./api";
import type { CoreArea, Group, Requirements as Req, Status, Suggestion } from "./api";
import { Confidence, Interval, NoData, Note, PageHead, StatusText } from "./ui";

type Tree = { code: string; name: string; n_courses: number }[];

export function RequirementsScreen({ status }: { status: Status }) {
  const [areas, setAreas] = useState<CoreArea[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [req, setReq] = useState<Req | null>(null);
  const [err, setErr] = useState("");
  const [warn, setWarn] = useState<string[]>([]);

  const load = useCallback(async () => {
    try {
      const [a, r] = await Promise.all([api<CoreArea[]>("/api/core/areas"), api<Req>("/api/requirements")]);
      setAreas(a);
      setReq(r);
      const t = await api<Tree>(`/api/core/tree?areas=${a.map((x) => x.code).join(",")}`);
      setCounts(Object.fromEntries(t.map((x) => [x.code, x.n_courses])));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const save = async (next: Req) => {
    setErr("");
    try {
      const r = await api<{ requirements: Req; not_in_schedule: string[] }>("/api/requirements", { method: "PUT", body: next });
      setReq(r.requirements);
      setWarn(r.not_in_schedule.map((c) => `${c} is not in the Spring 2027 schedule and was not added.`));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  if (!req) return <div><PageHead title="Requirements" />{err ? <Note error>{err}</Note> : <p className="muted">Loading.</p>}</div>;

  const toggleArea = (code: string) =>
    save({ ...req, core_areas: req.core_areas.includes(code) ? req.core_areas.filter((c) => c !== code) : [...req.core_areas, code] });
  return (
    <div>
      <PageHead title="Requirements">Choose what you still need. Schedules are built from these, and nothing here leaves your computer except the pasted audit lines you choose to parse.</PageHead>
      {err ? <Note error>{err}</Note> : null}
      {!status.has_data ? <NoData /> : null}

      <section className="block" aria-labelledby="core-h">
        <h2 id="core-h">Core curriculum areas you still need</h2>
        <p className="lede">Tick each area you need one more course for. The course options for every ticked area appear below, with the easiest first.</p>
        <div className="grid2">
          {areas.map((a) => (
            <label className="check" key={a.code}>
              <input type="checkbox" checked={req.core_areas.includes(a.code)} onChange={() => toggleArea(a.code)} />
              <span>
                {a.name} <span className="muted small">({counts[a.code] ?? 0} {(counts[a.code] ?? 0) === 1 ? "course" : "courses"} offered)</span>
              </span>
            </label>
          ))}
        </div>
      </section>

      <section className="block" aria-labelledby="req-h">
        <h2 id="req-h">Your courses</h2>
        <p className="lede">Required courses must be in every schedule. Like to take courses are optional: the app includes as many as fit, and when two clash it keeps the one you ranked higher. Drag a like-to-take course to rank it, or use its move buttons. The weight for this is set on the Preferences screen.</p>
        <div className="grid2" style={{ alignItems: "start" }}>
          <CourseList
            title="Required"
            items={req.required_courses}
            onChange={(items) => save({ ...req, required_courses: items, preferred_courses: req.preferred_courses.filter((c) => !items.includes(c)) })}
            moveLabel="Like to take instead"
            onMove={(c) => save({ ...req, required_courses: req.required_courses.filter((x) => x !== c), preferred_courses: [...req.preferred_courses, c] })}
          />
          <CourseList
            title="Like to take"
            ranked
            items={req.preferred_courses}
            onChange={(items) => save({ ...req, preferred_courses: items, required_courses: req.required_courses.filter((c) => !items.includes(c)) })}
            moveLabel="Make required"
            onMove={(c) => save({ ...req, preferred_courses: req.preferred_courses.filter((x) => x !== c), required_courses: [...req.required_courses, c] })}
          />
        </div>
        {warn.map((w) => <p key={w} className="small warn" style={{ marginTop: 6 }}>{w}</p>)}
        {req.groups.length ? (
          <div style={{ marginTop: 16 }}>
            <h3>Pick-from groups</h3>
            <ul className="list-plain" style={{ marginTop: 6 }}>
              {req.groups.map((g, i) => (
                <li key={i} className="small">
                  {g.name}: take {g.pick} of {g.courses.join(", ")}{" "}
                  <button className="btn text" onClick={() => save({ ...req, groups: req.groups.filter((_, j) => j !== i) })}>Remove</button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      {req.core_areas.length ? (
        <section className="block" aria-labelledby="opts-h">
          <h2 id="opts-h">Course options</h2>
          <p className="lede">Courses carrying each Core tag in the registrar schedule. Ease combines grades, professor difficulty and syllabus lightness where they exist; the range shows how sure that estimate is.</p>
          {req.core_areas.map((code) => (
            <AreaOptions key={code} code={code} name={areas.find((a) => a.code === code)?.name ?? code} />
          ))}
        </section>
      ) : null}

      <section className="block" aria-labelledby="more-h">
        <h2 id="more-h">Electives and registration time</h2>
        <div className="grid2">
          <label className="field">
            <span>Limit electives to departments (optional)</span>
            <input type="text" defaultValue={req.elective_depts.join(", ")} placeholder="for example: C S, M, SDS"
              onBlur={(e) => save({ ...req, elective_depts: e.target.value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean) })} />
            <span className="xs">If your required courses and Core areas total fewer credits than your minimum, the app fills the gap with the easiest-ranked courses from these departments, or any department if empty.</span>
          </label>
          <label className="field">
            <span>Your registration time (optional)</span>
            <input type="text" defaultValue={req.registration_time ?? ""} placeholder="for example: Nov 16, 8:00 a.m."
              onBlur={(e) => save({ ...req, registration_time: e.target.value.trim() || null })} />
            <span className="xs">Typed by you. The app never reads your account. It is shown at the top of the registration plan.</span>
          </label>
        </div>
      </section>

      <AuditPaste onApplied={(r) => setReq(r)} />
    </div>
  );
}

function AreaOptions({ code, name }: { code: string; name: string }) {
  const [data, setData] = useState<Suggestion | null>(null);
  const [open, setOpen] = useState(true);
  const [sort, setSort] = useState<"ease" | "dept">("ease");
  const [err, setErr] = useState("");
  useEffect(() => {
    api<Suggestion>(`/api/suggestions?core=${code}&limit=2000`).then(setData).catch((e) => setErr((e as Error).message));
  }, [code]);

  const grouped = useMemo(() => {
    if (!data) return [];
    const by: Record<string, Suggestion["courses"]> = {};
    for (const c of data.courses) (by[c.code.slice(0, c.code.lastIndexOf(" "))] ??= []).push(c);
    return Object.entries(by).sort(([a], [b]) => a.localeCompare(b));
  }, [data]);

  return (
    <div className="tree">
      <div className="area">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <button className="toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
            {name} <span className="muted small" style={{ fontWeight: 400 }}>{data ? `${data.total} ${data.total === 1 ? "course" : "courses"}` : ""}</span>
          </button>
          {open ? (
            <label className="small row" style={{ gap: 6 }}>
              Order
              <select value={sort} onChange={(e) => setSort(e.target.value as "ease" | "dept")}>
                <option value="ease">Easiest first</option>
                <option value="dept">By department</option>
              </select>
            </label>
          ) : null}
        </div>
        {err ? <Note error>{err}</Note> : null}
        {open && data ? (
          sort === "ease" ? (
            <ul>{data.courses.map((c) => <CourseRow key={c.code + c.title} c={c} />)}</ul>
          ) : (
            grouped.map(([dept, cs]) => (
              <div className="dept" key={dept}>
                <h3 className="small" style={{ margin: "10px 0 2px" }}>{dept}</h3>
                <ul>{cs.map((c) => <CourseRow key={c.code + c.title} c={c} />)}</ul>
              </div>
            ))
          )
        ) : null}
      </div>
    </div>
  );
}

function CourseRow({ c }: { c: Suggestion["courses"][number] }) {
  const s = c.signal;
  return (
    <li>
      <details>
        <summary className="course" style={{ cursor: "pointer" }}>
          <span className="mono">{c.code}</span>
          <span>
            {c.title} <span className="muted">({c.credits} hr, {c.sections.length} section{c.sections.length === 1 ? "" : "s"})</span>
          </span>
          <span className="small">
            Ease <Interval v={s.ease_score} lo={s.ease_score_lo} hi={s.ease_score_hi} /> <span className="muted">| </span>
            <Confidence s={s} /> <span className="muted">| Signals: {s.signals.length ? s.signals.join(", ") : "none"}</span>
          </span>
        </summary>
        <table className="t" style={{ margin: "6px 0 10px 18px", width: "calc(100% - 18px)" }}>
          <thead><tr><th>Unique</th><th>Meets</th><th>Instructor</th><th>Status</th></tr></thead>
          <tbody>
            {c.sections.map((x) => (
              <tr key={x.unique}>
                <td className="mono">{x.unique}</td><td>{x.when}</td><td>{x.instructors.join("; ") || "Not listed"}</td>
                <td><StatusText status={x.status} reserved={x.reserved} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {s.gpa !== null || s.rmp_rating !== null || s.lightness !== null ? (
          <p className="small muted" style={{ margin: "0 0 8px 18px" }}>
            {s.gpa !== null ? `Mean GPA ${f2(s.gpa)}. ` : ""}{s.rmp_rating !== null ? `Professor rating ${f2(s.rmp_rating)} of 5. ` : ""}{s.lightness !== null ? `Syllabus lightness ${f2(s.lightness)}.` : ""}
          </p>
        ) : null}
      </details>
    </li>
  );
}

function AuditPaste({ onApplied }: { onApplied: (r: Req) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [res, setRes] = useState<{ groups: Group[]; notes: string | null; characters_sent: number } | null>(null);
  const [keep, setKeep] = useState<boolean[]>([]);
  const [done, setDone] = useState<string[]>([]);

  const parse = async () => {
    setBusy(true); setErr(""); setDone([]);
    try {
      const r = await api<{ groups: Group[]; notes: string | null; characters_sent: number }>("/api/requirements/audit/parse", { body: { text } });
      setRes(r); setKeep(r.groups.map(() => true));
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    if (!res) return;
    const groups = res.groups.filter((_, i) => keep[i]);
    const r = await api<{ requirements: Req; warnings: string[] }>("/api/requirements/audit/apply", { body: { groups } });
    onApplied(r.requirements);
    setDone(r.warnings.length ? r.warnings : ["Saved."]);
    setRes(null); setText("");
  };
  const edit = (i: number, courses: string) =>
    setRes((r) => r && { ...r, groups: r.groups.map((g, j) => (j === i ? { ...g, courses: courses.split(",").map((s) => s.trim()).filter(Boolean) } : g)) });

  return (
    <section className="block" aria-labelledby="audit-h">
      <h2 id="audit-h">Read requirements from a pasted degree audit</h2>
      <p className="lede">Optional. Paste the requirements part of your audit. Lines that look like names, EIDs, emails or phone numbers are removed on this computer first, and only lines about requirements or courses are sent to the language model. The pasted text is not saved. You review and correct the result before anything is stored.</p>
      <label className="field">
        <span>Audit text</span>
        <textarea rows={7} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" disabled={busy || text.trim().length < 20} onClick={parse}>{busy ? "Reading" : "Read requirements"}</button>
      </div>
      {err ? <div style={{ marginTop: 10 }}><Note error>{err}</Note></div> : null}
      {done.length ? <div style={{ marginTop: 10 }}><Note>{done.map((d) => <p key={d}>{d}</p>)}</Note></div> : null}
      {res ? (
        <div style={{ marginTop: 14 }}>
          <p className="small muted">Sent {res.characters_sent.toLocaleString()} characters. Untick anything wrong, and edit course lists if needed.</p>
          <table className="t" style={{ marginTop: 6 }}>
            <thead><tr><th>Use</th><th>Kind</th><th>Name</th><th>Core code</th><th>Courses</th><th>Pick</th></tr></thead>
            <tbody>
              {res.groups.map((g, i) => (
                <tr key={i}>
                  <td><input type="checkbox" aria-label={`Use ${g.name}`} checked={keep[i]} onChange={() => setKeep(keep.map((k, j) => (j === i ? !k : k)))} /></td>
                  <td>{g.kind.replace("_", " ")}</td><td>{g.name}</td><td className="mono">{g.core_code ?? ""}</td>
                  <td><input type="text" aria-label={`Courses for ${g.name}`} defaultValue={g.courses.join(", ")} onBlur={(e) => edit(i, e.target.value)} style={{ width: "100%" }} /></td>
                  <td>{g.kind === "choose_from" ? g.pick : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {res.notes ? <p className="small muted" style={{ marginTop: 6 }}>Not placed in a group: {res.notes}</p> : null}
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn primary" onClick={apply}>Save selected</button>
            <button className="btn" onClick={() => setRes(null)}>Discard</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function CourseList({ title, items, onChange, onMove, moveLabel, ranked }: {
  title: string; items: string[]; onChange: (items: string[]) => void; onMove: (code: string) => void; moveLabel: string; ranked?: boolean;
}) {
  const [text, setText] = useState("");
  const [drag, setDrag] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const add = () => {
    const parts = text.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
    if (parts.length) onChange([...items, ...parts]);
    setText("");
  };
  const reorder = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0 || to >= items.length) return;
    const next = [...items];
    const [m] = next.splice(from, 1);
    next.splice(to, 0, m);
    onChange(next);
  };
  const id = title.toLowerCase().replace(/\W+/g, "-");
  return (
    <div>
      <h3 id={`${id}-h`}>{title} <span className="muted small" style={{ fontWeight: 400 }}>({items.length})</span></h3>
      <div className="row" style={{ margin: "8px 0" }}>
        <label className="field" style={{ minWidth: 200 }}>
          <span className="xs">Add course codes, for example C S 312 or M 408C</span>
          <input type="text" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} aria-describedby={`${id}-h`} />
        </label>
        <button className="btn" style={{ alignSelf: "end" }} onClick={add}>Add</button>
      </div>
      {items.length === 0 ? <p className="small muted">None yet.</p> : (
        <ol className="list-plain" aria-labelledby={`${id}-h`} style={{ counterReset: "r" }}>
          {items.map((c, i) => (
            <li key={c} draggable={!!ranked}
              onDragStart={() => setDrag(i)} onDragEnd={() => { setDrag(null); setOver(null); }}
              onDragOver={(e) => { if (ranked && drag !== null) { e.preventDefault(); setOver(i); } }}
              onDrop={() => { if (drag !== null) reorder(drag, i); setDrag(null); setOver(null); }}
              style={{ display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid var(--line)", padding: "6px 0",
                background: over === i && drag !== i ? "var(--primary-tint)" : undefined, opacity: drag === i ? 0.5 : 1, cursor: ranked ? "grab" : undefined }}>
              {ranked ? <><GripVertical size={16} aria-hidden style={{ color: "var(--muted)" }} /><span className="mono small" style={{ width: 22 }}>{i + 1}.</span></> : null}
              <span style={{ flex: 1 }}>{c}</span>
              {ranked ? (
                <>
                  <button className="btn text" aria-label={`Move ${c} up`} disabled={i === 0} onClick={() => reorder(i, i - 1)}><ArrowUp size={14} aria-hidden /></button>
                  <button className="btn text" aria-label={`Move ${c} down`} disabled={i === items.length - 1} onClick={() => reorder(i, i + 1)}><ArrowDown size={14} aria-hidden /></button>
                </>
              ) : null}
              <button className="btn text small" onClick={() => onMove(c)}>{moveLabel}</button>
              <button className="btn text" onClick={() => onChange(items.filter((x) => x !== c))} aria-label={`Remove ${c}`}><Trash2 size={14} aria-hidden /></button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
