import type { ReactNode } from "react";
import { f2 } from "./api";

export function StatusText({ status, reserved }: { status: string; reserved?: boolean }) {
  const label = status === "waitlisted" ? "Waitlisted" : status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <span className={`st-${status}`}>
      {label}
      {reserved ? <span className="muted">, reserved</span> : null}
    </span>
  );
}

export function Interval({ v, lo, hi }: { v: number | null; lo: number | null; hi: number | null }) {
  if (v === null) return <span className="muted">none</span>;
  return (
    <span>
      {f2(v)}
      <span className="unc"> ({f2(lo)} to {f2(hi)})</span>
    </span>
  );
}

export function Confidence({ s }: { s: { confidence: string } }) {
  const text = s.confidence === "None" ? "No data" : `${s.confidence} confidence`;
  return <span className={s.confidence === "Low" || s.confidence === "None" ? "warn" : "muted"}>{text}</span>;
}

export function Note({ children, error }: { children: ReactNode; error?: boolean }) {
  return (
    <div className={`note${error ? " err" : ""}`} role={error ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function PageHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="page-head">
      <h1>{title}</h1>
      {children ? <p>{children}</p> : null}
    </header>
  );
}

export function NoData() {
  return (
    <Note>
      <p>No sections are loaded yet.</p>
      <p>
        In the <code>backend</code> folder, run <code>uv run utcoursesplus login</code> then <code>uv run utcoursesplus crawl</code>, or load saved pages with{" "}
        <code>uv run utcoursesplus import-html FILE</code>. Then reload this page.
      </p>
    </Note>
  );
}

export function uniq<T>(xs: T[]): T[] {
  return [...new Set(xs)];
}

export function sourceHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function when(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Stable colour index (0 to 7) for a course code, so a course keeps its colour on every screen. */
export function courseColor(code: string): number {
  let h = 0;
  for (const ch of code) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h % 8;
}
export const ccClass = (code: string) => `cc${courseColor(code)}`;
