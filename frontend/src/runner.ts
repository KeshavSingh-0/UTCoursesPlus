// Pure logic for the adaptive registration runner. No DOM, so it can be tested on its own.
// The student reports what happened (got a section, it was full, give up on a course, dropped a section) and the
// server searches again with those facts. This file only keeps the reports and decides where the cursor goes.
import type { RegStep } from "./api.ts";

export type Snapshot = {
  registered: string[]; // unique numbers now held
  full: string[]; // unique numbers that were full or refused
  dropped: string[]; // unique numbers dropped on the plan's advice
  skipped: string[]; // course codes given up on
  at?: string; // course the report that led here was about, so undo can bring it back into view
};
export type Adapt = Snapshot & { history: Snapshot[] };
export type Action = "got" | "full" | "skip" | "drop";

export const empty = (): Adapt => ({ registered: [], full: [], dropped: [], skipped: [], history: [] });

const snap = (a: Adapt, at?: string): Snapshot => ({ registered: a.registered, full: a.full, dropped: a.dropped, skipped: a.skipped, at });
const add = (xs: string[], x: string) => (xs.includes(x) ? xs : [...xs, x]);

/** True once the student has reported anything, so the plan has to be searched again. */
export const touched = (a: Adapt) => a.history.length > 0;

const push = (a: Adapt, next: Snapshot, at?: string): Adapt => ({ ...next, at, history: [...a.history, snap(a, at)] });

export const got = (a: Adapt, unique: string, code?: string): Adapt =>
  a.registered.includes(unique) ? a : push(a, { ...snap(a), registered: [...a.registered, unique] }, code);

export const full = (a: Adapt, unique: string, code?: string): Adapt =>
  a.full.includes(unique) ? a : push(a, { ...snap(a), full: [...a.full, unique] }, code);

export const skipCourse = (a: Adapt, code: string): Adapt =>
  a.skipped.includes(code) ? a : push(a, { ...snap(a), skipped: [...a.skipped, code] }, code);

/** The student dropped these sections: they leave the registered list and are not offered again. */
export const dropSections = (a: Adapt, uniques: string[], code?: string): Adapt =>
  push(
    a,
    { ...snap(a), registered: a.registered.filter((u) => !uniques.includes(u)), dropped: uniques.reduce(add, a.dropped) },
    code,
  );

/** The course the most recent report was about, which is the one to show again after undoing it. */
export const lastCode = (a: Adapt): string | undefined => a.history[a.history.length - 1]?.at;

export function undo(a: Adapt): Adapt {
  const last = a.history[a.history.length - 1];
  if (!last) return a;
  const prev = a.history.slice(0, -1);
  return { ...last, at: prev[prev.length - 1]?.at, history: prev };
}

export const requestBody = (a: Adapt, previous: string[]) => ({
  registered: a.registered, full: a.full, dropped: a.dropped, skipped: a.skipped, previous,
});

/** Where the cursor goes after the plan is searched again. Returns an index into the new steps. */
export function nextCursor(oldSteps: RegStep[], code: string | undefined, action: Action | "undo", newSteps: RegStep[]): number {
  if (!newSteps.length) return 0;
  const idx = (c: string) => newSteps.findIndex((s) => s.code === c);
  if (code && (action === "full" || action === "undo" || action === "drop")) {
    const i = idx(code);
    if (i >= 0) return i; // same course, now showing its next best section
  }
  if (code) {
    const here = oldSteps.findIndex((s) => s.code === code);
    for (const s of oldSteps.slice(here + 1)) {
      const i = idx(s.code);
      if (i >= 0) return i;
    }
  }
  return 0;
}

export const progress = (a: Adapt, steps: RegStep[]) => ({
  registered: a.registered.length, skipped: a.skipped.length, remaining: steps.length,
});

/** Identity of the plan the saved reports belong to, so they are not applied to a different schedule. */
export const planKey = (steps: RegStep[]) => steps.map((s) => `${s.code}:${s.options[0]?.unique}`).join("|");
