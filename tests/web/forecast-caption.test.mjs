// The forecast card's wording follows the API's back-test numbers (web/js/forecast.js): node --test tests/web/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { forecastCaption, formatDateRange, rangeLabel, sourceLine } from "../../web/js/forecast.js";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/api/${name}.json`, import.meta.url)));
const EMBR = fixture("forecast-EMBR"); // calibrated, 79% coverage (new API shape)
const MCAR = fixture("forecast-MCAR"); // older API shape: raw p10-p90 only, 47.5% coverage

/** A copy of the calibrated fixture with a different back-tested coverage. */
function withCoverage(coverage, calibrated = true) {
  const data = structuredClone(EMBR);
  data.model.interval = { ...data.model.interval, coverage, calibrated };
  return data;
}

test("the caption includes the year and the calibrated 80% range", () => {
  assert.equal(
    forecastCaption(EMBR),
    "For Tue, Jan 6, 2026 the model expected about 11,400 entries; 80% range 9,500–14,700.",
  );
});

test("80% range only when calibrated and within 5 points of 80%", () => {
  assert.equal(rangeLabel(EMBR.model), "80% range");
  assert.equal(rangeLabel(withCoverage(0.75).model), "80% range");
  assert.equal(rangeLabel(withCoverage(0.85).model), "80% range");
  for (const off of [0.74, 0.86, 0.705, 0.42]) {
    assert.equal(rangeLabel(withCoverage(off).model), "calibrated model range", String(off));
  }
  // not calibrated: never called an 80% range, even when its coverage happens to be close
  assert.equal(rangeLabel(withCoverage(0.8, false).model), "model range (10th–90th percentile)");
  assert.equal(rangeLabel(MCAR.model), "model range (10th–90th percentile)");
  assert.equal(rangeLabel(null), "model range (10th–90th percentile)");
  assert.match(forecastCaption(withCoverage(0.7)), /; calibrated model range 9,500–14,700\.$/);
});

test("an uncalibrated (older) response falls back to the 10th and 90th percentiles", () => {
  assert.equal(
    forecastCaption(MCAR),
    "For Tue, Jan 6, 2026 the model expected about 3,000 entries; model range (10th–90th percentile) 2,900–3,700.",
  );
});

test("the source line names the data, the window and the coverage against the target", () => {
  const line = sourceLine(EMBR);
  assert.ok(line.startsWith("Forecast from data through Dec 31, 2025. It covers Jan 1–14, 2026,"), line);
  assert.match(line, /the 14 days after the latest ridership BART has published\./);
  assert.match(line, /in back-testing it held 79% of actual days against an 80% target\.$/);
  assert.match(line, /The shaded band is the 80% range, calibrated on earlier back-test weeks;/);
  assert.doesNotMatch(line, /narrower|wider/);

  // the older response has no forecast_start/end: the window comes from the forecast rows
  const old = sourceLine(MCAR);
  assert.match(old, /It covers Jan 1–14, 2026,/);
  assert.match(
    old,
    /The shaded band is the model range \(10th–90th percentile\); in back-testing it held 48% of actual days against an 80% target, so it is narrower than it should be\.$/,
  );
});

test("coverage wording: narrower below 75%, wider above 85%, nothing in between", () => {
  assert.match(sourceLine(withCoverage(0.749)), /held 75% of actual days against an 80% target, so it is narrower than it should be\.$/);
  assert.match(sourceLine(withCoverage(0.75)), /held 75% of actual days against an 80% target\.$/);
  assert.match(sourceLine(withCoverage(0.85)), /held 85% of actual days against an 80% target\.$/);
  assert.match(sourceLine(withCoverage(0.9)), /held 90% of actual days against an 80% target, so it is wider than needed\.$/);
  // outside +-5 points a calibrated band is the "calibrated model range", and still says how it was made
  assert.match(
    sourceLine(withCoverage(0.9)),
    /The shaded band is the calibrated model range \(the model's 10th–90th percentile, widened using earlier back-test weeks\);/,
  );
});

test("date ranges carry the year once, or twice across New Year", () => {
  assert.equal(formatDateRange("2026-01-01", "2026-01-14"), "Jan 1–14, 2026");
  assert.equal(formatDateRange("2026-01-25", "2026-02-07"), "Jan 25 – Feb 7, 2026");
  assert.equal(formatDateRange("2025-12-25", "2026-01-07"), "Dec 25, 2025 – Jan 7, 2026");
});
