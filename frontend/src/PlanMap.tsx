import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Copy, RefreshCw } from "lucide-react";
import { api } from "./api";
import type { GenResult, PlanAlt, PlanItem, PlanOption, PlanTree, Status } from "./api";
import { DeferralNote } from "./Deferrals";
import { layout, pathTo } from "./planlayout.ts";
import type { TreeNode } from "./planlayout.ts";
import { NoData, Note, PageHead, StatusText } from "./ui";

type Resp = { tree: PlanTree | null; problems: string[]; deferrals: GenResult["deferrals"]; notes: string[] };
const statusWord = (s: string) => (s === "waitlisted" ? "Waitlisted" : s.charAt(0).toUpperCase() + s.slice(1));

function buildTree(t: PlanTree, fallbacks: number, showAlts: boolean, showBackups: boolean): TreeNode {
  const root: TreeNode = { id: "root", kind: "root", title: t.root.title, sub: `${t.root.credits} credit hours, ${t.root.courses} courses`, sub2: `Utility ${t.root.utility.toFixed(2)}`, children: [] };
  for (const g of t.groups) {
    const gn: TreeNode = { id: `g:${g.id}`, kind: "group", tone: g.id, title: g.title, sub: `${g.items.length} item${g.items.length === 1 ? "" : "s"}`, children: [] };
    for (const it of g.items) {
      const head = it.code ? `${it.code} ${it.title ?? ""}`.trim() : `Core: ${it.area ?? it.slot}`;
      const rank = it.rank ? `Rank ${it.rank}. ` : "";
      if (!it.included) {
        gn.children!.push({ id: `i:${it.key}`, kind: "out", tone: g.id, title: head, sub: `${rank}Left out`, sub2: it.reason ?? undefined, data: it });
        continue;
      }
      const item: TreeNode = { id: `i:${it.key}`, kind: "item", tone: g.id, title: head, sub: `${it.credits ?? ""} credit hours${it.area ? `, covers ${it.area}` : ""}`, sub2: rank ? rank.trim() : undefined, data: it, children: [] };
      it.options.slice(0, 1 + fallbacks).forEach((o, j) => {
        item.children!.push({ id: `o:${it.key}:${o.unique}`, kind: j === 0 ? "plan" : "fallback", tone: g.id, title: `${o.unique}, ${statusWord(o.status)}`, sub: o.when, sub2: o.instructors.join("; ") || undefined, data: { item: it, option: o, index: j } });
      });
      if (showAlts) {
        it.alternatives.slice(0, 3).forEach((a) => {
          item.children!.push({ id: `a:${it.key}:${a.code}`, kind: "alt", tone: g.id, title: `${a.code} ${a.title}`, sub: "Another course for this area", sub2: a.ease_score !== null ? `Ease ${a.ease_score.toFixed(2)}, ${a.confidence} confidence` : "No ratings or grades", data: { item: it, alt: a } });
        });
      }
      gn.children!.push(item);
    }
    root.children!.push(gn);
  }
  if (showBackups && t.backups.length) {
    const bg: TreeNode = { id: "g:backup", kind: "group", tone: "backup", title: "Backup schedules", sub: `${t.backups.length} whole alternatives`, children: [] };
    for (const b of t.backups) {
      bg.children!.push({
        id: `b:${b.index}`, kind: "backup", tone: "backup", title: `Backup ${b.index}`, sub: `${b.credits} credit hours`, sub2: `Utility ${b.utility.toFixed(2)}`, data: b,
        children: b.sections.map((s) => ({ id: `bs:${b.index}:${s.unique}`, kind: "bsection" as const, tone: "backup", title: `${s.unique} ${s.code}`, sub: s.when, sub2: s.shared ? "Same as the plan" : "Different from the plan", data: s })),
      });
    }
    root.children!.push(bg);
  }
  return root;
}

const kindClass: Record<TreeNode["kind"], string> = { root: "root", group: "group", item: "", plan: "plan", fallback: "fallback", alt: "alt", out: "out", backup: "plan", bsection: "fallback" };

export function PlanMapScreen({ status }: { status: Status }) {
  const [resp, setResp] = useState<Resp | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [fallbacks, setFallbacks] = useState(3);
  const [alts, setAlts] = useState(true);
  const [backups, setBackups] = useState(true);
  const [sel, setSel] = useState("root");

  const load = useCallback(async () => {
    setBusy(true); setErr("");
    try { setResp(await api<Resp>("/api/plan/tree")); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const root = useMemo(() => (resp?.tree ? buildTree(resp.tree, fallbacks, alts, backups) : null), [resp, fallbacks, alts, backups]);
  const lay = useMemo(() => (root ? layout(root) : null), [root]);
  const path = useMemo(() => (lay ? pathTo(lay.nodes, sel) : new Set<string>()), [lay, sel]);
  const selected = lay?.nodes.find((n) => n.node.id === sel)?.node ?? null;
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // the root sits in the vertical middle of a tall tree; bring it into view
    const r = lay?.nodes.find((n) => n.node.id === "root");
    if (r && wrap.current) wrap.current.scrollTop = Math.max(0, r.y - 120);
  }, [lay]);

  if (!status.has_data) return <div><PageHead title="Plan map" /><NoData /></div>;
  return (
    <div>
      <PageHead title="Plan map">Everything the plan involves in one picture: what to take, the sections to try if one fills, other courses that would cover the same Core area, what was left out and why, and whole backup schedules. Click any box to see it.</PageHead>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="btn primary" onClick={load} disabled={busy}><RefreshCw size={14} aria-hidden /> {busy ? "Building" : "Rebuild from my settings"}</button>
        <label className="field" style={{ width: 150 }}><span className="xs">Fallback sections shown</span>
          <select value={fallbacks} onChange={(e) => setFallbacks(Number(e.target.value))}>{[0, 1, 2, 3, 4, 6, 9].map((n) => <option key={n} value={n}>{n === 0 ? "None" : `Up to ${n}`}</option>)}</select></label>
        <label className="check small"><input type="checkbox" checked={alts} onChange={(e) => setAlts(e.target.checked)} /><span>Other courses for a Core area</span></label>
        <label className="check small"><input type="checkbox" checked={backups} onChange={(e) => setBackups(e.target.checked)} /><span>Backup schedules</span></label>
      </div>
      <div className="legend" style={{ marginBottom: 10 }} aria-label="Legend">
        <span className="g-required">Required</span><span className="g-core">Core area</span><span className="g-like">Like to take</span><span className="g-elective">Elective</span><span className="g-backup">Backup</span>
        <span className="muted">Solid box: in the plan. Plain box: a section to try if the one before it fills. Dashed: left out. Dotted: another course you could take.</span>
      </div>
      {err ? <Note error>{err}</Note> : null}
      {resp?.notes.map((n) => <div key={n} style={{ marginBottom: 6 }}><Note>{n}</Note></div>)}
      {resp && !resp.tree ? (
        <>
          <Note error>{resp.problems.length ? resp.problems.map((p) => <p key={p}>{p}</p>) : <p>No schedule fits yet, so there is nothing to map. Add requirements first.</p>}</Note>
          <DeferralNote deferrals={resp.deferrals} onApplied={load} />
        </>
      ) : null}
      {lay && root ? (
        <>
          <div className="pm-wrap" ref={wrap} role="group" aria-label="Plan map. Each box is a button.">
            <div className="pm" style={{ width: lay.width, height: lay.height }}>
              <svg width={lay.width} height={lay.height} aria-hidden>
                {lay.edges.map((e) => <path key={e.from + e.to} d={e.d} className={path.has(e.from) && path.has(e.to) ? "hl" : ""} />)}
              </svg>
              {lay.nodes.map((p) => (
                <button key={p.node.id} className={`pm-node ${kindClass[p.node.kind]} g-${p.node.tone ?? "required"}${sel === p.node.id ? " sel" : ""}`}
                  style={{ left: p.x, top: p.y, width: p.w, height: p.h }} onClick={() => setSel(p.node.id)}
                  aria-label={`${p.node.title}. ${p.node.sub ?? ""} ${p.node.sub2 ?? ""}`} aria-pressed={sel === p.node.id}>
                  <span className="t">{p.node.title}</span>
                  {p.node.sub ? <span className="s">{p.node.sub}</span> : null}
                  {p.node.sub2 ? <span className="s">{p.node.sub2}</span> : null}
                </button>
              ))}
            </div>
          </div>
          {selected ? <Detail node={selected} /> : null}
        </>
      ) : null}
    </div>
  );
}

function Detail({ node }: { node: TreeNode }) {
  const [msg, setMsg] = useState("");
  const copy = async (u: string) => {
    try { await navigator.clipboard.writeText(u); setMsg(`Copied ${u}`); } catch { setMsg("Could not copy. Select the number and copy it by hand."); }
  };
  const d = node.data as unknown;
  let body: JSX.Element;
  if (node.kind === "plan" || node.kind === "fallback") {
    const { item, option, index } = d as { item: PlanItem; option: PlanOption; index: number };
    body = (
      <>
        <h3>{item.code} {item.title}</h3>
        <p className="small muted">{index === 0 ? "The section the plan wants" : `Fallback ${index}: try this if the ones before it are full`}</p>
        <p className="big-unique" style={{ margin: "6px 0" }}>{option.unique}</p>
        <p>{option.when}</p>
        <p className="small"><StatusText status={option.status} reserved={option.reserved} />{option.instructors.length ? `, ${option.instructors.join("; ")}` : ""}</p>
        {option.conflicts.length ? <p className="small warn">Overlaps the plan for {option.conflicts.join(", ")}.</p> : <p className="small good">Fits with the rest of the plan.</p>}
        <div className="row" style={{ marginTop: 8 }}><button className="btn" onClick={() => copy(option.unique)}><Copy size={14} aria-hidden /> Copy unique number</button><span className="small muted" role="status">{msg}</span></div>
      </>
    );
  } else if (node.kind === "alt") {
    const { item, alt } = d as { item: PlanItem; alt: PlanAlt };
    body = (
      <>
        <h3>{alt.code} {alt.title}</h3>
        <p className="small muted">Another course that would cover {item.area ?? "this area"} instead of {item.code}.</p>
        <p className="small" style={{ marginTop: 4 }}>{alt.credits} credit hours, {alt.sections} section{alt.sections === 1 ? "" : "s"}. {alt.ease_score !== null ? `Ease ${alt.ease_score.toFixed(2)} with ${alt.confidence} confidence.` : "No ratings, grades or syllabus loaded for it."}</p>
        <p className="small" style={{ marginTop: 4 }}>Best section: <span className="mono">{alt.best.unique}</span>, {alt.best.when}, <StatusText status={alt.best.status} reserved={alt.best.reserved} />.</p>
        <p className="small muted" style={{ marginTop: 6 }}>To plan around it, pin it as a required course or like-to-take course on the Requirements screen.</p>
      </>
    );
  } else if (node.kind === "out") {
    const it = d as PlanItem;
    body = (<><h3>{node.title}</h3><p className="small muted">{it.rank ? `Ranked ${it.rank} in your Like to take list. ` : ""}Not in the best schedule.</p><p style={{ marginTop: 4 }}>{it.reason}</p></>);
  } else if (node.kind === "item") {
    const it = d as PlanItem;
    body = (<><h3>{node.title}</h3><p className="small muted">{it.slot}</p><p className="small" style={{ marginTop: 4 }}>{it.options.length} section{it.options.length === 1 ? "" : "s"} could work. The first is the plan; the rest are fallbacks in order of how well they fit.</p></>);
  } else if (node.kind === "backup") {
    body = (<><h3>{node.title}</h3><p className="small muted">A whole alternative schedule that shares as few sections as possible with the plan, for when sections fill.</p></>);
  } else {
    body = (<><h3>{node.title}</h3>{node.sub ? <p className="small muted">{node.sub}</p> : null}{node.sub2 ? <p className="small muted">{node.sub2}</p> : null}</>);
  }
  return <div className="pm-detail" style={{ marginTop: 12 }} aria-live="polite">{body}</div>;
}
