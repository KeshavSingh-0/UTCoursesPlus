import { useState } from "react";
import { api } from "./api";
import type { GenResult, Requirements } from "./api";
import { Note } from "./ui";

/** Shown when nothing fits: the required items that, if put off, would let a schedule exist. */
export function DeferralNote({ deferrals, onApplied }: { deferrals: GenResult["deferrals"]; onApplied: () => void }) {
  const [err, setErr] = useState("");
  const [done, setDone] = useState("");
  if (!deferrals.length) return null;

  const move = async (d: GenResult["deferrals"][number], to: "like" | "defer") => {
    setErr("");
    try {
      const r = await api<Requirements>("/api/requirements");
      const req = { ...r };
      if (d.kind === "course") {
        req.required_courses = r.required_courses.filter((c) => c !== d.key);
        if (to === "like") req.preferred_courses = [...r.preferred_courses, d.key];
      } else {
        req.core_areas = r.core_areas.filter((c) => c !== d.key);
        if (to === "like") req.preferred_courses = [...r.preferred_courses, `core:${d.key}`];
      }
      await api("/api/requirements", { method: "PUT", body: req });
      setDone(`${d.label} is ${to === "like" ? "now in Like to take, at the bottom of your ranking" : "put off to a later semester"}.`);
      onApplied();
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="note tip" role="status" style={{ margin: "8px 0" }}>
      <p><b>Nothing fits everything you marked required.</b> Putting off any one of these would let a schedule exist, best result first:</p>
      <ul className="list-plain" style={{ margin: "8px 0" }}>
        {deferrals.map((d) => (
          <li key={d.kind + d.key} className="row" style={{ gap: 8 }}>
            <b>{d.label}</b>
            <span className="muted small">{d.kind === "core" ? "Core area" : "course"}, best schedule then scores {d.utility.toFixed(2)}</span>
            <button className="btn text small" onClick={() => move(d, "like")}>Move to Like to take</button>
            <button className="btn text small" onClick={() => move(d, "defer")}>Not this semester</button>
          </li>
        ))}
      </ul>
      {done ? <p className="small good">{done}</p> : null}
      {err ? <Note error>{err}</Note> : null}
    </div>
  );
}
