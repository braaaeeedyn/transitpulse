// Findings ink band (IMPLEMENTATION_PLAN M4): the eBART causal study, read from GET /api/findings.
// Shown from the JSON: the verdict sentence (one per pre-registered verdict code), the corridor and legacy effects
// with their 95% placebo intervals, a caution sentence when the pre-registered caution flag is set, the method line,
// and two small event-study charts (legacy, corridor) with placebo bands and a hidden table each. A fixed hedge note
// follows the figures when the verdict is "new".
// States: skeletons while loading, "The analysis is in progress." on 404, an error message with Retry otherwise.

import { formatDate, formatNumber, linePath, bandPath, niceTicks, scaleLinear, tickCount } from "./chart.js";
import { esc, getJSON, hiddenTable, keepDrawn, messageHTML, NotFound } from "./trends.js";

export const WRITE_UP_URL = "https://github.com/braaaeeedyn/transitpulse/blob/main/docs/FINDINGS.md";
const MINUS = "−"; // typographic minus sign

export const TITLES = {
  corridor: "Whole line, Concord → Antioch (incl. new stations)",
  legacy: "Pittsburg/Bay Point, North Concord, Concord",
};

// Hedged on purpose (final review, Revision 1): each sentence says what the data are consistent with, never that
// eBART caused it. One sentence per pre-registered verdict code.
const VERDICTS = {
  new: "The whole line from Concord to Antioch carried a few percent more riders than the comparison stations would predict: consistent with eBART bringing a modest number of new riders, on top of the many it moved from the old stations to the new ones.",
  moved:
    "The data are consistent with eBART mostly moving riders: the old stations lost riders to the new ones, and the line as a whole showed no clear growth.",
  fewer:
    "The whole line from Concord to Antioch carried fewer riders after the opening than the comparison stations would predict.",
  inconclusive: "The data can't tell whether eBART added new riders or only moved them between stations.",
};

// Fixed copy tied to the "new" code, shown under the figures. It describes the one final run (the fade after the
// first months and the monthly pre-opening drift in docs/FINDINGS.md); that run is final, so the note is not derived
// from the JSON. Separate from the pre-registered caution sentence.
export const VERDICTS_HEDGE_NOTE =
  "A small effect from one line: it is largest in the first months, and the longer monthly data show the line already rising against the comparison stations before the opening, so part of it may be that trend. See the write-up.";

/** Log points → percent change, 100 × (e^b − 1). */
export function logToPct(b) {
  return 100 * Math.expm1(b);
}

/** 4.235 → "+4.2%", −23.889 → "−23.9%" (a true minus sign); 0 → "0.0%". */
export function formatSignedPct(pct, digits = 1) {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "—";
  const shown = Math.abs(pct).toFixed(digits);
  if (Number(shown) === 0) return `${shown}%`;
  return `${pct > 0 ? "+" : MINUS}${shown}%`;
}

/** [1.62, 7.11] → "+1.6% to +7.1%" */
export function formatInterval([lo, hi], digits = 1) {
  return `${formatSignedPct(lo, digits)} to ${formatSignedPct(hi, digits)}`;
}

/** The sentence for a pre-registered verdict code. */
export function verdictSentence(code) {
  const s = VERDICTS[code];
  if (!s) throw new Error(`unknown verdict ${code}`);
  return s;
}

/** The caution sentence, or "" when the pre-registered caution flag is off. */
export function cautionSentence(caution) {
  return caution
    ? "Read this with care: the trends before the opening, or the longer monthly data, don't fully back it up."
    : "";
}

/** Corridor entries a day attributable to eBART, rounded to tens: "about 500 more entries a day (200 to 820)". */
export function dailyEntriesText(imp) {
  if (!imp || !Number.isFinite(imp.point)) return "";
  const r = (v) => formatNumber(Math.round(Math.abs(v) / 10) * 10);
  const more = imp.point >= 0 ? "more" : "fewer";
  const signed = (v) => (v < 0 ? `${MINUS}${r(v)}` : r(v));
  return `about ${r(imp.point)} ${more} entries a day (${signed(imp.lo)} to ${signed(imp.hi)})`;
}

/** The method line, with the control count and the pre-registration date from the data. */
export function methodLine(doc) {
  const n = doc.design?.controls?.length ?? 0;
  const on = formatDate(doc.preregistration.fixed_on);
  return `Difference-in-differences against ${n} BART stations far from the line, pre-registered on ${on}. 95% intervals from placebo tests.`;
}

/** "−5 to −2", "0 to 3" weeks since opening */
export function binLabel(row) {
  const f = (v) => (v < 0 ? `${MINUS}${Math.abs(v)}` : String(v));
  return `${f(row.bin_start)} to ${f(row.bin_end)}`;
}

// --- rendering -------------------------------------------------------------------------------------

function figureHTML(key, est, extra = "") {
  return `<div class="findings__figure" data-findings-figure="${key}">
    <p class="findings__figure-label">${esc(TITLES[key])}</p>
    <p class="findings__figure-value">${esc(formatSignedPct(est.pct))}</p>
    <p class="findings__figure-detail">95% interval ${esc(formatInterval(est.placebo_ci_pct))}${extra ? `, ${esc(extra)}` : ""}</p>
  </div>`;
}

function chartCardHTML(key) {
  return `<article class="card findings-chart" aria-labelledby="findings-chart-${key}" data-findings-chart="${key}">
    <h3 class="findings-chart__title" id="findings-chart-${key}">${esc(TITLES[key])}</h3>
    <div class="chart findings-chart__plot" data-plot></div>
    <div data-table></div>
  </article>`;
}

const MARGIN = { top: 8, right: 8, bottom: 36, left: 48 };

/** One event-study panel: placebo band, zero line, opening marker, 2 px ink line with a dot per bin, in %. */
export function renderEventStudy(el, rows, title) {
  const w = Math.max(1, Math.round(el.clientWidth));
  const h = Math.max(1, Math.round(el.clientHeight));
  const pts = rows.map((r) => ({
    x: (r.bin_start + r.bin_end) / 2,
    y: logToPct(r.coef),
    lo: logToPct(r.lo),
    hi: logToPct(r.hi),
  }));
  const x0 = Math.min(rows[0].bin_start, 0);
  const x1 = Math.max(rows[rows.length - 1].bin_end, 1);
  const ys = pts.flatMap((p) => [p.lo, p.hi, p.y, 0]);
  const yTicks = niceTicks(Math.min(...ys), Math.max(...ys), tickCount(w));
  const x = scaleLinear([x0, x1], [MARGIN.left, w - MARGIN.right]);
  const y = scaleLinear([yTicks[0], yTicks[yTicks.length - 1]], [h - MARGIN.bottom, MARGIN.top]);
  const step = Math.max(...pts.slice(1).map((p, i) => p.x - pts[i].x)) + 0.01;

  const grid = yTicks
    .map(
      (v) => `<line class="chart__grid${v === 0 ? " findings-chart__zero" : ""}" x1="${MARGIN.left}" x2="${w - MARGIN.right}" y1="${y(v)}" y2="${y(v)}"/>
      <text class="chart__tick" x="${MARGIN.left - 6}" y="${y(v)}" text-anchor="end" dominant-baseline="middle">${esc(formatSignedPct(v, 0))}</text>`,
    )
    .join("");
  const xTicks = niceTicks(x0, x1, w < 360 ? 3 : 5)
    .filter((v) => v >= x0 && v <= x1)
    .map((v) => `<text class="chart__tick" x="${x(v)}" y="${h - 20}" text-anchor="middle">${v < 0 ? MINUS + Math.abs(v) : v}</text>`)
    .join("");
  const ex = x(-0.5);
  const event = `<line class="findings-chart__event" x1="${ex}" x2="${ex}" y1="${MARGIN.top}" y2="${h - MARGIN.bottom}"/>
    <text class="chart__tick findings-chart__event-label" x="${ex + 4}" y="${MARGIN.top + 10}">Opening</text>`;
  const band = `<path class="chart__band" d="${bandPath(pts, x, y, { maxStep: step })}"/>`;
  const line = `<path class="chart__line" d="${linePath(pts, x, y, { maxStep: step })}"/>`;
  const dots = pts
    .map((p) => `<circle class="findings-chart__point" cx="${x(p.x)}" cy="${y(p.y)}" r="2.5"/>`)
    .join("");
  const axis = `<text class="chart__tick" x="${(MARGIN.left + w - MARGIN.right) / 2}" y="${h - 2}" text-anchor="middle">weeks since opening</text>`;
  el.innerHTML = `<svg class="findings-chart__svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img"
      aria-label="${esc(`Event study, ${title}: change against the control stations in 4-week bins, with 95% placebo bands.`)}">${band}${grid}${event}${line}${dots}${xTicks}${axis}</svg>`;
}

export function initFindings(root) {
  if (!root) return;
  const skeleton = root.innerHTML;
  let observers = [];

  const forget = () => {
    for (const o of observers) o.disconnect();
    observers = [];
  };

  async function load() {
    root.setAttribute("aria-busy", "true");
    try {
      render(await getJSON("api/findings"));
    } catch (err) {
      forget();
      if (err instanceof NotFound) {
        root.innerHTML = messageHTML("The analysis is in progress.");
      } else {
        console.error(err);
        root.innerHTML = messageHTML("The findings didn't load. Check your connection and try again.", {
          error: true,
          action: "Retry",
        });
        root.querySelector("[data-action]").addEventListener("click", () => {
          root.innerHTML = skeleton;
          load();
        });
      }
    } finally {
      root.setAttribute("aria-busy", "false");
    }
  }

  function render(doc) {
    forget();
    const est = doc.estimates;
    const caution = cautionSentence(doc.caution);
    root.innerHTML = `<p class="findings__verdict" data-findings-verdict>${esc(verdictSentence(doc.verdict))}</p>
      <div class="findings__figures">
        ${figureHTML("corridor", est.corridor, dailyEntriesText(est.corridor.implied_daily_entries))}
        ${figureHTML("legacy", est.legacy)}
      </div>
      ${doc.verdict === "new" ? `<p class="findings__note" data-findings-note>${esc(VERDICTS_HEDGE_NOTE)}</p>` : ""}
      ${caution ? `<p class="findings__caution" data-findings-caution>${esc(caution)}</p>` : ""}
      <div class="findings__charts">${chartCardHTML("legacy")}${chartCardHTML("corridor")}</div>
      <p class="caption findings__method" data-findings-method>${esc(methodLine(doc))}
        <a href="${WRITE_UP_URL}">Read the write-up</a></p>`;
    for (const key of ["legacy", "corridor"]) {
      const rows = doc.event_study.series[key];
      const card = root.querySelector(`[data-findings-chart="${key}"]`);
      card.querySelector("[data-table]").innerHTML = hiddenTable(
        `${TITLES[key]}: change against the control stations by weeks since opening`,
        ["Weeks since opening", "Change", "95% placebo band"],
        rows.map((r) => [binLabel(r), formatSignedPct(logToPct(r.coef)), formatInterval([logToPct(r.lo), logToPct(r.hi)])]),
      );
      const plot = card.querySelector("[data-plot]");
      observers.push(keepDrawn(plot, () => renderEventStudy(plot, rows, TITLES[key])));
    }
  }

  load();
}
