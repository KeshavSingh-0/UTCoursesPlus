export class ApiError extends Error {}

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: init?.method ?? (init?.body !== undefined ? "POST" : "GET"),
      headers: init?.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiError("Could not reach the local server. Start it with: uv run utcoursesplus serve");
  }
  if (!res.ok) {
    let detail = `The server returned ${res.status}.`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") detail = j.detail;
      else if (Array.isArray(j.detail) && j.detail[0]?.msg) detail = `${j.detail[0].msg} (${j.detail[0].loc?.join(".")})`;
    } catch {
      /* keep default */
    }
    throw new ApiError(detail);
  }
  return res.json() as Promise<T>;
}

export type Status = { term: string; sections: number; courses: number; departments: number; has_data: boolean; llm_configured: boolean; model: string; buildings_loaded: boolean };
export type Meet = { days: string[]; start: number; end: number; building: string | null; room: string | null };
export type Signal = {
  ease: number | null; ease_lo: number | null; ease_hi: number | null;
  ease_score: number | null; ease_score_lo: number | null; ease_score_hi: number | null;
  confidence: "None" | "Low" | "Medium" | "High"; lightness: number | null; lightness_coverage: number;
  gpa: number | null; n_graded: number; rmp_difficulty: number | null; rmp_rating: number | null; rmp_n: number; signals: string[];
  difficulty_sources?: string[]; quality?: number | null; a_rate?: number | null; drop_rate?: number | null;
};
export type Section = {
  unique: string; code: string; title: string; credits: number; status: string; reserved: boolean; mode: string | null;
  instructors: string[]; core: string[]; level: string | null; when: string; meets: Meet[]; source_url: string; fetched_at: string;
  signal?: Signal;
};
export type CoreArea = { code: string; name: string };
export type Group = { name: string; kind: "core_area" | "required_course" | "choose_from" | "elective"; core_code: string | null; courses: string[]; pick: number; credit_hours_needed: number | null };
export type Requirements = { core_areas: string[]; required_courses: string[]; preferred_courses: string[]; pinned_sections: Record<string, string[]>; groups: Group[]; elective_depts: string[]; registration_time: string | null };
export type TimeBlock = { days: string[]; start_min: number; end_min: number };
export type Hard = {
  earliest_start_min: number | null; latest_end_min: number | null; days_off: string[]; max_gap_min: number | null; max_walk_min: number | null;
  credit_min: number; credit_max: number; excluded_instructors: string[]; excluded_sections: string[]; excluded_times: TimeBlock[]; required_courses?: string[];
};
export type Weights = Record<"ease" | "syllabus_lightness" | "professor_quality" | "time_of_day" | "compactness" | "few_gaps" | "walking" | "seat_availability" | "wishlist", number>;
export type Prefs = { hard: Hard; weights: Weights; time_bias: number };
export type HistoryItem = { id: number; at: string; note: string };
export type DiffRow = { path: string; old: unknown; new: unknown; phrase: string | null; rationale: string };
export type Proposal = { question: string | null; tradeoff: string | null; config: Prefs | null; diff: DiffRow[] };
export type Schedule = {
  credits: number; utility: number; slots: string[]; features: Record<string, number>; contributions: Record<string, number>;
  sections: Section[]; why?: string[]; wish_included?: string[];
};
export type RegOption = {
  unique: string; when: string; status: string; reserved: boolean; instructors: string[];
  meets: { days: string[]; start: number; end: number }[]; conflicts: string[];
};
export type RegStep = {
  options: RegOption[]; credits: number;
  order: number; unique: string; code: string; title: string; when: string; status: string; reserved: boolean; scarcity: number; reasons: string[];
  fallback: { unique: string; when: string; status: string; instructors: string[] } | null; fetched_at: string;
};
export type GenResult = {
  problems: string[]; notes: string[]; truncated: boolean; searched: number; schedules: Schedule[]; backups: Schedule[];
  registration: { steps: RegStep[]; label: string; registration_time: string | null } | null; weights: Record<string, number>; change: string[];
  deferrals: { kind: "course" | "core"; key: string; label: string; utility: number }[]; plan_tree: PlanTree | null;
};
export type PlanOption = RegOption & { planned: boolean };
export type PlanAlt = { code: string; title: string; credits: number; sections: number; rank: number; ease_score: number | null; confidence: string;
  best: { unique: string; when: string; status: string; reserved: boolean; instructors: string[] } };
export type PlanItem = {
  key: string; code: string | null; title: string | null; credits: number | null; included: boolean; slot: string; rank: number | null;
  area?: string; options: PlanOption[]; alternatives: PlanAlt[]; reason: string | null;
};
export type PlanTree = {
  root: { title: string; credits: number; courses: number; utility: number };
  groups: { id: "required" | "core" | "like" | "elective"; title: string; items: PlanItem[] }[];
  backups: { index: number; credits: number; utility: number; sections: { unique: string; code: string; title: string; when: string; status: string; shared: boolean }[] }[];
};
export type SettingsView = {
  key_source: "saved" | "environment" | null; key_hint: string | null; default_model: string; models: Record<string, string>;
  tasks: Record<string, string>; fallback_models: string[];
};
export type CompareRow = {
  unique: string; section: Section | null; fits: boolean; utility: number | null; delta: number | null; why: string[]; problems: string[]; schedule: Schedule | null;
};
export type Compare = { code: string; in_plan_as: string; rows: CompareRow[]; best_utility: number | null };
export type Suggestion = {
  area: string; total: number;
  courses: { code: string; title: string; credits: number; rank: number;
    signal: { ease_score: number | null; ease_score_lo: number | null; ease_score_hi: number | null; confidence: string; signals: string[]; lightness: number | null; gpa: number | null; rmp_rating: number | null };
    sections: { unique: string; when: string; status: string; reserved: boolean; instructors: string[] }[] }[];
};

export const FEATURE_LABELS: Record<string, string> = {
  ease: "Ease (grades and professor difficulty)", syllabus_lightness: "Syllabus lightness", professor_quality: "Professor rating",
  time_of_day: "Time-of-day fit", compactness: "Fewer days on campus", few_gaps: "Fewer gaps", walking: "Short walks", seat_availability: "Seat availability", wishlist: "Preferred courses included",
};

export function fmtMin(m: number | null | undefined): string {
  if (m === null || m === undefined) return "none";
  const h = Math.floor(m / 60), mi = m % 60;
  return `${h % 12 || 12}:${String(mi).padStart(2, "0")} ${h < 12 ? "a.m." : "p.m."}`;
}
export function toTimeInput(m: number | null): string {
  return m === null ? "" : `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
export function fromTimeInput(s: string): number | null {
  if (!s) return null;
  const [h, m] = s.split(":").map(Number);
  return h * 60 + m;
}
export const f2 = (x: number | null | undefined) => (x === null || x === undefined ? "none" : x.toFixed(2));
