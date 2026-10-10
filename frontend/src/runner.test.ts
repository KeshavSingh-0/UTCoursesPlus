import assert from "node:assert/strict";
import test from "node:test";
import type { RegStep } from "./api.ts";
import { dropSections, empty, full, got, lastCode, nextCursor, progress, requestBody, skipCourse, touched, undo } from "./runner.ts";

const step = (code: string, order: number, uniques: string[]): RegStep =>
  ({ code, order, options: uniques.map((unique) => ({ unique, when: "", status: "open", reserved: false, instructors: [], meets: [], conflicts: [] })),
    credits: 3, title: code, unique: uniques[0], when: "", status: "open", reserved: false, scarcity: 0, reasons: [], fallback: null, fetched_at: "" }) as RegStep;

const steps = [step("C S 312", 1, ["100", "101"]), step("M 408C", 2, ["200"]), step("E 316L", 3, ["300"])];

test("nothing reported means nothing to search again", () => {
  assert.equal(touched(empty()), false);
  assert.equal(touched(got(empty(), "100")), true);
});

test("reports accumulate once each and undo walks them back in order", () => {
  let a = got(empty(), "100");
  a = full(a, "200");
  a = skipCourse(a, "E 316L");
  assert.deepEqual([a.registered, a.full, a.skipped], [["100"], ["200"], ["E 316L"]]);
  assert.equal(got(a, "100"), a); // repeating a report changes nothing and adds no history
  a = undo(a);
  assert.deepEqual(a.skipped, []);
  a = undo(undo(a));
  assert.deepEqual([a.registered, a.full, a.history.length], [[], [], 0]);
  assert.equal(undo(a), a);
});

test("dropping a section frees it and keeps it from coming back", () => {
  const a = dropSections(got(got(empty(), "100"), "200"), ["100"]);
  assert.deepEqual([a.registered, a.dropped], [["200"], ["100"]]);
  assert.deepEqual(undo(a).registered, ["100", "200"]);
});

test("the request carries every report and the steps being followed", () => {
  const a = full(got(empty(), "100"), "200");
  assert.deepEqual(requestBody(a, ["300"]), { registered: ["100"], full: ["200"], dropped: [], skipped: [], previous: ["300"] });
});

test("after getting a course the cursor moves on; after a full section it stays on the course", () => {
  const next = [steps[1], steps[2]]; // C S 312 is now registered and gone from the steps
  assert.equal(nextCursor(steps, "C S 312", "got", next), 0);
  assert.equal(nextCursor(steps, "M 408C", "got", [steps[0], steps[2]]), 1);
  assert.equal(nextCursor(steps, "C S 312", "full", steps), 0);
  assert.equal(nextCursor(steps, "M 408C", "full", steps), 1);
});

test("a course that left the plan hands the cursor to the next one that is still there", () => {
  assert.equal(nextCursor(steps, "M 408C", "full", [steps[0], steps[2]]), 1);
  assert.equal(nextCursor(steps, "E 316L", "got", [steps[0], steps[1]]), 0);
  assert.equal(nextCursor(steps, "C S 312", "skip", []), 0);
});

test("progress counts what is registered, given up and still to do", () => {
  const a = skipCourse(got(empty(), "100"), "E 316L");
  assert.deepEqual(progress(a, [steps[1]]), { registered: 1, skipped: 1, remaining: 1 });
});

test("undo remembers which course the undone report was about", () => {
  let a = got(empty(), "100", "C S 312");
  a = skipCourse(a, "E 316L");
  assert.equal(lastCode(a), "E 316L");
  a = undo(a);
  assert.equal(lastCode(a), "C S 312");
  assert.equal(nextCursor(steps, lastCode(skipCourse(empty(), "E 316L")), "undo", steps), 2);
});
