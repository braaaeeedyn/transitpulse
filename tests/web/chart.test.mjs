// Unit tests for the chart helpers (web/js/chart.js): node --test tests/web/
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bandPath,
  formatCompact,
  formatDate,
  formatDay,
  formatDelta,
  formatMonth,
  formatNumber,
  formatPercent,
  linePath,
  monthIndex,
  niceTicks,
  scaleLinear,
  tickCount,
  yearTicks,
} from "../../web/js/chart.js";

const identity = (v) => v;

test("nice ticks are round numbers that cover the data", () => {
  assert.deepEqual(niceTicks(0, 324958, 5), [0, 100000, 200000, 300000, 400000]);
  assert.deepEqual(niceTicks(0, 1, 5), [0, 0.2, 0.4, 0.6, 0.8, 1]);
  assert.deepEqual(niceTicks(0, 95, 3), [0, 50, 100]);
  const t = niceTicks(11234, 13987, 5);
  assert.ok(t[0] <= 11234 && t[t.length - 1] >= 13987);
  for (let i = 1; i < t.length; i++) assert.equal(t[i] - t[i - 1], t[1] - t[0]);
  assert.deepEqual(niceTicks(0, 0), [0]);
  assert.deepEqual(niceTicks(Number.NaN, 5), []);
});

test("narrow cards get fewer ticks", () => {
  assert.ok(tickCount(320) < tickCount(1200));
  assert.equal(tickCount(599), 3);
  assert.equal(tickCount(600), 5);
  const wide = niceTicks(0, 324958, tickCount(1200));
  const narrow = niceTicks(0, 324958, tickCount(400));
  assert.ok(narrow.length < wide.length);
  // year labels: every year when wide, every other year below 600 px
  const from = monthIndex("2018-01-01");
  const to = monthIndex("2025-12-01");
  assert.equal(yearTicks(from, to, 1200).length, 8);
  assert.equal(yearTicks(from, to, 400).length, 4);
  assert.deepEqual(yearTicks(from, to, 1200)[0], { value: 2018 * 12, label: "2018" });
});

test("scales map the domain onto the range", () => {
  const y = scaleLinear([0, 100], [200, 0]);
  assert.equal(y(0), 200);
  assert.equal(y(50), 100);
  assert.equal(y(100), 0);
  assert.equal(scaleLinear([5, 5], [0, 10])(5), 0);
});

test("line path breaks at missing months instead of bridging them", () => {
  const pts = [
    { x: monthIndex("2019-11-01"), y: 1 },
    { x: monthIndex("2019-12-01"), y: 2 },
    { x: monthIndex("2025-01-01"), y: 3 }, // 61-month gap
    { x: monthIndex("2025-02-01"), y: 4 },
  ];
  const x = (v) => v - pts[0].x;
  const d = linePath(pts, x, identity);
  assert.equal((d.match(/M/g) ?? []).length, 2);
  assert.equal(d, "M0,1L1,2M62,3L63,4");
  // a null value also breaks the line; a lone point stays visible
  const d2 = linePath([{ x: 0, y: 1 }, { x: 1, y: null }, { x: 2, y: 3 }], identity, identity);
  assert.equal(d2, "M0,1h0.01M2,3h0.01");
  // consecutive months: one segment
  assert.equal(linePath([{ x: 0, y: 1 }, { x: 1, y: 2 }, { x: 2, y: 3 }], identity, identity), "M0,1L1,2L2,3");
  assert.equal(linePath([], identity, identity), "");
});

test("band path closes each segment between its low and high edges", () => {
  const d = bandPath([{ x: 0, lo: 1, hi: 3 }, { x: 1, lo: 2, hi: 4 }], identity, identity);
  assert.equal(d, "M0,3L1,4L1,2L0,1Z");
});

test("numbers, percentages, deltas and dates are formatted for people", () => {
  assert.equal(formatNumber(149335.2), "149,335");
  assert.equal(formatNumber(null), "—");
  assert.equal(formatCompact(150000), "150K");
  assert.equal(formatCompact(1200000), "1.2M");
  assert.equal(formatCompact(0), "0");
  assert.equal(formatCompact(2500), "2.5K");
  assert.equal(formatPercent(0.4312), "43%");
  assert.equal(formatPercent(0.10706, 1), "10.7%");
  assert.equal(formatPercent(undefined), "—");
  assert.equal(formatDelta(0.042, "percent"), "▲ 4.2 pts");
  assert.equal(formatDelta(-0.0087, "percent"), "▼ 0.9 pts");
  assert.equal(formatDelta(0.031, "entries"), "▲ 3.1%");
  assert.equal(formatDelta(0, "entries"), "0.0%");
  assert.equal(formatDelta(null, "entries"), "");
  assert.equal(formatDate("2025-12-31"), "Dec 31, 2025");
  assert.equal(formatDate("2026-01-06T00:00:00"), "Jan 6, 2026");
  assert.equal(formatDay("2026-01-06"), "Tue, Jan 6");
  assert.equal(formatMonth("2025-12-01"), "Dec 2025");
});
