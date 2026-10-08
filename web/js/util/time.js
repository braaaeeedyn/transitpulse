// Pacific-time helpers. BART runs on America/Los_Angeles time regardless of where the visitor is.

export const TZ = "America/Los_Angeles";

const partsFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  weekday: "short",
});

const WEEKDAYS = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };

/** Wall-clock parts of an instant in Pacific time. weekday: 0 = Monday … 6 = Sunday (GTFS order). */
export function pacificParts(date = new Date()) {
  const p = Object.fromEntries(partsFmt.formatToParts(date).map((x) => [x.type, x.value]));
  return {
    ymd: `${p.year}${p.month}${p.day}`,
    weekday: WEEKDAYS[p.weekday],
    minutes: Number(p.hour) * 60 + Number(p.minute) + Number(p.second) / 60,
  };
}

/** The calendar date (YYYYMMDD) and weekday `delta` days from `ymd`. */
export function shiftDay(ymd, delta) {
  const d = new Date(Date.UTC(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8)));
  d.setUTCDate(d.getUTCDate() + delta);
  const out = d.toISOString().slice(0, 10).replaceAll("-", "");
  return { ymd: out, weekday: (d.getUTCDay() + 6) % 7 };
}

export const previousDay = (ymd) => shiftDay(ymd, -1);

/** "8:15 AM" from minutes after midnight (wraps past 24 h). */
export function formatClock(minutes) {
  const m = Math.floor(((minutes % 1440) + 1440) % 1440);
  const h = Math.floor(m / 60);
  const mm = String(m % 60).padStart(2, "0");
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${mm} ${h < 12 ? "AM" : "PM"}`;
}

/** "Wed, Oct 7" for a YYYYMMDD date. */
export function formatDay(ymd) {
  const d = new Date(Date.UTC(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8), 12));
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}
