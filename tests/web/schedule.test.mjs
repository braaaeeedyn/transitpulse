// Unit tests for the browser's schedule maths (web/js/map/schedule.js), run with Node's built-in runner:
//   node --test tests/web/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { serviceRunsOn, trainsAt, tripPosition, tripsForDay } from "../../web/js/map/schedule.js";
import { formatClock, shiftDay } from "../../web/js/util/time.js";

const schedule = JSON.parse(readFileSync(new URL("../../web/data/schedule.json", import.meta.url)));

const entry = { start: 600, end: 620, profile: [0, 1, 9, 10, 20, 20] }; // 3 stops: dwell 1 min, run 8, dwell 1, run 10

test("trip position: dwelling, moving, and outside the trip", () => {
  assert.equal(tripPosition(entry, 599), null);
  assert.deepEqual(
    { ...tripPosition(entry, 600.5), nextAt: undefined },
    { hop: -1, frac: 0, stop: 0, atStation: true, next: 1, nextAt: undefined },
  );
  const mid = tripPosition(entry, 605); // halfway between dep 1 and arr 9
  assert.equal(mid.atStation, false);
  assert.equal(mid.hop, 0);
  assert.equal(mid.frac, 0.5);
  assert.equal(mid.nextAt, 609);
  const end = tripPosition(entry, 620);
  assert.equal(end.atStation, true);
  assert.equal(end.next, null);
  assert.equal(tripPosition(entry, 621), null);
});

test("service calendar: weekday rules and exceptions", () => {
  const svc = { days: "1111100", start: "20260810", end: "20270108", added: [], removed: ["20261126"] };
  assert.equal(serviceRunsOn(svc, "20261007", 2), true); // Wed
  assert.equal(serviceRunsOn(svc, "20261010", 5), false); // Sat
  assert.equal(serviceRunsOn(svc, "20261126", 3), false); // Thanksgiving removed
  assert.equal(serviceRunsOn({ ...svc, days: "0000000", added: ["20261126"], removed: [] }, "20261126", 3), true);
});

test("real schedule: trains run at weekday rush hour, none at 3 AM", () => {
  const days = {};
  const rush = trainsAt(schedule, days, "20261007", 2, 8 * 60 + 15);
  assert.ok(rush.length > 30, `expected many trains, got ${rush.length}`);
  const night = trainsAt(schedule, days, "20261007", 2, 3 * 60);
  assert.equal(night.length, 0);
});

test("after-midnight trips count toward the previous service day", () => {
  const days = {};
  const lateTrips = tripsForDay(schedule, "20261007", 2).filter((e) => e.end > 1440);
  assert.ok(lateTrips.length > 0, "the feed has trips that run past midnight");
  const t = lateTrips[0].start + 1; // a minute into one of them
  const asNextDay = trainsAt(schedule, {}, shiftDay("20261007", 1).ymd, 3, t - 1440);
  if (t >= 1440) assert.ok(asNextDay.some((tr) => tr.serviceDay === "20261007"));
  const asMinutesPast = trainsAt(schedule, {}, "20261007", 2, t);
  assert.ok(asMinutesPast.some((tr) => tr.entry.trip === lateTrips[0].trip));
});

test("clock formatting", () => {
  assert.equal(formatClock(0), "12:00 AM");
  assert.equal(formatClock(495), "8:15 AM");
  assert.equal(formatClock(780), "1:00 PM");
  assert.equal(formatClock(1500), "1:00 AM");
});
