// Pure chart and number helpers (no DOM), shared by the Trends and Forecast charts and unit-tested with node:test.
// DESIGN.md §7 chart card: horizontal gridlines only, caption-size axes, fewer ticks below 600 px card width.

const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export const NARROW = 600;

/** Linear scale from a [d0, d1] domain to a [r0, r1] range. */
export function scaleLinear([d0, d1], [r0, r1]) {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  return (v) => r0 + (v - d0) * k;
}

/** How many y-axis ticks to aim for at a given card width. */
export function tickCount(width) {
  return width < NARROW ? 3 : 5;
}

/** "Nice" round tick values (1, 2, 5 × 10^n steps) covering [min, max], about `count` of them. */
export function niceTicks(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (max < min) [min, max] = [max, min];
  if (max === min) {
    if (max === 0) return [0];
    min = Math.min(0, min);
    max = Math.max(0, max);
  }
  const raw = (max - min) / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

/** Month number since year 0 for an ISO date string ("2025-03-01" → 2025 × 12 + 2), for even month spacing. */
export function monthIndex(iso) {
  const [y, m] = iso.split("-").map(Number);
  return y * 12 + (m - 1);
}

/** Day number (UTC) for an ISO date, for even day spacing. */
export function dayIndex(iso) {
  return Math.round(Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / 86_400_000);
}

/**
 * SVG path through points [{x, y}] (x in data units, sorted). The line breaks instead of bridging a gap:
 * a missing value (y null) or a jump in x larger than `maxStep` starts a new segment. Single-point segments
 * get a tiny horizontal stroke so they stay visible with round caps.
 */
export function linePath(points, xScale, yScale, { maxStep = 1 } = {}) {
  const parts = [];
  let seg = [];
  let prevX = null;
  const flush = () => {
    if (seg.length === 1) parts.push(`M${seg[0][0]},${seg[0][1]}h0.01`);
    else if (seg.length > 1) parts.push(`M${seg.map((p) => p.join(",")).join("L")}`);
    seg = [];
  };
  for (const p of points) {
    if (p.y === null || p.y === undefined || !Number.isFinite(p.y)) {
      flush();
      prevX = null;
      continue;
    }
    if (prevX !== null && p.x - prevX > maxStep) flush();
    seg.push([round(xScale(p.x)), round(yScale(p.y))]);
    prevX = p.x;
  }
  flush();
  return parts.join("");
}

/** Closed SVG area between two lines (e.g. a forecast's p10–p90 band); breaks like linePath. */
export function bandPath(points, xScale, yScale, { maxStep = 1 } = {}) {
  const segs = [];
  let seg = [];
  let prevX = null;
  for (const p of points) {
    const ok = Number.isFinite(p.lo) && Number.isFinite(p.hi);
    if (!ok || (prevX !== null && p.x - prevX > maxStep)) {
      if (seg.length) segs.push(seg);
      seg = [];
    }
    if (ok) seg.push(p);
    prevX = ok ? p.x : null;
  }
  if (seg.length) segs.push(seg);
  return segs
    .map((s) => {
      const top = s.map((p) => `${round(xScale(p.x))},${round(yScale(p.hi))}`);
      const bottom = s.map((p) => `${round(xScale(p.x))},${round(yScale(p.lo))}`).reverse();
      return `M${top.join("L")}L${bottom.join("L")}Z`;
    })
    .join("");
}

/** Year ticks (January of each year) between two month indexes; every other year on narrow cards. */
export function yearTicks(minMonth, maxMonth, width) {
  const first = Math.ceil(minMonth / 12);
  const last = Math.floor(maxMonth / 12);
  const years = [];
  for (let y = first; y <= last; y++) years.push(y);
  const every = width < NARROW && years.length > 4 ? 2 : 1;
  return years.filter((_, i) => i % every === 0).map((y) => ({ value: y * 12, label: String(y) }));
}

function round(v) {
  return Math.round(v * 10) / 10;
}

// --- formatting ----------------------------------------------------------------------------------

/** 149335.2 → "149,335" */
export function formatNumber(n) {
  return n === null || n === undefined || !Number.isFinite(n) ? "—" : nf0.format(n);
}

/** Axis labels: 150000 → "150K", 1200000 → "1.2M", 950 → "950". */
export function formatCompact(n) {
  const a = Math.abs(n);
  if (a >= 1e6) return `${trim(n / 1e6)}M`;
  if (a >= 1e3) return `${trim(n / 1e3)}K`;
  return trim(n);
}

function trim(v) {
  return String(Number(v.toFixed(1)));
}

/** A ratio as a percentage: 0.4312 → "43%", with `digits` decimals: (0.1071, 1) → "10.7%". */
export function formatPercent(ratio, digits = 0) {
  return ratio === null || ratio === undefined || !Number.isFinite(ratio) ? "—" : `${(ratio * 100).toFixed(digits)}%`;
}

/**
 * A change with an ink arrow (DESIGN.md: ▲/▼, never green/red). For a percent-valued tile the delta is a
 * difference of ratios and is shown in points; otherwise it is a relative change shown in percent.
 */
export function formatDelta(delta, unit) {
  if (delta === null || delta === undefined || !Number.isFinite(delta)) return "";
  const v = delta * 100;
  const shown = Math.abs(v).toFixed(1);
  const arrow = Number(shown) === 0 ? "" : v > 0 ? "▲ " : "▼ ";
  return unit === "percent" ? `${arrow}${shown} pts` : `${arrow}${shown}%`;
}

/** "2025-12-31" → "Dec 31, 2025" (dates are calendar dates, so no time zone shifts). */
export function formatDate(iso) {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** "2026-01-06" → "Tue, Jan 6" */
export function formatDay(iso) {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${DAYS[wd]}, ${MONTHS[m - 1]} ${d}`;
}

/** "2025-12-01" → "Dec 2025" */
export function formatMonth(iso) {
  const [y, m] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}
