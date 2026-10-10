import { useCallback, useEffect, useState } from "react";
import { CalendarDays, ClipboardList, Database, FileText, KeyRound, ListChecks, Network, SlidersHorizontal, Table2 } from "lucide-react";
import { api } from "./api";
import type { GenResult, Status } from "./api";
import { CoursesScreen } from "./Courses";
import { ModelsScreen } from "./Models";
import { PlanMapScreen } from "./PlanMap";
import { PreferencesScreen } from "./Preferences";
import { RegistrationScreen } from "./Registration";
import { RequirementsScreen } from "./Requirements";
import { SchedulesScreen } from "./Schedules";
import { SourcesScreen } from "./Sources";
import { SyllabiScreen } from "./Syllabi";
import { Note } from "./ui";

const SCREENS = [
  { id: "requirements", label: "Requirements", icon: ListChecks },
  { id: "courses", label: "Courses and sections", icon: Table2 },
  { id: "preferences", label: "Preferences", icon: SlidersHorizontal },
  { id: "schedules", label: "Ranked schedules", icon: CalendarDays },
  { id: "planmap", label: "Plan map", icon: Network },
  { id: "registration", label: "Registration plan", icon: ClipboardList },
  { id: "syllabi", label: "Syllabi", icon: FileText },
  { id: "sources", label: "Data sources", icon: Database },
  { id: "models", label: "AI models", icon: KeyRound },
] as const;
type Id = (typeof SCREENS)[number]["id"];

export function App() {
  const [screen, setScreen] = useState<Id>(() => (SCREENS.find((s) => s.id === location.hash.slice(1))?.id ?? "requirements") as Id);
  const [status, setStatus] = useState<Status | null>(null);
  const [fatal, setFatal] = useState("");
  const [result, setResult] = useState<GenResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [genErr, setGenErr] = useState("");

  const refreshStatus = useCallback(() => { api<Status>("/api/status").then(setStatus).catch((e) => setFatal((e as Error).message)); }, []);
  useEffect(() => {
    refreshStatus();
    const on = () => { const id = SCREENS.find((s) => s.id === location.hash.slice(1))?.id; if (id) setScreen(id); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => { document.title = `${SCREENS.find((s) => s.id === screen)?.label} | UT Courses Plus`; }, [screen]);

  const generate = useCallback(async (): Promise<GenResult | null> => {
    setBusy(true); setGenErr("");
    try { const r = await api<GenResult>("/api/schedules/generate", { body: { k: 8 } }); setResult(r); return r; }
    catch (e) { setGenErr((e as Error).message); return null; }
    finally { setBusy(false); }
  }, []);

  const go = (id: Id) => { location.hash = id; setScreen(id); };
  if (fatal) return <main><Note error>{fatal}</Note></main>;
  if (!status) return <main><p className="muted">Loading.</p></main>;

  return (
    <div className="app">
      <a className="skip" href="#content">Skip to content</a>
      <nav className="nav" aria-label="Main">
        <div className="brand">UT Courses Plus</div>
        <div className="brand-sub">Spring 2027 planner</div>
        <ul>
          {SCREENS.map(({ id, label, icon: Icon }) => (
            <li key={id}>
              <button className="link" aria-current={screen === id ? "page" : undefined} onClick={() => go(id)}>
                <Icon size={16} aria-hidden /> {label}
              </button>
            </li>
          ))}
        </ul>
        <p className="foot xs muted">Spring 2027. {status.sections.toLocaleString()} sections loaded. Everything stays on this computer.</p>
      </nav>
      <main id="content" tabIndex={-1}>
        {screen === "requirements" && <RequirementsScreen status={status} />}
        {screen === "courses" && <CoursesScreen status={status} />}
        {screen === "preferences" && <PreferencesScreen status={status} onChanged={generate} last={result} />}
        {screen === "schedules" && <SchedulesScreen status={status} result={result} busy={busy} error={genErr} onGenerate={generate} />}
        {screen === "planmap" && <PlanMapScreen status={status} />}
        {screen === "registration" && <RegistrationScreen status={status} result={result} />}
        {screen === "syllabi" && <SyllabiScreen />}
        {screen === "sources" && <SourcesScreen />}
        {screen === "models" && <ModelsScreen status={status} onChanged={refreshStatus} />}
      </main>
    </div>
  );
}
