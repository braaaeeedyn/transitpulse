// Trends band (IMPLEMENTATION_PLAN F4, M1 Bay Wheels): KPI tiles, the monthly ridership chart and the bikes vs
// trains chart, read from GET /api/kpis, /api/trends/ridership and /api/trends/bikes-vs-trains.
// States: skeletons of the final size while loading (no layout shift), the honest "not connected" message on 503,
// an error message with Retry, and one-sentence empty states. Bike data is optional: without it the BART tiles and
// chart still show, and the bikes card says why it's empty.

import {
  formatCompact,
  formatDate,
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
} from "./chart.js";
import { apiUrl } from "./util/api.js";

export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Thrown for a 503: the site isn't connected to the warehouse. */
export class NotConnected extends Error {}

/** Thrown for a 404 with a machine-readable code (e.g. forecast_not_available). */
export class NotFound extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

export async function getJSON(url) {
  const res = await fetch(url.startsWith("api/") ? apiUrl(url) : url, { headers: { Accept: "application/json" } });
  if (res.status === 503) throw new NotConnected(url);
  if (res.status === 404) {
    const body = await res.json().catch(() => ({}));
    throw new NotFound(body?.detail?.code ?? "not_found");
  }
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

export function messageHTML(text, { error = false, action = "" } = {}) {
  const icon = error ? "i-circle-alert" : "i-info";
  const button = action ? `<button class="btn btn--subtle" type="button" data-action>${esc(action)}</button>` : "";
  return `<div class="message${error ? " message--error" : ""}" role="${error ? "alert" : "status"}">
    <p class="message__text"><svg class="icon" aria-hidden="true"><use href="#${icon}"/></svg>${esc(text)}</p>${button}</div>`;
}

// --- KPI tiles -----------------------------------------------------------------------------------

function tileValue(t) {
  if (t.unit === "percent") return formatPercent(t.value, t.id === "recovery" ? 0 : 1);
  if (t.unit === "entries") return formatNumber(t.value);
  return t.value ?? "—";
}

function tileHTML(t) {
  const id = `kpi-def-${t.id}`;
  const delta = t.delta === null || t.delta === undefined ? "" : formatDelta(t.delta, t.unit);
  const deltaText = [delta, t.delta_label].filter(Boolean).join(" ");
  const textValue = t.unit === null || t.unit === undefined;
  return `<div class="stat-tile" data-tile="${esc(t.id)}">
    <p class="stat-tile__label">${esc(t.label)}</p>
    <button class="stat-tile__info" type="button" aria-expanded="false" aria-controls="${id}" aria-label="What does “${esc(t.label)}” mean?">
      <svg class="icon" aria-hidden="true"><use href="#i-info"/></svg></button>
    <p class="stat-tile__value${textValue ? " stat-tile__value--text" : ""}">${esc(tileValue(t))}</p>
    <p class="stat-tile__delta">${esc(deltaText)}</p>
    <p class="stat-tile__def" id="${id}" hidden>${esc(t.definition)}</p>
  </div>`;
}

// --- line charts ---------------------------------------------------------------------------------

const MARGIN = { top: 8, right: 8, bottom: 24, left: 44 };

/**
 * Draws monthly line series into `el` at its current pixel size (the SVG viewBox matches it, so text stays 12 px).
 * series: [{ cls, points: [{ x: monthIndex, y }] }]. Missing months break each line instead of bridging them.
 */
export function renderLineChart(el, { series, label, yFormat = formatCompact }) {
  const w = Math.max(1, Math.round(el.clientWidth));
  const h = Math.max(1, Math.round(el.clientHeight));
  const all = series.flatMap((s) => s.points);
  const xs = all.map((p) => p.x);
  const x0 = Math.min(...xs);
  const x1 = Math.max(Math.max(...xs), x0 + 1);
  const yTicks = niceTicks(0, Math.max(...all.map((p) => p.y ?? 0)), tickCount(w));
  const x = scaleLinear([x0, x1], [MARGIN.left, w - MARGIN.right]);
  const y = scaleLinear([0, yTicks[yTicks.length - 1] || 1], [h - MARGIN.bottom, MARGIN.top]);

  const grid = yTicks
    .map(
      (v) => `<line class="chart__grid" x1="${MARGIN.left}" x2="${w - MARGIN.right}" y1="${y(v)}" y2="${y(v)}"/>
      <text class="chart__tick" x="${MARGIN.left - 6}" y="${y(v)}" text-anchor="end" dominant-baseline="middle">${yFormat(v)}</text>`,
    )
    .join("");
  const xt = yearTicks(x0, x1, w)
    .map((t) => `<text class="chart__tick" x="${x(t.value)}" y="${h - 6}" text-anchor="middle">${t.label}</text>`)
    .join("");
  const lines = series
    .map((s) => `<path class="chart__line ${s.cls ?? ""}" d="${linePath(s.points, x, y, { maxStep: 1 })}"/>`)
    .join("");
  const gaps = series.some((s) => s.points.some((p, i) => i > 0 && p.x - s.points[i - 1].x > 1));
  el.innerHTML = `<svg class="chart__svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img"
      aria-label="${esc(label)}${gaps ? " Gaps are months with no data loaded." : ""}">${grid}${xt}${lines}</svg>`;
}

/** Draws a chart now and again whenever its container changes width. Returns the observer. */
export function keepDrawn(el, draw) {
  draw();
  let lastW = el.clientWidth;
  const ro = new ResizeObserver(() => {
    if (el.clientWidth === lastW) return;
    lastW = el.clientWidth;
    draw();
  });
  ro.observe(el);
  return ro;
}

/** A visually hidden table with the chart's numbers, for screen readers. */
export function hiddenTable(caption, head, rows) {
  const body = rows
    .map((r) => `<tr><th scope="row">${esc(r[0])}</th>${r.slice(1).map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="visually-hidden"><table><caption>${esc(caption)}</caption>
    <thead><tr>${head.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
}

// ridership since 2019

function ridershipChart(el, rows) {
  const first = formatMonth(rows[0].month_start);
  const last = formatMonth(rows[rows.length - 1].month_start);
  renderLineChart(el, {
    series: [{ points: rows.map((r) => ({ x: monthIndex(r.month_start), y: r.avg_daily_entries })) }],
    label: `Line chart of average daily BART entries by month, ${first} to ${last}.`,
  });
}

function ridershipTakeaway(rows) {
  const r = rows[rows.length - 1];
  const rec = r.avg_service_weekday_recovery;
  const recText = rec === null || rec === undefined ? "" : `, ${formatPercent(rec)} of 2019 on weekdays`;
  return `In ${formatMonth(r.month_start)}, BART averaged ${formatNumber(r.avg_daily_entries)} entries a day${recText}.`;
}

// bikes and trains: each as a percentage of the same month in 2019

const pct = (v) => `${Math.round(v)}%`;

function bikesChart(el, rows) {
  const pts = (key) =>
    rows.filter((r) => r[key] !== null && r[key] !== undefined).map((r) => ({ x: monthIndex(r.month_start), y: r[key] }));
  renderLineChart(el, {
    series: [
      { cls: "chart__line--primary", points: pts("bart_index_2019") },
      { cls: "chart__line--secondary", points: pts("bike_index_2019") },
    ],
    yFormat: pct,
    label:
      "Line chart of BART entries (solid) and Bay Wheels trips (dashed) per day, each as a percentage of the same " +
      `month in 2019, ${formatMonth(rows[0].month_start)} to ${formatMonth(rows[rows.length - 1].month_start)}.`,
  });
}

function bikesTakeaway(rows) {
  const both = rows.filter((r) => r.bart_index_2019 !== null && r.bike_index_2019 !== null);
  if (!both.length) return "Bay Wheels trips and BART entries per day, compared with 2019.";
  const r = both[both.length - 1];
  const month = formatMonth(r.month_start);
  const base = `${month.slice(0, 3)} 2019`;
  return `In ${month}, Bay Wheels trips were at ${pct(r.bike_index_2019)} of ${base} and BART entries at ${pct(r.bart_index_2019)}.`;
}

// --- controller ----------------------------------------------------------------------------------

export function initTrends(root) {
  if (!root) return;
  const skeleton = root.innerHTML; // the loading state, kept so Retry can show it again
  const bikesSkeleton = root.querySelector("[data-bikes-card]")?.outerHTML ?? "";
  let observers = [];

  const forget = () => {
    for (const o of observers) o.disconnect();
    observers = [];
  };

  const loadBikes = () =>
    getJSON("api/trends/bikes-vs-trains").then(
      (data) => ({ data }),
      (error) => ({ error }),
    );

  async function load() {
    root.setAttribute("aria-busy", "true");
    const bikes = loadBikes(); // in parallel; the BART parts don't wait for it or fail with it
    try {
      const [kpis, trend] = await Promise.all([getJSON("api/kpis"), getJSON("api/trends/ridership")]);
      if (!kpis.tiles?.length || !trend.rows?.length) {
        forget();
        root.innerHTML = messageHTML("No ridership data has been loaded into the warehouse yet.");
        return;
      }
      render(kpis, trend);
      renderBikes(await bikes);
    } catch (err) {
      forget();
      if (err instanceof NotConnected) {
        root.innerHTML = messageHTML("Ridership numbers will appear here once the data pipeline is connected.");
      } else {
        console.error(err);
        root.innerHTML = messageHTML("Ridership numbers didn't load. Check your connection and try again.", {
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

  function render(kpis, trend) {
    forget();
    const through = kpis.data_through ?? trend.data_through;
    root.querySelector("[data-trends-through]").textContent =
      `Data through ${formatDate(through)}. Tiles cover the ${kpis.window?.days ?? 28} days to that date.`;
    root.querySelector("[data-kpi-tiles]").innerHTML = kpis.tiles.map(tileHTML).join("");
    root.querySelector("[data-kpi-source]").textContent = `Source: ${kpis.source}`;

    const rows = trend.rows;
    root.querySelector("[data-chart-title]").textContent = `Ridership since ${rows[0].month_start.slice(0, 4)}`;
    root.querySelector("[data-takeaway]").textContent = ridershipTakeaway(rows);
    root.querySelector("[data-chart-table]").innerHTML = hiddenTable(
      "Average daily entries by month",
      ["Month", "Average daily entries", "Weekday recovery vs 2019"],
      rows.map((r) => [
        formatMonth(r.month_start),
        formatNumber(r.avg_daily_entries),
        formatPercent(r.avg_service_weekday_recovery),
      ]),
    );
    const chart = root.querySelector("[data-chart]");
    observers.push(keepDrawn(chart, () => ridershipChart(chart, rows)));
  }

  function renderBikes({ data, error }) {
    const card = root.querySelector("[data-bikes-card]");
    if (!card) return;
    const rows = data?.rows ?? [];
    if (error || !rows.some((r) => r.bike_trips !== null && r.bike_trips !== undefined)) {
      const retryable = Boolean(error) && !(error instanceof NotFound) && !(error instanceof NotConnected);
      if (retryable) console.error(error);
      const box = document.createElement("div");
      box.dataset.bikesCard = "";
      box.innerHTML = retryable
        ? messageHTML("The bikes and trains comparison didn't load. Check your connection and try again.", {
            error: true,
            action: "Retry",
          })
        : messageHTML("Bay Wheels numbers will appear here once bike trip data is loaded.");
      card.replaceWith(box);
      box.querySelector("[data-action]")?.addEventListener("click", async () => {
        box.outerHTML = bikesSkeleton;
        renderBikes(await loadBikes());
      });
      return;
    }
    card.querySelector("[data-bikes-takeaway]").textContent = bikesTakeaway(rows);
    card.querySelector("[data-bikes-table]").innerHTML = hiddenTable(
      "BART entries and Bay Wheels trips per day, as a percentage of the same month in 2019",
      ["Month", "BART", "Bay Wheels"],
      rows.map((r) => [
        formatMonth(r.month_start),
        r.bart_index_2019 === null ? "—" : pct(r.bart_index_2019),
        r.bike_index_2019 === null ? "—" : pct(r.bike_index_2019),
      ]),
    );
    const chart = card.querySelector("[data-bikes-chart]");
    observers.push(keepDrawn(chart, () => bikesChart(chart, rows)));
  }

  // ⓘ toggles a tile's definition
  root.addEventListener("click", (e) => {
    const btn = e.target.closest(".stat-tile__info");
    if (!btn) return;
    const def = document.getElementById(btn.getAttribute("aria-controls"));
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    def.hidden = !open;
  });

  load();
}
