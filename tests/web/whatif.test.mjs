// The map's "what if stations close?" picker (web/js/map/whatif.js): node --test tests/web/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { AT_RISK, presetOf, whatIfStatus } from "../../web/js/map/whatif.js";

test("the picker's list is the dbt seed's list", () => {
  const rows = readFileSync(new URL("../../dbt/transitpulse/seeds/bart_closure_candidates.csv", import.meta.url), "utf-8")
    .trim()
    .split(/\r?\n/)
    .slice(1)
    .map((r) => r.split(","));
  const group = (g) => rows.filter((r) => r[1] === g).map((r) => r[0]).toSorted();
  assert.deepEqual(AT_RISK.first10.toSorted(), group("1"));
  assert.deepEqual(AT_RISK.next5.toSorted(), group("2"));
  const network = JSON.parse(readFileSync(new URL("../../web/data/network.json", import.meta.url)));
  const codes = new Set(network.stations.map((s) => s.code));
  for (const c of [...AT_RISK.first10, ...AT_RISK.next5]) assert.ok(codes.has(c), c);
});

test("presets are recognised in any order", () => {
  assert.equal(presetOf([]), "none");
  assert.equal(presetOf([...AT_RISK.first10].reverse()), "first10");
  assert.equal(presetOf([...AT_RISK.next5, ...AT_RISK.first10]), "all15");
  assert.equal(presetOf(["OAKL"]), null);
});

test("status line: today, presets with exact shares, a custom pick as an upper bound", () => {
  assert.equal(whatIfStatus([], 50, null), "Today's map: all 50 stations open.");
  const closures = {
    system: { share_first_10: 0.1256, share_all_15: 0.2412 },
    stations: [
      { code: "OAKL", share_of_trips: 0.006 },
      { code: "ORIN", share_of_trips: 0.016 },
    ],
  };
  assert.equal(
    whatIfStatus(AT_RISK.first10, 50, closures),
    "10 of 50 stations closed. The same trains run through them without stopping. 12.6% of weekday trips start or end at them.",
  );
  assert.match(whatIfStatus([...AT_RISK.first10, ...AT_RISK.next5], 50, closures), /24\.1% of weekday trips/);
  assert.equal(
    whatIfStatus(["OAKL"], 50, closures),
    "1 of 50 stations closed. The same trains run through it without stopping. Up to 0.6% of weekday trips start or end at it.",
  );
  assert.equal(whatIfStatus(["OAKL", "ORIN"], 50, null), "2 of 50 stations closed. The same trains run through them without stopping.");
});
