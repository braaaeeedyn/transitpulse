// The bundled GTFS timetable has an end date; after it the map must say so instead of "No trains running".
//   node --test tests/web/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { isOutsideTimetable, timetableRange } from "../../web/js/map/schedule.js";

const schedule = JSON.parse(readFileSync(new URL("../../web/data/schedule.json", import.meta.url)));

test("timetable expiry is detected", () => {
  const svc = (start, end, added = []) => ({ days: "1111100", start, end, added, removed: [] });
  const tiny = { services: [svc("20260810", "20270108"), svc("20260901", "20270110"), svc("20261001", "20261002", ["20270115"])] };
  assert.deepEqual(timetableRange(tiny), { start: "20260810", end: "20270115" }); // an added date extends it
  assert.equal(isOutsideTimetable(tiny, "20261007"), false);
  assert.equal(isOutsideTimetable(tiny, "20270115"), false);
  assert.equal(isOutsideTimetable(tiny, "20270116"), true);
  assert.equal(isOutsideTimetable(tiny, "20260809"), true);

  // the real bundled timetable: in service now, expired by Feb 2027
  const range = timetableRange(schedule);
  assert.match(range.start, /^\d{8}$/);
  assert.equal(isOutsideTimetable(schedule, "20261007"), false);
  assert.equal(isOutsideTimetable(schedule, "20270201"), true);
});
