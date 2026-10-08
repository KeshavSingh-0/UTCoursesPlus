// Pure logic for the keyboard registration runner. No DOM, so it can be tested on its own.
import type { RegOption, RegStep } from "./api.ts";

export type RunState = {
  cur: number; // index of the course being worked on
  choice: Record<string, number>; // course code -> index of the option currently shown
  done: Record<string, string | null>; // course code -> unique number registered, or null if skipped
  log: string[]; // course codes in the order they were finished, for undo
};

export const initialState = (): RunState => ({ cur: 0, choice: {}, done: {}, log: [] });

export function overlaps(a: RegOption, b: RegOption): boolean {
  for (const x of a.meets) for (const y of b.meets) {
    if (x.days.some((d) => y.days.includes(d)) && x.start < y.end && y.start < x.end) return true;
  }
  return false;
}

export const chosen = (step: RegStep, st: RunState): RegOption => step.options[st.choice[step.code] ?? 0] ?? step.options[0];

/** Sections already registered, with the course each belongs to. */
export function confirmed(steps: RegStep[], st: RunState): { code: string; opt: RegOption }[] {
  const out: { code: string; opt: RegOption }[] = [];
  for (const s of steps) {
    const u = st.done[s.code];
    const opt = u ? s.options.find((o) => o.unique === u) : undefined;
    if (opt) out.push({ code: s.code, opt });
  }
  return out;
}

/** Course codes whose registered section overlaps this option in time. */
export function clashWithRegistered(steps: RegStep[], st: RunState, step: RegStep, opt: RegOption): string[] {
  return confirmed(steps, st).filter((c) => c.code !== step.code && overlaps(opt, c.opt)).map((c) => c.code);
}

/** Course codes still to do whose currently shown option overlaps this one (a warning, not a block). */
export function clashWithPending(steps: RegStep[], st: RunState, step: RegStep, opt: RegOption): string[] {
  return steps
    .filter((s) => s.code !== step.code && st.done[s.code] === undefined && overlaps(opt, chosen(s, st)))
    .map((s) => s.code);
}

/** Move to the next or previous option of the current course, skipping any that clash with sections already registered. */
export function moveOption(steps: RegStep[], st: RunState, dir: 1 | -1): RunState {
  const step = steps[st.cur];
  if (!step) return st;
  const n = step.options.length;
  const start = st.choice[step.code] ?? 0;
  for (let k = 1; k <= n; k++) {
    const i = (((start + dir * k) % n) + n) % n;
    if (clashWithRegistered(steps, st, step, step.options[i]).length === 0) {
      return { ...st, choice: { ...st.choice, [step.code]: i } };
    }
  }
  return st;
}

export function moveCourse(steps: RegStep[], st: RunState, dir: 1 | -1): RunState {
  const cur = Math.max(0, Math.min(steps.length - 1, st.cur + dir));
  return { ...st, cur };
}

function nextOpen(steps: RegStep[], st: RunState, from: number): number {
  for (let k = 1; k <= steps.length; k++) {
    const i = (from + k) % steps.length;
    if (st.done[steps[i].code] === undefined) return i;
  }
  return from;
}

/** Mark the option on screen as registered and move to the next course that is still open. */
export function confirm(steps: RegStep[], st: RunState): RunState {
  const step = steps[st.cur];
  if (!step || st.done[step.code] !== undefined) return st;
  const done = { ...st.done, [step.code]: chosen(step, st).unique };
  const next = { ...st, done, log: [...st.log, step.code] };
  return { ...next, cur: nextOpen(steps, next, st.cur) };
}

export function skip(steps: RegStep[], st: RunState): RunState {
  const step = steps[st.cur];
  if (!step || st.done[step.code] !== undefined) return st;
  const next = { ...st, done: { ...st.done, [step.code]: null }, log: [...st.log, step.code] };
  return { ...next, cur: nextOpen(steps, next, st.cur) };
}

export function undo(steps: RegStep[], st: RunState): RunState {
  const code = st.log[st.log.length - 1];
  if (!code) return st;
  const done = { ...st.done };
  delete done[code];
  return { ...st, done, log: st.log.slice(0, -1), cur: Math.max(0, steps.findIndex((s) => s.code === code)) };
}

export function progress(steps: RegStep[], st: RunState) {
  const vals = steps.map((s) => st.done[s.code]);
  return { registered: vals.filter((v) => typeof v === "string").length, skipped: vals.filter((v) => v === null).length, remaining: vals.filter((v) => v === undefined).length };
}

/** Changes whenever the plan changes, so saved progress is not applied to a different schedule. */
export const planKey = (steps: RegStep[]) => steps.map((s) => `${s.code}:${s.options[0]?.unique}`).join("|");
