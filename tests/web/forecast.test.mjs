// Unit tests for the Forecast explorer's pure helpers (web/js/forecast.js): node --test tests/web/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { forecastCaption, matchStations } from "../../web/js/forecast.js";

const network = JSON.parse(readFileSync(new URL("../../web/data/network.json", import.meta.url)));
const stations = network.stations.map((s) => ({ code: s.code, name: s.name, short: s.short }));
const forecast = JSON.parse(readFileSync(new URL("./fixtures/api/forecast-MCAR.json", import.meta.url)));

test("station search matches names and codes, best first", () => {
  assert.equal(matchStations(stations, "mac")[0].code, "MCAR");
  assert.equal(matchStations(stations, "MCAR")[0].code, "MCAR");
  assert.equal(matchStations(stations, "embr")[0].code, "EMBR");
  assert.equal(matchStations(stations, "12")[0].code, "12TH");
  assert.equal(matchStations(stations, "  Powell ")[0].code, "POWL");
  assert.ok(matchStations(stations, "oakland").some((s) => s.code === "OAKL"));
  assert.deepEqual(matchStations(stations, "zzzz"), []);
  assert.equal(matchStations(stations, "").length, stations.length);
});

test("the caption describes the first Tuesday in plain English", () => {
  assert.equal(
    forecastCaption(forecast),
    "Expect about 3,000 entries on Tue, Jan 6, likely between 2,900 and 3,700.",
  );
  const noTuesday = { forecast: [{ date: "2026-01-01", p10: 40, p50: 52.4, p90: 61 }] };
  assert.equal(forecastCaption(noTuesday), "Expect about 52 entries on Thu, Jan 1, likely between 40 and 61.");
});
