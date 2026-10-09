// A calibrated band is p10/p90 widened by the conformal correction, so it must never be called the 10th–90th
// percentile (web/js/forecast.js, Revision 1 R1): node --test tests/web/forecast-label.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { forecastCaption, rangeLabel, sourceLine } from "../../web/js/forecast.js";

const EMBR = JSON.parse(readFileSync(new URL("./fixtures/api/forecast-EMBR.json", import.meta.url)));

test("a calibrated band off its target is not called the 10th–90th percentile", () => {
  const data = structuredClone(EMBR);
  data.model.interval = { ...data.model.interval, coverage: 0.73, calibrated: true };

  assert.equal(rangeLabel(data.model), "calibrated model range");

  // the caption's numbers are the calibrated lo/hi, not p10/p90
  const tuesday = data.forecast.find((d) => new Date(`${d.date}T00:00:00Z`).getUTCDay() === 2);
  assert.notEqual(tuesday.lo, tuesday.p10);
  assert.notEqual(tuesday.hi, tuesday.p90);
  const round = (v) => (Math.round(v / (v >= 1000 ? 100 : v >= 100 ? 10 : 1)) * (v >= 1000 ? 100 : v >= 100 ? 10 : 1)).toLocaleString("en-US");
  const caption = forecastCaption(data);
  assert.ok(caption.endsWith(`; calibrated model range ${round(tuesday.lo)}–${round(tuesday.hi)}.`), caption);

  const line = sourceLine(data);
  assert.match(line, /widened using earlier back-test weeks/);
  assert.match(line, /held 73% of actual days against an 80% target, so it is narrower than it should be\.$/);
  assert.ok(!line.includes("model range (10th–90th percentile)"), line);
  assert.ok(!caption.includes("10th–90th percentile"), caption);
});
