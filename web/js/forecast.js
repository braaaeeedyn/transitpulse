// Forecast explorer (IMPLEMENTATION_PLAN F5): pick a station (ARIA combobox or a chip) and see its last 28 days
// of entries and the model's 14-day forecast with an 80% range, from GET /api/forecast/{code}.
// The forecast starts the day after the latest published data, so the card says "forecast from data through".

import {
  bandPath,
  dayIndex,
  formatCompact,
  formatDate,
  formatDay,
  formatNumber,
  formatPercent,
  linePath,
  NARROW,
  niceTicks,
  scaleLinear,
  tickCount,
} from "./chart.js";
import { esc, getJSON, hiddenTable, keepDrawn, messageHTML, NotConnected, NotFound } from "./trends.js";

const DEFAULT_STATION = "EMBR";
const MARGIN = { top: 8, right: 8, bottom: 24, left: 48 };

/** Stations matching a query by code, name or short name, best matches first ("mac" → MacArthur). */
export function matchStations(stations, query) {
  const q = query.trim().toLowerCase();
  if (!q) return stations.slice();
  const scored = [];
  for (const s of stations) {
    const code = s.code.toLowerCase();
    const names = [s.short, s.name].map((n) => n.toLowerCase());
    let score = -1;
    if (code === q) score = 0;
    else if (names.some((n) => n.startsWith(q))) score = 1;
    else if (code.startsWith(q)) score = 2;
    else if (names.some((n) => n.split(/[\s/]+/).some((w) => w.startsWith(q)))) score = 3;
    else if (names.some((n) => n.includes(q))) score = 4;
    if (score >= 0) scored.push([score, s]);
  }
  return scored.sort((a, b) => a[0] - b[0] || a[1].short.localeCompare(b[1].short)).map(([, s]) => s);
}

function shortDate(iso) {
  return formatDate(iso).replace(/, \d{4}$/, "");
}

function renderForecastChart(el, data) {
  const w = Math.max(1, Math.round(el.clientWidth));
  const h = Math.max(1, Math.round(el.clientHeight));
  const actual = data.actuals.map((a) => ({ x: dayIndex(a.date), y: a.entries }));
  const last = actual[actual.length - 1];
  const fc = data.forecast.map((f) => ({ x: dayIndex(f.date), y: f.p50, lo: f.p10, hi: f.p90 }));
  // the dashed forecast and its band start from the last actual day, so the two read as one series
  const joined = last ? [{ ...last, lo: last.y, hi: last.y }, ...fc] : fc;
  const xs = [...actual, ...fc].map((p) => p.x);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const yMax = Math.max(...actual.map((p) => p.y), ...fc.map((p) => p.hi));
  const yTicks = niceTicks(0, yMax, tickCount(w));
  const x = scaleLinear([x0, x1], [MARGIN.left, w - MARGIN.right]);
  const y = scaleLinear([0, yTicks[yTicks.length - 1] || 1], [h - MARGIN.bottom, MARGIN.top]);

  const grid = yTicks
    .map(
      (v) => `<line class="chart__grid" x1="${MARGIN.left}" x2="${w - MARGIN.right}" y1="${y(v)}" y2="${y(v)}"/>
      <text class="chart__tick" x="${MARGIN.left - 6}" y="${y(v)}" text-anchor="end" dominant-baseline="middle">${formatCompact(v)}</text>`,
    )
    .join("");
  const every = w < NARROW ? 14 : 7;
  const dates = [...data.actuals.map((a) => a.date), ...data.forecast.map((f) => f.date)];
  const xt = dates
    .filter((_, i) => (dates.length - 1 - i) % every === 0) // count back from the last day so it gets a label
    .map((d) => `<text class="chart__tick" x="${x(dayIndex(d))}" y="${h - 6}" text-anchor="middle">${shortDate(d)}</text>`)
    .join("");
  el.innerHTML = `<svg class="chart__svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img"
      aria-label="${esc(`Daily entries at ${data.name}: the last ${actual.length} days (solid) and the ${fc.length}-day forecast (dashed) with its likely range (shaded).`)}">
      ${grid}<path class="chart__band" d="${bandPath(joined, x, y, { maxStep: 1 })}"/>${xt}
      <path class="chart__line chart__line--actual" d="${linePath(actual, x, y, { maxStep: 1 })}"/>
      <path class="chart__line chart__line--forecast" d="${linePath(joined, x, y, { maxStep: 1 })}"/></svg>`;
}

/** The plain-English line under the title, about a typical day: the first Tuesday in the forecast. */
export function forecastCaption(data) {
  const f = data.forecast.find((d) => new Date(`${d.date}T00:00:00Z`).getUTCDay() === 2) ?? data.forecast[0];
  // "about": hundreds for busy stations, tens for quiet ones
  const round = (v) => {
    const step = v >= 1000 ? 100 : v >= 100 ? 10 : 1;
    return formatNumber(Math.round(v / step) * step);
  };
  return `Expect about ${round(f.p50)} entries on ${formatDay(f.date)}, likely between ${round(f.p10)} and ${round(f.p90)}.`;
}

function sourceLine(data) {
  const m = data.model;
  const through = `Forecast from data through ${formatDate(data.data_through)}.`;
  if (!m) return `${through} Source: BART hourly ridership; TransitPulse forecasting model.`;
  const cover = Number.isFinite(m.interval_coverage)
    ? ` The shaded range is the model's 10th to 90th percentile; in back-testing it held ${formatPercent(m.interval_coverage)} of actual days, so it is narrower than it should be.`
    : " The shaded range is the model's 10th to 90th percentile.";
  return (
    `${through} In back-testing the model was off by ${formatNumber(m.mae)} entries a day on average, ` +
    `against ${formatNumber(m.baseline_mae)} for repeating the same weekday of the latest week.${cover}`
  );
}

function cardHTML() {
  return `<article class="card chart-card forecast-card" aria-labelledby="forecast-chart-title">
    <div class="card__head">
      <h3 id="forecast-chart-title" data-fc-title><span class="skeleton skeleton--title"></span></h3>
      <p class="card__takeaway" data-fc-caption><span class="skeleton skeleton--body"></span></p>
    </div>
    <ul class="legend chart-legend" aria-label="Series">
      <li><svg class="chart-key" viewBox="0 0 24 8" aria-hidden="true"><line class="chart__line chart__line--actual" x1="1" y1="4" x2="23" y2="4"/></svg>Actual entries</li>
      <li><svg class="chart-key" viewBox="0 0 24 8" aria-hidden="true"><line class="chart__line chart__line--forecast" x1="1" y1="4" x2="23" y2="4"/></svg>Forecast</li>
      <li><svg class="chart-key" viewBox="0 0 24 8" aria-hidden="true"><rect class="chart__band" x="1" y="0" width="22" height="8"/></svg>Likely range</li>
    </ul>
    <div class="chart chart--forecast" data-fc-chart><div class="skeleton chart__skeleton"></div></div>
    <div data-fc-table></div>
    <p class="caption chart-card__source" data-fc-source><span class="skeleton skeleton--caption"></span></p>
  </article>`;
}

export async function initForecast(root) {
  if (!root) return;
  const input = root.querySelector("[data-fc-input]");
  const list = root.querySelector("[data-fc-list]");
  const result = root.querySelector("[data-fc-result]");
  let stations = [];
  let matches = [];
  let active = -1;
  let current = null;
  let observer = null;
  let request = 0;

  try {
    const network = await getJSON("data/network.json");
    stations = network.stations.map((s) => ({ code: s.code, name: s.name, short: s.short }));
  } catch (err) {
    console.error(err);
  }
  const byCode = Object.fromEntries(stations.map((s) => [s.code, s]));

  // --- combobox (ARIA 1.2 pattern: focus stays in the input, aria-activedescendant marks the option) ---
  function open(query) {
    matches = matchStations(stations, query);
    active = -1;
    list.innerHTML = matches.length
      ? matches
          .map(
            (s, i) =>
              `<li role="option" id="fc-opt-${i}" class="combobox__option" data-code="${esc(s.code)}" aria-selected="false">${esc(s.short)} <span class="combobox__code">${esc(s.code)}</span></li>`,
          )
          .join("")
      : `<li class="combobox__empty" role="presentation">No station matches “${esc(query)}”.</li>`;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    input.removeAttribute("aria-activedescendant");
  }

  function close() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }

  function highlight(i) {
    const opts = [...list.querySelectorAll("[role=option]")];
    if (!opts.length) return;
    active = (i + opts.length) % opts.length;
    opts.forEach((o, j) => o.setAttribute("aria-selected", String(j === active)));
    input.setAttribute("aria-activedescendant", opts[active].id);
    opts[active].scrollIntoView({ block: "nearest" });
  }

  function choose(code) {
    const s = byCode[code];
    if (!s) return;
    input.value = s.short;
    close();
    load(code);
  }

  input.addEventListener("input", () => open(input.value));
  input.addEventListener("focus", () => {
    if (input.value.trim() && current && input.value === byCode[current]?.short) return;
    if (input.value.trim()) open(input.value);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (list.hidden) open(input.value);
      highlight(active < 0 ? (e.key === "ArrowDown" ? 0 : -1) : active + (e.key === "ArrowDown" ? 1 : -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (!list.hidden && active >= 0) choose(matches[active].code);
      else if (input.value.trim()) {
        const best = matchStations(stations, input.value)[0];
        if (best) choose(best.code);
      }
    } else if (e.key === "Escape") {
      if (!list.hidden) {
        e.preventDefault();
        close();
      } else {
        input.value = "";
      }
    }
  });
  input.addEventListener("blur", () => setTimeout(close, 120)); // after a click on an option has landed
  list.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus in the input
  list.addEventListener("click", (e) => {
    const opt = e.target.closest("[role=option]");
    if (opt) choose(opt.dataset.code);
  });

  root.querySelectorAll("[data-fc-chip]").forEach((chip) =>
    chip.addEventListener("click", () => {
      input.value = byCode[chip.dataset.fcChip]?.short ?? "";
      close();
      load(chip.dataset.fcChip);
    }),
  );

  // --- result card -------------------------------------------------------------------------------
  async function load(code) {
    const mine = ++request;
    current = code;
    observer?.disconnect();
    result.innerHTML = cardHTML();
    result.setAttribute("aria-busy", "true");
    root.querySelectorAll("[data-fc-chip]").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.fcChip === code)));
    try {
      const data = await getJSON(`api/forecast/${encodeURIComponent(code)}`);
      if (mine !== request) return;
      if (!data.forecast?.length) throw new NotFound("forecast_not_available");
      render(data);
    } catch (err) {
      if (mine !== request) return;
      if (err instanceof NotConnected) {
        root.innerHTML = messageHTML("Forecasts will appear here once the forecasting model has run.");
        return;
      }
      const name = byCode[code]?.short ?? code;
      if (err instanceof NotFound) {
        result.innerHTML = messageHTML(`There's no forecast for ${name} yet.`, { action: "Try another station" });
        result.querySelector("[data-action]").addEventListener("click", () => {
          input.value = "";
          input.focus();
          open("");
        });
      } else {
        console.error(err);
        result.innerHTML = messageHTML(`The forecast for ${name} didn't load. Check your connection and try again.`, {
          error: true,
          action: "Retry",
        });
        result.querySelector("[data-action]").addEventListener("click", () => load(code));
      }
    } finally {
      if (mine === request) result.setAttribute("aria-busy", "false");
    }
  }

  function render(data) {
    result.querySelector("[data-fc-title]").textContent = data.name;
    result.querySelector("[data-fc-caption]").textContent = forecastCaption(data);
    result.querySelector("[data-fc-source]").textContent = sourceLine(data);
    result.querySelector("[data-fc-table]").innerHTML = hiddenTable(
      `Forecast daily entries at ${data.name}`,
      ["Day", "Expected entries", "Likely low", "Likely high"],
      data.forecast.map((f) => [formatDay(f.date), formatNumber(f.p50), formatNumber(f.p10), formatNumber(f.p90)]),
    );
    const chart = result.querySelector("[data-fc-chart]");
    observer = keepDrawn(chart, () => renderForecastChart(chart, data));
  }

  load(DEFAULT_STATION);
}
