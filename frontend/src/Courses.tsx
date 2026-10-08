import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ExternalLink } from "lucide-react";
import { api, f2 } from "./api";
import type { CoreArea, Section, Status } from "./api";
import { Confidence, Interval, NoData, Note, PageHead, StatusText, sourceHost, when } from "./ui";

const COLS = "64px 84px minmax(150px, 1.5fr) minmax(120px, 1fr) 178px 88px minmax(120px, 1fr) 138px 138px 70px";
const WIDTH = 1180;

export function CoursesScreen({ status }: { status: Status }) {
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("");
  const [level, setLevel] = useState("");
  const [core, setCore] = useState("");
  const [st, setSt] = useState("");
  const [depts, setDepts] = useState<string[]>([]);
  const [areas, setAreas] = useState<CoreArea[]>([]);
  const [rows, setRows] = useState<Section[]>([]);
  const [total, setTotal] = useState(0);
  const [sel, setSel] = useState(0);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<string[]>("/api/departments").then(setDepts).catch(() => undefined);
    api<CoreArea[]>("/api/core/areas").then(setAreas).catch(() => undefined);
  }, []);
  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true);
      const p = new URLSearchParams({ q, dept, level, core, status: st, limit: "8000" });
      api<{ total: number; rows: Section[] }>(`/api/courses?${p}`)
        .then((r) => { setRows(r.rows); setTotal(r.total); setSel(0); setErr(""); })
        .catch((e) => setErr((e as Error).message))
        .finally(() => setLoading(false));
    }, 180);
    return () => clearTimeout(t);
  }, [q, dept, level, core, st]);

  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => 36, overscan: 12 });
  const areaName = useMemo(() => Object.fromEntries(areas.map((a) => [a.code, a.name])), [areas]);
  const cur = rows[sel];

  const onKey = (e: React.KeyboardEvent) => {
    if (!rows.length) return;
    const move = (n: number) => { e.preventDefault(); const i = Math.max(0, Math.min(rows.length - 1, n)); setSel(i); virt.scrollToIndex(i); };
    if (e.key === "ArrowDown") move(sel + 1);
    else if (e.key === "ArrowUp") move(sel - 1);
    else if (e.key === "PageDown") move(sel + 12);
    else if (e.key === "PageUp") move(sel - 12);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(rows.length - 1);
  };

  if (!status.has_data) return <div><PageHead title="Courses and sections" /><NoData /></div>;

  return (
    <div>
      <PageHead title="Courses and sections">Every section in the Spring 2027 schedule you loaded. Ease is shown with its range; "none" means no ratings, grades or syllabus are loaded for it.</PageHead>
      <div className="row" style={{ marginBottom: 12 }} role="search">
        <label className="field" style={{ width: 240 }}><span>Search</span><input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="course, title, instructor, unique" /></label>
        <label className="field"><span>Department</span>
          <select value={dept} onChange={(e) => setDept(e.target.value)}><option value="">All</option>{depts.map((d) => <option key={d}>{d}</option>)}</select></label>
        <label className="field"><span>Level</span>
          <select value={level} onChange={(e) => setLevel(e.target.value)}><option value="">All</option><option value="L">Lower division</option><option value="U">Upper division</option><option value="G">Graduate</option></select></label>
        <label className="field"><span>Core area</span>
          <select value={core} onChange={(e) => setCore(e.target.value)}><option value="">Any</option>{areas.map((a) => <option key={a.code} value={a.code}>{a.name}</option>)}</select></label>
        <label className="field"><span>Status</span>
          <select value={st} onChange={(e) => setSt(e.target.value)}><option value="">All</option><option value="open">Open</option><option value="waitlisted">Waitlisted</option><option value="closed">Closed</option><option value="cancelled">Cancelled</option></select></label>
        <p className="small muted" style={{ alignSelf: "end" }} aria-live="polite">{loading ? "Loading" : `${total.toLocaleString()} sections${rows.length < total ? `, showing first ${rows.length.toLocaleString()}` : ""}`}</p>
      </div>
      {err ? <Note error>{err}</Note> : null}
      <div style={{ overflowX: "auto" }}>
        <div className="vt" role="table" aria-label="Sections" aria-rowcount={rows.length + 1} style={{ minWidth: WIDTH }}>
          <div className="vhead" role="row" style={{ gridTemplateColumns: COLS }}>
            {["Unique", "Course", "Title", "Instructor", "Meets", "Status", "Core", "Ease", "Difficulty", "Lightness"].map((h) => <span role="columnheader" key={h}>{h}</span>)}
          </div>
          <div className="vscroll" ref={scroller} style={{ height: "min(46vh, 520px)" }} tabIndex={0} onKeyDown={onKey} role="rowgroup"
            aria-label="Section rows. Use arrow keys to move." aria-activedescendant={cur ? `row-${cur.unique}` : undefined}>
            <div style={{ height: virt.getTotalSize(), position: "relative" }}>
              {virt.getVirtualItems().map((v) => {
                const s = rows[v.index];
                const sg = s.signal;
                return (
                  <div key={s.unique} id={`row-${s.unique}`} role="row" aria-rowindex={v.index + 2} aria-selected={v.index === sel} className="vrow"
                    style={{ gridTemplateColumns: COLS, top: v.start }} onClick={() => setSel(v.index)}>
                    <span role="cell" className="mono">{s.unique}</span>
                    <span role="cell" className="mono">{s.code}</span>
                    <span role="cell" title={s.title}>{s.title}</span>
                    <span role="cell" title={s.instructors.join("; ")}>{s.instructors.join("; ") || "Not listed"}</span>
                    <span role="cell" title={s.when}>{s.when === "No meeting time listed" ? <span className="muted">No time listed</span> : s.when}</span>
                    <span role="cell"><StatusText status={s.status} reserved={s.reserved} /></span>
                    <span role="cell" title={s.core.map((c) => areaName[c] ?? c).join("; ")}>{s.core.map((c) => areaName[c] ?? c).join("; ") || <span className="muted">none</span>}</span>
                    <span role="cell">{sg ? <Interval v={sg.ease_score} lo={sg.ease_score_lo} hi={sg.ease_score_hi} /> : null}</span>
                    <span role="cell">{sg && sg.ease !== null ? <Interval v={1 - sg.ease} lo={1 - (sg.ease_hi ?? 0)} hi={1 - (sg.ease_lo ?? 0)} /> : <span className="muted">none</span>}</span>
                    <span role="cell">{sg && sg.lightness !== null ? f2(sg.lightness) : <span className="muted">none</span>}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
      {cur ? <Detail s={cur} areaName={areaName} /> : rows.length === 0 && !loading ? <p className="muted" style={{ marginTop: 12 }}>No sections match these filters.</p> : null}
    </div>
  );
}

function Detail({ s, areaName }: { s: Section; areaName: Record<string, string> }) {
  const [links, setLinks] = useState<Record<string, string>>({});
  useEffect(() => {
    setLinks({});
    s.instructors.forEach((n) => api<{ url: string }>(`/api/instructors/rmp-link?name=${encodeURIComponent(n)}`).then((r) => setLinks((l) => ({ ...l, [n]: r.url }))).catch(() => undefined));
  }, [s.unique]); // eslint-disable-line react-hooks/exhaustive-deps
  const g = s.signal;
  return (
    <section className="block" aria-labelledby="detail-h" aria-live="polite">
      <h2 id="detail-h" style={{ fontSize: "var(--fs-lg)" }}>{s.code} {s.title} <span className="muted mono" style={{ fontWeight: 400 }}>unique {s.unique}</span></h2>
      <div className="grid2" style={{ marginTop: 10 }}>
        <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "130px 1fr", gap: "4px 12px" }} className="small">
          <dt className="muted">Credits</dt><dd style={{ margin: 0 }}>{s.credits}</dd>
          <dt className="muted">Meets</dt><dd style={{ margin: 0 }}>{s.when}</dd>
          <dt className="muted">Mode</dt><dd style={{ margin: 0 }}>{s.mode ?? "Not listed"}</dd>
          <dt className="muted">Status</dt><dd style={{ margin: 0 }}><StatusText status={s.status} reserved={s.reserved} /></dd>
          <dt className="muted">Core</dt><dd style={{ margin: 0 }}>{s.core.map((c) => areaName[c] ?? c).join("; ") || "None"}</dd>
          <dt className="muted">Source</dt>
          <dd style={{ margin: 0 }}>{sourceHost(s.source_url)}, fetched {when(s.fetched_at)}</dd>
          <dt className="muted">Instructors</dt>
          <dd style={{ margin: 0 }}>
            {s.instructors.length ? s.instructors.map((n) => (
              <div key={n}>{n}{links[n] ? <> <a href={links[n]} target="_blank" rel="noopener noreferrer" className="btn text" style={{ textDecoration: "none" }}>Look up on RMP <ExternalLink size={13} aria-hidden /></a></> : null}</div>
            )) : "Not listed"}
          </dd>
        </dl>
        {g ? (
          <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "170px 1fr", gap: "4px 12px" }} className="small">
            <dt className="muted">Ease score</dt><dd style={{ margin: 0 }}><Interval v={g.ease_score} lo={g.ease_score_lo} hi={g.ease_score_hi} /> <Confidence s={g} /></dd>
            <dt className="muted">Signals present</dt><dd style={{ margin: 0 }}>{g.signals.length ? g.signals.join(", ") : "None. Import ratings or grades, or add a syllabus, on the Data sources screen."}</dd>
            <dt className="muted">Mean GPA</dt><dd style={{ margin: 0 }}>{g.gpa !== null ? `${f2(g.gpa)} from ${g.n_graded.toLocaleString()} students` : "none"}</dd>
            <dt className="muted">Professor rating</dt><dd style={{ margin: 0 }}>{g.rmp_rating !== null ? `${f2(g.rmp_rating)} of 5 from ${g.rmp_n} ratings${g.rmp_n < 10 ? " (few ratings; shrunk toward the department)" : ""}` : "none"}</dd>
            <dt className="muted">Syllabus lightness</dt><dd style={{ margin: 0 }}>{g.lightness !== null ? `${f2(g.lightness)}, from ${Math.round(g.lightness_coverage * 100)}% of the scored fields` : "none"}</dd>
          </dl>
        ) : null}
      </div>
    </section>
  );
}
