// "What if stations close?" picker under the live map. Picks stations from the closure list in BART staff's
// February 2026 presentation (as reported; dbt/transitpulse/seeds/bart_closure_candidates.csv is the same list,
// and tests/web/whatif.test.mjs keeps them in step). The map hides the picked stations and runs the same trains
// through them without stopping (schedule.closedStops).

import { formatPercent } from "../chart.js";
import { getJSON } from "../trends.js";

export const AT_RISK = {
  first10: ["OAKL", "PCTR", "NCON", "WARM", "CAST", "WDUB", "ORIN", "SSAN", "SHAY", "SBRN"],
  next5: ["COLM", "MLBR", "DUBL", "PITT", "ANTC"],
};
const ALL15 = [...AT_RISK.first10, ...AT_RISK.next5];
const PRESETS = { none: [], first10: AT_RISK.first10, all15: ALL15 };

const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

/** Which preset (if any) a set of closed codes matches. */
export function presetOf(codes) {
  return Object.keys(PRESETS).find((k) => sameSet(PRESETS[k], codes)) ?? null;
}

/**
 * The status line under the picker. `closures` is GET /api/closures (or null when it isn't available): the exact
 * trip shares for the two presets, otherwise the sum of the stations' shares, which counts a trip between two
 * closed stations twice, so it's an upper bound.
 */
export function whatIfStatus(codes, total, closures) {
  if (!codes.length) return `Today's map: all ${total} stations open.`;
  const n = codes.length;
  let share = "";
  if (closures) {
    const preset = presetOf(codes);
    const s = closures.system;
    if (preset === "first10" && s.share_first_10 !== null) {
      share = ` ${formatPercent(s.share_first_10, 1)} of weekday trips start or end at them.`;
    } else if (preset === "all15" && s.share_all_15 !== null) {
      share = ` ${formatPercent(s.share_all_15, 1)} of weekday trips start or end at them.`;
    } else {
      const byCode = Object.fromEntries(closures.stations.map((x) => [x.code, x.share_of_trips]));
      const sum = codes.reduce((acc, c) => acc + (byCode[c] ?? 0), 0);
      if (sum > 0) share = ` Up to ${formatPercent(sum, 1)} of weekday trips start or end at ${n === 1 ? "it" : "them"}.`;
    }
  }
  return `${n} of ${total} stations closed. The same trains run through ${n === 1 ? "it" : "them"} without stopping.${share}`;
}

/**
 * Wire the picker. `stations` is network.stations (codes and short names); `onChange(codes)` gets the closed codes.
 */
export function initWhatIf(root, stations, onChange) {
  if (!root) return;
  const list = root.querySelector("[data-whatif-stations]");
  const status = root.querySelector("[data-whatif-status]");
  const presets = [...root.querySelectorAll("[data-whatif-preset]")];
  const name = Object.fromEntries(stations.map((s) => [s.code, s.short]));
  let closed = [];
  let closures = null;

  list.innerHTML = ALL15.filter((c) => name[c])
    .map((c) => `<button type="button" class="chip whatif__station" data-whatif-code="${c}" aria-pressed="false">${name[c]}</button>`)
    .join("");

  function set(codes) {
    closed = codes;
    for (const b of list.querySelectorAll("[data-whatif-code]")) b.setAttribute("aria-pressed", String(codes.includes(b.dataset.whatifCode)));
    const preset = presetOf(codes);
    for (const b of presets) b.setAttribute("aria-pressed", String(b.dataset.whatifPreset === preset));
    status.textContent = whatIfStatus(codes, stations.length, closures);
    onChange(codes);
    // the trip shares come from the closures API; fetched once, on the first closure, and optional
    if (codes.length && closures === null) {
      closures = false;
      getJSON("api/closures").then(
        (doc) => {
          closures = doc;
          status.textContent = whatIfStatus(closed, stations.length, closures);
        },
        () => {},
      );
    }
  }

  for (const b of presets) b.addEventListener("click", () => set([...PRESETS[b.dataset.whatifPreset]]));
  list.addEventListener("click", (e) => {
    const b = e.target.closest("[data-whatif-code]");
    if (!b) return;
    const c = b.dataset.whatifCode;
    set(closed.includes(c) ? closed.filter((x) => x !== c) : [...closed, c]);
  });
  set([]);
}
