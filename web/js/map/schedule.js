// Where every train is at a given moment, interpolated from the published GTFS schedule (no live feed).
// Pure functions over the data in web/data/schedule.json, so they can be tested without a browser.

import { previousDay, shiftDay } from "../util/time.js";

/** Is a service (from schedule.services) running on calendar date ymd (YYYYMMDD) with weekday 0=Mon…6=Sun? */
export function serviceRunsOn(svc, ymd, weekday) {
  if (svc.removed.includes(ymd)) return false;
  if (svc.added.includes(ymd)) return true;
  return svc.days[weekday] === "1" && ymd >= svc.start && ymd <= svc.end;
}

/**
 * First and last calendar dates (YYYYMMDD) any service in the timetable can run on, counting added dates.
 * Outside this range the published timetable has no trains at all, which is not the same as "no trains right now".
 */
export function timetableRange(schedule) {
  let start = null;
  let end = null;
  for (const svc of schedule.services) {
    for (const d of [svc.start, ...svc.added]) if (start === null || d < start) start = d;
    for (const d of [svc.end, ...svc.added]) if (end === null || d > end) end = d;
  }
  return { start, end };
}

/** Is calendar date ymd (YYYYMMDD) before the timetable starts or after it ends? */
export function isOutsideTimetable(schedule, ymd) {
  const { start, end } = timetableRange(schedule);
  return start !== null && (ymd < start || ymd > end);
}

/**
 * Build a lookup of the trips that run on one service day.
 * Returns [{trip, start, end, pattern, profile}] sorted by start (minutes after that day's midnight).
 */
export function tripsForDay(schedule, ymd, weekday) {
  const active = new Set();
  schedule.services.forEach((svc, i) => {
    if (serviceRunsOn(svc, ymd, weekday)) active.add(i);
  });
  const out = [];
  schedule.trips.forEach(([pattern, service, profile, start], i) => {
    if (!active.has(service)) return;
    const prof = schedule.profiles[profile];
    out.push({ trip: i, pattern, profile: prof, start, end: start + prof[prof.length - 1] });
  });
  out.sort((a, b) => a.start - b.start);
  return out;
}

/**
 * Position of one trip at time t (minutes after its service day's midnight), or null if not running.
 * Returns {hop, frac, stop, atStation, next, nextAt}:
 *   hop        index into pattern.hops (the edge being travelled), or -1 when dwelling at the first stop
 *   frac       0..1 progress along that hop (linear in time — BART runs at roughly constant speed between stations)
 *   stop       index into pattern.stops of the current/last station
 *   atStation  true while dwelling
 *   next       index into pattern.stops of the next station (null at the terminus)
 *   nextAt     minutes at which it reaches `next`
 */
export function tripPosition(entry, t) {
  if (t < entry.start || t > entry.end) return null;
  const rel = t - entry.start;
  const p = entry.profile; // [arr0, dep0, arr1, dep1, …]
  const n = p.length / 2;
  for (let i = 0; i < n; i++) {
    const arr = p[2 * i];
    const dep = p[2 * i + 1];
    if (rel >= arr && rel <= dep) {
      const next = i + 1 < n ? i + 1 : null;
      return {
        hop: i === 0 ? -1 : i - 1,
        frac: i === 0 ? 0 : 1,
        stop: i,
        atStation: true,
        next,
        nextAt: next === null ? null : entry.start + p[2 * next],
      };
    }
    if (i + 1 < n && rel > dep && rel < p[2 * (i + 1)]) {
      const nextArr = p[2 * (i + 1)];
      return {
        hop: i,
        frac: (rel - dep) / (nextArr - dep),
        stop: i,
        atStation: false,
        next: i + 1,
        nextAt: entry.start + nextArr,
      };
    }
  }
  return null;
}

/**
 * Every train running at minute `minutes` on calendar date ymd (Pacific).
 * After-midnight trips belong to the *previous* service day, with times past 1440, so both days are checked.
 * `days` is a cache object {ymd: tripsForDay(...)} owned by the caller.
 */
export function trainsAt(schedule, days, ymd, weekday, minutes) {
  if (minutes >= 1440) {
    // a time past midnight on service day `ymd` is early morning of the next calendar day
    ({ ymd, weekday } = shiftDay(ymd, 1));
    minutes -= 1440;
  }
  const prev = previousDay(ymd);
  const sets = [
    [ymd, weekday, minutes],
    [prev.ymd, prev.weekday, minutes + 1440],
  ];
  const trains = [];
  for (const [d, wd, t] of sets) {
    days[d] ??= tripsForDay(schedule, d, wd);
    for (const entry of days[d]) {
      if (entry.start > t) break; // sorted by start
      if (entry.end < t) continue;
      const pos = tripPosition(entry, t);
      if (pos) trains.push({ ...pos, entry, serviceDay: d, dayOffset: t - minutes });
    }
  }
  return trains;
}

/** First departure (minutes after midnight) on a service day at or after `minutes`, or null. */
export function nextDeparture(schedule, days, ymd, weekday, minutes) {
  days[ymd] ??= tripsForDay(schedule, ymd, weekday);
  const next = days[ymd].find((e) => e.start >= minutes);
  return next ? next.start : null;
}
