import type { Section } from "./api";
import { fmtMin } from "./api";

const DAYS = ["M", "T", "W", "TH", "F", "S"];
const NAMES: Record<string, string> = { M: "Mon", T: "Tue", W: "Wed", TH: "Thu", F: "Fri", S: "Sat" };

export function Calendar({ sections, compact = false, label }: { sections: Section[]; compact?: boolean; label: string }) {
  const meets = sections.flatMap((s) => s.meets.map((m) => ({ s, m })));
  const untimed = sections.filter((s) => s.meets.length === 0);
  const showSat = meets.some(({ m }) => m.days.includes("S"));
  const days = showSat ? DAYS : DAYS.slice(0, 5);
  const starts = meets.map(({ m }) => m.start), ends = meets.map(({ m }) => m.end);
  const first = Math.min(8 * 60, ...(starts.length ? [Math.floor(Math.min(...starts) / 60) * 60] : [8 * 60]));
  const last = Math.max(17 * 60, ...(ends.length ? [Math.ceil(Math.max(...ends) / 60) * 60] : [17 * 60]));
  const px = compact ? 0.55 : 0.8; // pixels per minute
  const height = (last - first) * px;
  const hours: number[] = [];
  for (let h = first; h <= last; h += 60) hours.push(h);
  const cols = `${compact ? 44 : 56}px repeat(${days.length}, minmax(0, 1fr))`;

  return (
    <div>
      <div className={`cal${compact ? " compact" : ""}`} role="img" aria-label={label}>
        <div className="head" style={{ gridTemplateColumns: cols }}>
          <div />
          {days.map((d) => (
            <div key={d}>{NAMES[d]}</div>
          ))}
        </div>
        <div className="body" style={{ gridTemplateColumns: cols, height }}>
          <div className="hours">
            {hours.map((h) => (
              <span key={h} style={{ top: (h - first) * px, transform: h === first ? "translateY(3px)" : undefined }}>
                {compact ? fmtMin(h).replace(":00 a.m.", "").replace(":00 p.m.", "") : fmtMin(h).replace(":00 ", " ")}
              </span>
            ))}
          </div>
          {days.map((d) => (
            <div className="col" key={d}>
              {hours.map((h) => (
                <div className="hline" key={h} style={{ top: (h - first) * px }} />
              ))}
              {meets
                .filter(({ m }) => m.days.includes(d))
                .map(({ s, m }, i) => (
                  <div className="block" key={`${s.unique}-${i}`} style={{ top: (m.start - first) * px, height: (m.end - m.start) * px - 2 }}>
                    <b>{s.code}</b>
                    {compact ? null : (
                      <>
                        <span>{fmtMin(m.start).replace(" a.m.", "").replace(" p.m.", "")}-{fmtMin(m.end)}</span>
                        <br />
                        <span>{m.building ? `${m.building} ${m.room ?? ""}` : s.mode ?? ""}</span>
                      </>
                    )}
                  </div>
                ))}
            </div>
          ))}
        </div>
      </div>
      {untimed.length ? (
        <p className="small muted" style={{ marginTop: 6 }}>
          No meeting time listed: {untimed.map((s) => `${s.code} (${s.unique})`).join(", ")}
        </p>
      ) : null}
    </div>
  );
}
