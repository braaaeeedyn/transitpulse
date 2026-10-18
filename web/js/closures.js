// Station closures band: the BART stations named in BART staff's February 2026 presentation (as reported), each with
// a rule-based "case to keep" verdict from BART's own ridership data, read from GET /api/closures. The rules' text
// and the verdict mapping come from the API (api/routes/data.py), so the page never restates a threshold, and every
// number comes from the marts. The context, not-final, neutral, caveat and source notes are static in index.html,
// so they show without data.
// States: skeletons while loading; 503 "Ridership data isn't connected yet."; 404 "This data hasn't been loaded
// yet."; any other error a message with Retry.

import { formatDelta, formatNumber, formatPercent } from "./chart.js";
import { esc, getJSON, messageHTML, NotConnected, NotFound } from "./trends.js";

export const RULE_NAMES = { riders: "Riders", recovery: "Recovery", distance: "Distance", growing: "Growing" };
const VERDICTS = ["strong", "mixed", "weak"];

/** "strong" → "Case to keep: strong" */
export function verdictLabel(verdict) {
  return `Case to keep: ${verdict}`;
}

/** A rule's result in words (the ✓/✗ next to it is decoration). */
export function ruleStatus(met) {
  return met ? "Met" : "Not met";
}

/** 2.9 → "2.9 mi" */
export function formatMiles(miles) {
  return miles === null || miles === undefined || !Number.isFinite(miles) ? "—" : `${miles.toFixed(1)} mi`;
}

/** 41 → "41%" (the API sends whole percentages, already rounded the way the rules compare them) */
export function formatWholePct(pct) {
  return pct === null || pct === undefined || !Number.isFinite(pct) ? "—" : `${pct}%`;
}

/** ["A"] → "A", ["A", "B"] → "A and B", ["A", "B", "C"] → "A, B and C" */
export function listText(items) {
  return items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** The summary tiles' sentences, from the API's system block. */
export function summarySentences(doc) {
  const s = doc.system;
  const first = doc.stations.filter((x) => x.group === 1).length;
  const unlisted = s.lowest_10.filter((x) => !x.listed).map((x) => x.name);
  const also = unlisted.length
    ? ` Also among them: ${listText(unlisted)}, which ${unlisted.length === 1 ? "isn't" : "aren't"} on the list.`
    : "";
  return {
    lowest: `${s.first_10_in_lowest_10} of the first ${first} are among the ${s.lowest_10.length} least-used stations in ${doc.period_year}.${also}`,
    first10: `${formatPercent(s.share_first_10, 1)} of weekday trips in ${doc.period_year} start or end at the first ${first}. The press reported about 12%.`,
    all15: `${formatPercent(s.share_all_15, 1)} of weekday trips start or end at one of all ${doc.stations.length}.`,
  };
}

/** The data line of the "What closing would cost" card. */
export function costSentence(doc) {
  const n = doc.stations.length;
  const growing = doc.stations.filter((s) => s.criteria.growing).length;
  const far = doc.stations.filter((s) => s.criteria.distance);
  const farthest = far.reduce((a, b) => (b.nearest_open.miles > a.nearest_open.miles ? b : a), far[0]);
  const reach = farthest
    ? ` ${far.length} of them are far enough from the next open station to meet the Distance rule; ${farthest.name} riders would be ${formatMiles(farthest.nearest_open.miles)} from ${farthest.nearest_open.name}.`
    : "";
  return (
    `In ${doc.period_year}, ${formatPercent(doc.system.share_all_15, 1)} of BART's weekday trips started or ended at one of these ${n} stations. ` +
    `${growing} of the ${n} carried more weekday riders than in ${doc.period_year - 1}: their riders are coming back.${reach}`
  );
}

// --- rendering -------------------------------------------------------------------------------------

function tileHTML(label, value, text) {
  return `<div class="stat-tile">
    <p class="stat-tile__label">${esc(label)}</p>
    <p class="stat-tile__value" data-count>${esc(value)}</p>
    <p class="closures__tile-text">${esc(text)}</p>
  </div>`;
}

function summaryHTML(doc) {
  const s = doc.system;
  const first = doc.stations.filter((x) => x.group === 1).length;
  const t = summarySentences(doc);
  return `<div class="grid-auto" data-closures-summary>
    ${tileHTML(`The first ${first} and the least used`, `${s.first_10_in_lowest_10} of ${first}`, t.lowest)}
    ${tileHTML(`Trips at the first ${first}`, formatPercent(s.share_first_10, 1), t.first10)}
    ${tileHTML(`Trips at all ${doc.stations.length}`, formatPercent(s.share_all_15, 1), t.all15)}
  </div>`;
}

export function rulesHTML(doc) {
  const rules = doc.rules
    .map((r) => `<li data-rule="${esc(r.id)}"><strong>${esc(RULE_NAMES[r.id] ?? r.id)}.</strong> ${esc(r.text)}</li>`)
    .join("");
  const verdicts = VERDICTS.map(
    (v) => `<li><span class="verdict-pill verdict-pill--${v}">${esc(verdictLabel(v))}</span>${esc(doc.verdicts[v])}</li>`,
  ).join("");
  return `<div class="card closures__rules" data-closures-rules>
    <h3>How the verdicts work</h3>
    <p>Each rule a station meets is a point for keeping it. The rules use service weekdays in ${esc(doc.period_year)} only. The first three were set before this section was built; Growing was added afterwards, so that stations whose riders are returning count for it.</p>
    <ol class="closures__rule-list">${rules}</ol>
    <ul class="closures__verdicts">${verdicts}</ul>
  </div>`;
}

function fact(label, value) {
  return `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;
}

export function stationCardHTML(st, doc) {
  const sys = doc.system;
  const id = `closure-${esc(st.code)}`;
  const recovery =
    st.recovery_pct === null || st.recovery_pct === undefined
      ? `No full ${doc.baseline_year} to compare (BART: ${formatWholePct(sys.recovery_pct)})`
      : `${formatWholePct(st.recovery_pct)} of ${doc.baseline_year} (BART: ${formatWholePct(sys.recovery_pct)})`;
  const change = formatDelta(st.change_vs_prev_year, "entries") || "—";
  const dests = st.destinations
    .map((d) => `<li>${esc(d.name)} <span class="closure-card__share">${esc(formatPercent(d.share))}</span></li>`)
    .join("");
  const rules = doc.rules
    .map((r) => {
      const met = Boolean(st.criteria[r.id]);
      return `<li data-rule="${esc(r.id)}" data-met="${met}"><span class="closure-card__mark" aria-hidden="true">${met ? "✓" : "✗"}</span>${esc(RULE_NAMES[r.id] ?? r.id)}: ${ruleStatus(met)}</li>`;
    })
    .join("");
  return `<article class="card closure-card" data-closure-station="${esc(st.code)}" data-verdict="${esc(st.verdict)}" aria-labelledby="${id}">
    <div class="closure-card__head">
      <h4 id="${id}">${esc(st.name)}</h4>
      <p class="closure-card__segment">${esc(st.segment ? `${st.segment} segment` : "Not part of a listed segment")}</p>
    </div>
    <p class="verdict-pill verdict-pill--${esc(st.verdict)}">${esc(verdictLabel(st.verdict))}</p>
    <dl class="closure-card__facts">
      ${fact(`Weekday trips in ${doc.period_year}`, `${formatNumber(st.weekday_trips)}, rank ${st.rank_lowest} of ${sys.stations} from the fewest`)}
      ${fact("Recovery", recovery)}
      ${fact(`Change vs ${doc.period_year - 1}`, change)}
      ${fact("Nearest station still open", `${st.nearest_open.name}, ${formatMiles(st.nearest_open.miles)}`)}
    </dl>
    ${dests ? `<p class="closure-card__label">Top destinations</p><ol class="closure-card__dests">${dests}</ol>` : ""}
    <ul class="closure-card__rules" aria-label="Rules">${rules}</ul>
  </article>`;
}

function groupHTML(doc, group, title, intro) {
  const stations = doc.stations.filter((s) => s.group === group);
  if (!stations.length) return "";
  return `<section class="closures__group" data-closures-group="${group}" aria-labelledby="closures-group-${group}">
    <h3 id="closures-group-${group}">${esc(title)}</h3>
    <p>${esc(intro)}</p>
    <div class="closures__cards">${stations.map((s) => stationCardHTML(s, doc)).join("")}</div>
  </section>`;
}

export function groupsHTML(doc) {
  const n1 = doc.stations.filter((s) => s.group === 1).length;
  const n2 = doc.stations.filter((s) => s.group === 2).length;
  const segments = [...new Set(doc.stations.map((s) => s.segment).filter(Boolean))];
  return (
    groupHTML(
      doc,
      1,
      `The first ${n1}: lowest ridership`,
      "BART staff started, as reported, from the stations with the lowest ridership. Fewest weekday trips first.",
    ) +
    groupHTML(
      doc,
      2,
      `The next ${n2}: line-end segments`,
      `Closing these as well as the first ${n1} would close all the listed stations on ${segments.length} line-end segments: ${listText(segments)}.`,
    )
  );
}

export function initClosures(root) {
  if (!root) return;
  const skeleton = root.innerHTML;

  async function load() {
    root.setAttribute("aria-busy", "true");
    try {
      const doc = await getJSON("api/closures");
      root.innerHTML = summaryHTML(doc) + rulesHTML(doc) + groupsHTML(doc);
      const cost = root.closest("section")?.querySelector("[data-closures-cost-data]");
      if (cost) {
        cost.textContent = costSentence(doc);
        cost.hidden = false;
      }
    } catch (err) {
      if (err instanceof NotConnected) {
        root.innerHTML = messageHTML("Ridership data isn't connected yet.");
      } else if (err instanceof NotFound) {
        root.innerHTML = messageHTML("This data hasn't been loaded yet.");
      } else {
        console.error(err);
        root.innerHTML = messageHTML("The station closures data didn't load. Check your connection and try again.", {
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

  load();
}
