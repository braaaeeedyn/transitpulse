// The Findings band's wording (web/js/findings.js): node --test tests/web/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  binLabel,
  cautionSentence,
  dailyEntriesText,
  formatInterval,
  formatSignedPct,
  logToPct,
  methodLine,
  verdictSentence,
  VERDICTS_HEDGE_NOTE,
} from "../../web/js/findings.js";

const FIXTURE = JSON.parse(readFileSync(new URL("./fixtures/api/findings.json", import.meta.url)));
const MINUS = "−";

test("signed percentages use a true minus sign and an explicit plus", () => {
  assert.equal(formatSignedPct(4.235082), "+4.2%");
  assert.equal(formatSignedPct(-23.889341), `${MINUS}23.9%`);
  assert.ok(!formatSignedPct(-23.889341).includes("-"), "no hyphen-minus");
  assert.equal(formatSignedPct(0), "0.0%");
  assert.equal(formatSignedPct(-0.04), "0.0%"); // rounds to zero: no sign
  assert.equal(formatSignedPct(12.3456, 0), "+12%");
  assert.equal(formatSignedPct(null), "—");
  assert.equal(formatSignedPct(Number.NaN), "—");
});

test("intervals read low to high", () => {
  assert.equal(formatInterval([1.623917, 7.107388]), "+1.6% to +7.1%");
  assert.equal(formatInterval([-25.764536, -21.785222]), `${MINUS}25.8% to ${MINUS}21.8%`);
  assert.equal(formatInterval([-3, 4]), `${MINUS}3.0% to +4.0%`);
});

test("log points convert to percent", () => {
  assert.ok(Math.abs(logToPct(Math.log(1.15)) - 15) < 1e-9);
  assert.equal(logToPct(0), 0);
});

test("every verdict code has its own sentence", () => {
  const codes = ["new", "moved", "fewer", "inconclusive"];
  const sentences = codes.map(verdictSentence);
  assert.equal(new Set(sentences).size, codes.length);
  assert.match(verdictSentence("new"), /modest number of new riders/);
  assert.match(verdictSentence("moved"), /mostly moving riders/);
  assert.match(verdictSentence("fewer"), /fewer riders/);
  assert.match(verdictSentence("inconclusive"), /can't tell/);
  assert.throws(() => verdictSentence("maybe"));
});

test("verdict sentences are hedged", () => {
  const codes = ["new", "moved", "fewer", "inconclusive"];
  assert.match(verdictSentence("new"), /consistent with/);
  for (const code of codes) assert.doesNotMatch(verdictSentence(code), /eBART brought|caused/i);
  assert.match(VERDICTS_HEDGE_NOTE, /before the opening/);
  assert.doesNotMatch(VERDICTS_HEDGE_NOTE, /eBART brought|caused/i);
});

test("caution on and off", () => {
  assert.match(cautionSentence(true), /with care/);
  assert.equal(cautionSentence(false), "");
});

test("implied daily entries round to tens and carry their sign", () => {
  assert.equal(dailyEntriesText({ point: 504.7, lo: 198.5, hi: 824.3 }), "about 500 more entries a day (200 to 820)");
  assert.equal(
    dailyEntriesText({ point: -1234.5, lo: -2000, hi: 15 }),
    `about 1,230 fewer entries a day (${MINUS}2,000 to 20)`,
  );
  assert.equal(dailyEntriesText(undefined), "");
});

test("the method line takes its numbers from the data", () => {
  assert.equal(
    methodLine(FIXTURE),
    "Difference-in-differences against 34 BART stations far from the line, pre-registered on Oct 9, 2026. 95% intervals from placebo tests.",
  );
  const fewer = structuredClone(FIXTURE);
  fewer.design.controls = fewer.design.controls.slice(0, 16);
  assert.match(methodLine(fewer), /against 16 BART stations/);
});

test("event-study bin labels", () => {
  assert.equal(binLabel({ bin_start: -5, bin_end: -2 }), `${MINUS}5 to ${MINUS}2`);
  assert.equal(binLabel({ bin_start: 0, bin_end: 3 }), "0 to 3");
});
