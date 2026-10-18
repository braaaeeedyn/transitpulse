// The Station closures band's wording (web/js/closures.js): node --test tests/web/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  costSentence,
  formatMiles,
  formatWholePct,
  groupsHTML,
  listText,
  ruleStatus,
  rulesHTML,
  stationCardHTML,
  summarySentences,
  verdictLabel,
} from "../../web/js/closures.js";

const FIXTURE = JSON.parse(readFileSync(new URL("./fixtures/api/closures.json", import.meta.url)));

test("verdict labels and rule results are words, not colours", () => {
  assert.equal(verdictLabel("strong"), "Case to keep: strong");
  assert.equal(verdictLabel("mixed"), "Case to keep: mixed");
  assert.equal(verdictLabel("weak"), "Case to keep: weak");
  assert.equal(ruleStatus(true), "Met");
  assert.equal(ruleStatus(false), "Not met");
});

test("miles keep one decimal and percentages are shown as sent", () => {
  assert.equal(formatMiles(2.9), "2.9 mi");
  assert.equal(formatMiles(3), "3.0 mi");
  assert.equal(formatMiles(13.6), "13.6 mi");
  assert.equal(formatMiles(null), "—");
  assert.equal(formatWholePct(43), "43%");
  assert.equal(formatWholePct(0), "0%");
  assert.equal(formatWholePct(null), "—");
  assert.equal(formatWholePct(undefined), "—");
});

test("lists read as English", () => {
  assert.equal(listText([]), "");
  assert.equal(listText(["Milpitas"]), "Milpitas");
  assert.equal(listText(["Milpitas", "Berryessa"]), "Milpitas and Berryessa");
  assert.equal(listText(["A", "B", "C"]), "A, B and C");
});

const doc = (system, stations = FIXTURE.stations) => ({ ...FIXTURE, system: { ...FIXTURE.system, ...system }, stations });

test("summary sentences come from the data and name any least-used station that isn't listed", () => {
  const lowest = [
    ...Array.from({ length: 9 }, (_, i) => ({ code: `L${i}`, name: `Listed ${i}`, listed: true })),
    { code: "MLPT", name: "Milpitas", listed: false },
  ];
  const s = summarySentences(doc({ lowest_10: lowest, first_10_in_lowest_10: 9, share_first_10: 0.1256, share_all_15: 0.2412 }));
  assert.equal(
    s.lowest,
    `9 of the first 10 are among the 10 least-used stations in ${FIXTURE.period_year}. Also among them: Milpitas, which isn't on the list.`,
  );
  assert.equal(s.first10, `12.6% of weekday trips in ${FIXTURE.period_year} start or end at the first 10. The press reported about 12%.`);
  assert.equal(s.all15, "24.1% of weekday trips start or end at one of all 15.");

  const two = summarySentences(
    doc({
      lowest_10: [...lowest.slice(0, 8), { name: "Milpitas", listed: false }, { name: "Berryessa", listed: false }],
      first_10_in_lowest_10: 8,
    }),
  );
  assert.match(two.lowest, /^8 of the first 10 .* Also among them: Milpitas and Berryessa, which aren't on the list\.$/);

  const none = summarySentences(doc({ lowest_10: lowest.slice(0, 9).concat([{ name: "X", listed: true }]), first_10_in_lowest_10: 10 }));
  assert.equal(none.lowest, `10 of the first 10 are among the 10 least-used stations in ${FIXTURE.period_year}.`);
});

test("rules and the verdict mapping are the API's text", () => {
  const html = rulesHTML(FIXTURE);
  for (const r of FIXTURE.rules) assert.ok(html.includes(r.text.replace(/'/g, "&#39;")), r.id);
  for (const [v, text] of Object.entries(FIXTURE.verdicts)) {
    assert.ok(html.includes(`Case to keep: ${v}`), v);
    assert.ok(html.includes(text), text);
  }
  assert.equal(html.match(/data-rule=/g).length, FIXTURE.rules.length);
});

test("a station card shows its evidence and each rule as Met / Not met", () => {
  const st = FIXTURE.stations.find((s) => s.verdict === "strong");
  const html = stationCardHTML(st, FIXTURE);
  assert.ok(html.includes(`data-closure-station="${st.code}"`));
  assert.ok(html.includes(`data-verdict="strong"`));
  assert.ok(html.includes("Case to keep: strong"));
  assert.ok(html.includes(`${st.nearest_open.miles.toFixed(1)} mi`));
  assert.ok(html.includes(`rank ${st.rank_lowest} of ${FIXTURE.system.stations}`));
  assert.equal(html.match(/: Met</g).length, st.points);
  const weak = stationCardHTML({ ...st, criteria: { riders: false, recovery: true, distance: false }, verdict: "weak" }, FIXTURE);
  assert.equal(weak.match(/: Not met</g).length, FIXTURE.rules.length - 1);
  assert.equal(weak.match(/: Met</g).length, 1);
  const noBase = stationCardHTML({ ...st, recovery_pct: null }, FIXTURE);
  assert.ok(noBase.includes(`No full ${FIXTURE.baseline_year} to compare`));
});

test("the cost card's data line counts growing stations and the farthest one", () => {
  const st = (code, growing, distance, miles) => ({
    code,
    name: `Station ${code}`,
    criteria: { growing, distance },
    nearest_open: { name: `Open ${code}`, miles },
  });
  const doc = { period_year: 2025, system: { share_all_15: 0.241 }, stations: [st("A", true, true, 5.6), st("B", true, true, 13.6), st("C", false, false, 1.1)] };
  assert.equal(
    costSentence(doc),
    "In 2025, 24.1% of BART's weekday trips started or ended at one of these 3 stations. 2 of the 3 carried more weekday riders than in 2024: their riders are coming back. 2 of them are far enough from the next open station to meet the Distance rule; Station B riders would be 13.6 mi from Open B.",
  );
  const near = costSentence({ ...doc, stations: [st("C", false, false, 1.1)] });
  assert.ok(near.endsWith("their riders are coming back."), near);
});

test("API strings are escaped", () => {
  const st = {
    ...FIXTURE.stations[0],
    name: '<img src=x onerror="alert(1)">',
    segment: "<b>Line</b>",
    nearest_open: { code: "X", name: "<script>x</script>", miles: 1 },
    destinations: [{ code: "Y", name: "a & b", share: 0.1 }],
  };
  const html = stationCardHTML(st, FIXTURE) + groupsHTML({ ...FIXTURE, stations: [st] });
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<script>"));
  assert.ok(!html.includes("<b>"));
  assert.ok(html.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"));
  assert.ok(html.includes("a &amp; b"));
});

test("the groups: the first 10 by ridership, the next 5 closing the named segments", () => {
  const html = groupsHTML(FIXTURE);
  assert.ok(html.includes("The first 10: lowest ridership"));
  assert.ok(html.includes("The next 5: line-end segments"));
  assert.ok(html.includes("3 line-end segments"));
  for (const seg of new Set(FIXTURE.stations.map((s) => s.segment).filter(Boolean))) assert.ok(html.includes(seg), seg);
  assert.equal(html.match(/data-closure-station=/g).length, 15);
});
