import assert from "node:assert/strict";
import test from "node:test";
import type { RegOption, RegStep } from "./api.ts";
import { chosen, clashWithPending, confirm, confirmed, initialState, moveCourse, moveOption, progress, skip, undo } from "./runner.ts";

const opt = (unique: string, days: string[], start: number, end: number, status = "open"): RegOption => ({
  unique, when: "", status, reserved: false, instructors: [], meets: [{ days, start, end }], conflicts: [],
});
const step = (code: string, order: number, options: RegOption[]): RegStep =>
  ({ code, order, options, credits: 3, title: code, unique: options[0].unique, when: "", status: "open", reserved: false, scarcity: 0, reasons: [], fallback: null, fetched_at: "" }) as RegStep;

const steps = [
  step("C S 312", 1, [opt("100", ["M", "W"], 540, 600, "closed"), opt("101", ["T", "TH"], 540, 600), opt("102", ["F"], 540, 600)]),
  step("M 408C", 2, [opt("200", ["T", "TH"], 560, 620), opt("201", ["M", "W"], 700, 760)]),
  step("E 316L", 3, [opt("300", ["F"], 800, 860)]),
];

test("right arrow cycles through options of the current course and wraps", () => {
  let st = initialState();
  st = moveOption(steps, st, 1);
  assert.equal(chosen(steps[0], st).unique, "101");
  st = moveOption(steps, moveOption(steps, st, 1), 1);
  assert.equal(chosen(steps[0], st).unique, "100");
  assert.equal(chosen(steps[0], moveOption(steps, st, -1)).unique, "102");
});

test("space confirms the shown option and moves to the next open course", () => {
  let st = moveOption(steps, initialState(), 1); // 101 (Tue/Thu)
  st = confirm(steps, st);
  assert.deepEqual(st.done, { "C S 312": "101" });
  assert.equal(st.cur, 1);
  assert.deepEqual(progress(steps, st), { registered: 1, skipped: 0, remaining: 2 });
});

test("options that clash with a registered section are skipped when cycling", () => {
  let st = moveOption(steps, initialState(), 1); // pick 101 (Tue/Thu 9:00-10:00)
  st = confirm(steps, st); // now on M 408C; option 200 is Tue/Thu 9:20-10:20 and clashes
  assert.equal(chosen(steps[1], st).unique, "200"); // shown first, so the warning is visible
  st = moveOption(steps, st, 1);
  assert.equal(chosen(steps[1], st).unique, "201"); // 200 is not offered again after moving off it
  st = moveOption(steps, st, 1);
  assert.equal(chosen(steps[1], st).unique, "201"); // the only non-clashing option stays put
});

test("pending clashes are reported as warnings against what is currently shown", () => {
  const st = initialState();
  assert.deepEqual(clashWithPending(steps, st, steps[0], steps[0].options[1]), ["M 408C"]);
  assert.deepEqual(clashWithPending(steps, st, steps[0], steps[0].options[0]), []);
});

test("undo restores the last finished course and selects it again", () => {
  let st = confirm(steps, initialState());
  st = skip(steps, st); // skip M 408C
  assert.deepEqual(progress(steps, st), { registered: 1, skipped: 1, remaining: 1 });
  st = undo(steps, st);
  assert.equal(st.cur, 1);
  assert.equal(st.done["M 408C"], undefined);
  assert.equal(confirmed(steps, st).length, 1);
});

test("finishing every course leaves the cursor in range and ignores extra confirms", () => {
  let st = initialState();
  for (let i = 0; i < 5; i++) st = confirm(steps, st);
  assert.deepEqual(progress(steps, st), { registered: 3, skipped: 0, remaining: 0 });
  assert.ok(st.cur >= 0 && st.cur < steps.length);
  assert.equal(moveCourse(steps, st, 1).cur <= steps.length - 1, true);
});
