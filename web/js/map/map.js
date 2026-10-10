// Live system map controller (IMPLEMENTATION_PLAN F3, DESIGN.md §6).
// Owns the clock (live or replay), sizing, the animation loop, pointer interaction, the list view and the
// screen-reader summary. Rendering lives in network.js (SVG) and trains.js (canvas).

import { formatDate, formatNumber, formatPercent } from "../chart.js";
import { apiUrl } from "../util/api.js";
import { formatClock, formatDay, pacificParts, shiftDay } from "../util/time.js";
import { makeView } from "./geometry.js";
import { renderNetwork, setActiveStation } from "./network.js";
import { isOutsideTimetable, nextDeparture, timetableRange, trainsAt } from "./schedule.js";
import { drawTrains, hitTrain, placeTrain, trainSize } from "./trains.js";

const SCRUB_MIN = 240; // 4:00 AM
const SCRUB_MAX = 1590; // 2:30 AM next day
const ZOOMS = [1, 1.5, 2.25, 3.4, 5];
const SUMMARY_EVERY_MS = 60_000;
const LIST_EVERY_MS = 5_000;
const REDUCED_MOTION_EVERY_MS = 30_000;

async function loadJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

export async function initMap(root) {
  const $ = (sel) => root.querySelector(sel);
  const stage = $(".map-stage");
  const svg = $(".map-svg");
  const canvas = $(".map-canvas");
  const ctx = canvas.getContext("2d");
  const tooltip = $(".tooltip");
  const notice = $(".map-notice");
  const listPanel = $(".map-list");
  const listBody = $(".map-list tbody");
  const listCount = $("[data-list-count]");
  const clockTime = $("[data-clock-time]");
  const clockStatus = $("[data-clock-status]");
  const clockDate = $("[data-clock-date]");
  const btnNow = $("[data-now]");
  const btnPlay = $("[data-play]");
  const scrub = $("[data-scrub]");
  const speedBtns = [...root.querySelectorAll("[data-speed]")];
  const viewBtns = [...root.querySelectorAll("[data-view]")];
  const zoomIn = $("[data-zoom-in]");
  const zoomOut = $("[data-zoom-out]");
  const summary = document.querySelector("[data-map-summary]");
  const legend = document.querySelector("[data-map-legend]");
  const loading = $(".map-loading");

  // --- data ------------------------------------------------------------------------------------------
  let data;
  try {
    const [network, schedule, land] = await Promise.all([
      loadJSON("data/network.json"),
      loadJSON("data/schedule.json"),
      loadJSON("data/land.json").catch(() => null), // the map still works without the coastline
    ]);
    data = { network, schedule, land };
  } catch (err) {
    console.error(err);
    loading.replaceWith(errorMessage(() => location.reload()));
    return;
  }
  loading.remove();
  const { network, schedule } = data;
  const lineName = Object.fromEntries(network.lines.map((l) => [l.id, l.name]));
  const days = {}; // per-service-day trip cache for schedule.trainsAt

  legend.replaceChildren(
    ...network.lines.map((l) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="swatch" style="background:var(--line-${l.id})"></span>${l.name} <span class="text-body">· ${l.desc}</span>`;
      return li;
    }),
  );

  // --- state -----------------------------------------------------------------------------------------
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const state = {
    live: true,
    playing: true,
    speed: 1,
    sim: null, // {ymd, weekday, minutes} for replay mode; minutes may exceed 1440
    zoomIdx: 0,
    center: null,
    selected: null, // {type: "train", trip} | {type: "station", index}
    view: "map",
    visible: true,
  };

  let view;
  let geom;
  let size;
  let dpr = 1;
  let placed = [];
  let lastFrame = 0;
  let lastDraw = 0;
  let lastList = 0;
  let lastSummary = 0;
  let raf = 0;
  let timer = 0;
  const colors = {};
  let ink = "#000";
  let canvasColor = "#fff";

  function readColors() {
    const cs = getComputedStyle(root);
    for (const l of network.lines) colors[l.id] = cs.getPropertyValue(`--line-${l.id}`).trim();
    ink = cs.getPropertyValue("--color-ink").trim();
    canvasColor = cs.getPropertyValue("--color-canvas").trim();
  }

  // --- clock -----------------------------------------------------------------------------------------
  function now() {
    if (state.live) {
      const p = pacificParts();
      // early-morning hours are the tail of the previous service day
      if (p.minutes < SCRUB_MIN) {
        const prev = shiftDay(p.ymd, -1);
        return { ymd: prev.ymd, weekday: prev.weekday, minutes: p.minutes + 1440 };
      }
      return p;
    }
    return state.sim;
  }

  function enterReplay() {
    if (!state.live) return;
    state.sim = { ...now() };
    state.live = false;
  }

  function goLive() {
    state.live = true;
    state.playing = true;
    state.speed = 1;
    state.sim = null;
    syncControls();
    tick(true);
  }

  function syncControls() {
    btnNow.setAttribute("aria-pressed", String(state.live));
    btnPlay.setAttribute("aria-label", state.playing ? "Pause" : "Play");
    btnPlay.querySelector("use").setAttribute("href", state.playing ? "#i-pause" : "#i-play");
    for (const b of speedBtns) b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === state.speed));
    const t = now();
    scrub.value = String(Math.min(SCRUB_MAX, Math.max(SCRUB_MIN, t.minutes)));
    scrub.setAttribute("aria-valuetext", formatClock(t.minutes));
    clockTime.textContent = formatClock(t.minutes);
    clockDate.textContent = ` · ${formatDay(t.minutes >= 1440 ? shiftDay(t.ymd, 1).ymd : t.ymd)}`;
    clockStatus.textContent = state.live ? "Live schedule" : state.playing ? `Replay ${state.speed}×` : "Paused";
  }

  // --- sizing ----------------------------------------------------------------------------------------
  function controlsInset() {
    // keep the network clear of the floating controls (only when they float over the map)
    const controls = $(".map-controls");
    const floating = getComputedStyle(controls).position === "absolute";
    const top = $(".map-top").offsetHeight + 12;
    return { top, right: 8, bottom: floating ? controls.offsetHeight + 24 : 8, left: 8 };
  }

  function layout() {
    const rect = stage.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    view = makeView(network.bounds, rect.width, rect.height, {
      zoom: ZOOMS[state.zoomIdx],
      center: state.center,
      padPx: controlsInset(),
    });
    geom = renderNetwork(svg, data, view);
    size = trainSize(rect.width);
    stage.classList.toggle("is-zoomed", state.zoomIdx > 0);
    zoomOut.disabled = state.zoomIdx === 0;
    zoomIn.disabled = state.zoomIdx === ZOOMS.length - 1;
    if (state.selected?.type === "station") setActiveStation(geom.stations, state.selected.index);
    draw(true);
  }

  // --- frame -----------------------------------------------------------------------------------------
  function computeTrains() {
    const t = now();
    const trains = trainsAt(schedule, days, t.ymd, t.weekday, t.minutes);
    placed = trains.map((tr) => ({ ...tr, ...placeTrain(tr, schedule, geom), trip: tr.entry.trip }));
    return t;
  }

  function draw(force = false) {
    if (!geom) return;
    const t = computeTrains();
    drawTrains(ctx, placed, {
      size,
      colors,
      ink,
      canvasColor,
      selectedTrip: state.selected?.type === "train" ? state.selected.trip : null,
      dpr,
      w: view.w,
      h: view.h,
    });
    updateNotice(t);
    if (state.selected) updateTooltip(t);
    const ms = performance.now();
    if (force || ms - lastList > LIST_EVERY_MS) {
      if (state.view === "list") renderList(t);
      lastList = ms;
    }
    if (force || ms - lastSummary > SUMMARY_EVERY_MS) {
      updateSummary(t);
      lastSummary = ms;
    }
    syncControls();
  }

  /** How often trains need redrawing: at 1× they move < 1 px/s, so a few frames a second is plenty. */
  function drawInterval() {
    if (reducedMotion.matches) return REDUCED_MOTION_EVERY_MS;
    if (!state.playing) return Infinity;
    return state.speed >= 60 ? 0 : state.speed >= 10 ? 50 : 250;
  }

  function tick(force = false) {
    cancelAnimationFrame(raf);
    clearTimeout(timer);
    if (!state.visible) return;
    const ms = performance.now();
    const dt = lastFrame ? ms - lastFrame : 0;
    lastFrame = ms;
    if (!state.live && state.playing && state.sim) {
      state.sim.minutes += (dt / 60_000) * state.speed;
      if (state.sim.minutes > SCRUB_MAX) state.sim.minutes = SCRUB_MIN;
    }
    if (force || ms - lastDraw >= drawInterval()) {
      draw(force);
      lastDraw = ms;
    }
    if (reducedMotion.matches) {
      timer = setTimeout(() => tick(), REDUCED_MOTION_EVERY_MS);
    } else if (state.playing || state.live) {
      raf = requestAnimationFrame(() => tick());
    }
  }

  function setVisible(v) {
    if (v === state.visible) return;
    state.visible = v;
    lastFrame = 0;
    if (v) tick(true);
    else {
      cancelAnimationFrame(raf);
      clearTimeout(timer);
    }
  }

  // --- out of service --------------------------------------------------------------------------------
  function updateNotice(t) {
    const empty = placed.length === 0;
    notice.hidden = !empty;
    if (!empty) return;
    const day = t.minutes >= 1440 ? shiftDay(t.ymd, 1) : { ymd: t.ymd, weekday: t.weekday };
    const text = notice.querySelector("[data-notice-text]");
    const jump = notice.querySelector("[data-jump]");
    if (isOutsideTimetable(schedule, day.ymd)) {
      // the bundled timetable doesn't cover this date, so "no trains" would be misleading
      const range = timetableRange(schedule);
      const fmt = (ymd) => formatDate(`${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}`);
      text.textContent =
        day.ymd > range.end
          ? `This site's BART timetable ended on ${fmt(range.end)}. Positions can't be shown until it's updated.`
          : `This site's BART timetable starts on ${fmt(range.start)}. Positions can't be shown until then.`;
      jump.hidden = true;
      return;
    }
    jump.hidden = false;
    const next = nextDeparture(schedule, days, day.ymd, day.weekday, t.minutes % 1440);
    text.textContent =
      next === null
        ? "No trains running right now."
        : `No trains running right now. Service resumes at ${formatClock(next)}.`;
  }

  notice.querySelector("[data-jump]").addEventListener("click", () => {
    const t = now();
    const ymd = t.minutes >= 1440 ? shiftDay(t.ymd, 1) : { ymd: t.ymd, weekday: t.weekday };
    state.live = false;
    state.sim = { ymd: ymd.ymd, weekday: ymd.weekday, minutes: 480 };
    state.playing = true;
    state.speed = 1;
    tick(true);
  });

  // --- tooltip ---------------------------------------------------------------------------------------
  function swatch(line) {
    return `<span class="swatch" style="background:var(--line-${line})"></span>`;
  }

  function trainHTML(tr, t) {
    const pattern = schedule.patterns[tr.entry.pattern];
    const dest = network.stations[pattern.stops[pattern.stops.length - 1]].short;
    let second;
    if (tr.next === null) {
      second = `Arrived at ${dest}`;
    } else {
      const next = network.stations[pattern.stops[tr.next]].short;
      const mins = Math.max(0, Math.ceil(tr.nextAt - (t.minutes + tr.dayOffset)));
      const at = tr.atStation ? `At ${network.stations[pattern.stops[tr.stop]].short} · ` : "";
      second = `${at}Next: ${next} · ${mins < 1 ? "arriving" : `${mins} min`}`;
    }
    return `<div class="tooltip__title">${swatch(pattern.line)}${lineName[pattern.line]} to ${dest}</div><div>${second}</div>`;
  }

  function stationHTML(i) {
    const s = network.stations[i];
    const lines = s.lines.map((l) => `${swatch(l)}`).join("");
    const names = s.lines.map((l) => lineName[l].replace(" line", "")).join(", ");
    const sum = stationSummary(s.code);
    let entries = "";
    if (sum) {
      const rec = sum.recovery_ratio === null ? "" : ` (${formatPercent(sum.recovery_ratio)} of 2019)`;
      entries = `<div data-station-entries>Entries on ${formatDate(sum.data_through)}: ${formatNumber(sum.entries)}${rec}</div>`;
    }
    return `<div class="tooltip__title">${s.name}</div><div class="tooltip__title">${lines}<span class="tooltip__muted">${names}</span></div>${entries}`;
  }

  // Ridership numbers for the station tooltip (GET /api/stations/{code}/summary), fetched once per station
  // after the first hover/tap. While the warehouse isn't connected (503) or a request fails, the tooltip simply
  // has no numbers line.
  const summaries = new Map(); // code → summary | null (none available) | "pending"
  let summariesOff = false;

  function stationSummary(code) {
    const have = summaries.get(code);
    if (have !== undefined) return have === "pending" ? null : have;
    if (summariesOff) return null;
    summaries.set(code, "pending");
    fetch(apiUrl(`api/stations/${encodeURIComponent(code)}/summary`), { headers: { Accept: "application/json" } })
      .then(async (res) => {
        if (res.status === 503) summariesOff = true;
        const body = res.ok ? await res.json() : null;
        summaries.set(code, body && Number.isFinite(body.entries) ? body : null);
      })
      .catch(() => summaries.set(code, null))
      .finally(() => {
        const sel = state.selected;
        if (sel?.type === "station" && network.stations[sel.index].code === code && geom) updateTooltip(now());
      });
    return null;
  }

  function placeTooltip(x, y) {
    tooltip.hidden = false;
    const w = tooltip.offsetWidth;
    const h = tooltip.offsetHeight;
    const pad = 8;
    let left = x + 14;
    let top = y - h - 10;
    if (left + w > view.w - pad) left = x - w - 14; // flip to stay inside the map
    if (left < pad) left = pad;
    if (top < pad) top = y + 16;
    if (top + h > view.h - pad) top = view.h - h - pad;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function updateTooltip(t) {
    const sel = state.selected;
    if (!sel) {
      tooltip.hidden = true;
      return;
    }
    if (sel.type === "train") {
      const tr = placed.find((p) => p.trip === sel.trip);
      if (!tr) {
        clearSelection(); // the trip ended
        return;
      }
      tooltip.innerHTML = trainHTML(tr, t);
      placeTooltip(tr.x, tr.y);
    } else {
      const s = geom.stations[sel.index];
      tooltip.innerHTML = stationHTML(sel.index);
      placeTooltip(s.x, s.y);
    }
  }

  function clearSelection() {
    state.selected = null;
    tooltip.hidden = true;
    if (geom) setActiveStation(geom.stations, -1);
  }

  function hitStation(x, y, radius) {
    let best = -1;
    let bestD = radius;
    geom.stations.forEach((s, i) => {
      const d = Math.hypot(s.x - x, s.y - y) - s.halfSpan;
      if (d <= bestD) {
        best = i;
        bestD = d;
      }
    });
    return best;
  }

  function hitAt(x, y) {
    const radius = parseFloat(getComputedStyle(stage).getPropertyValue("--map-hit-radius")) || 12;
    const tr = hitTrain(placed, x, y, radius);
    if (tr) return { type: "train", trip: tr.trip };
    const s = hitStation(x, y, radius);
    return s >= 0 ? { type: "station", index: s } : null;
  }

  function select(hit) {
    state.selected = hit;
    setActiveStation(geom.stations, hit?.type === "station" ? hit.index : -1);
    draw();
  }

  // --- pointer: hover (mouse), tap/click to pin, drag to pan when zoomed ------------------------------
  let drag = null;
  let pinned = false;

  stage.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button, input")) return;
    const r = stage.getBoundingClientRect();
    drag = { x: e.clientX, y: e.clientY, cx: view.center[0], cy: view.center[1], moved: false, rx: r.left, ry: r.top };
    if (state.zoomIdx > 0) stage.setPointerCapture(e.pointerId);
  });

  stage.addEventListener("pointermove", (e) => {
    if (!geom) return;
    const r = stage.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    if (drag && state.zoomIdx > 0) {
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (Math.hypot(dx, dy) > 4) {
        drag.moved = true;
        stage.classList.add("is-dragging");
        state.center = clampCenter([drag.cx - dx / view.scale, drag.cy - dy / view.scale]);
        layout();
      }
      return;
    }
    if (e.pointerType === "mouse" && !pinned) {
      const hit = hitAt(x, y);
      stage.style.cursor = hit ? "pointer" : "";
      if (JSON.stringify(hit) !== JSON.stringify(state.selected)) {
        if (hit) select(hit);
        else clearSelection();
      }
    }
  });

  stage.addEventListener("pointerup", (e) => {
    stage.classList.remove("is-dragging");
    const wasDrag = drag?.moved;
    drag = null;
    if (wasDrag || e.target.closest("button, input") || !geom) return;
    const r = stage.getBoundingClientRect();
    const hit = hitAt(e.clientX - r.left, e.clientY - r.top);
    if (hit) {
      pinned = true;
      select(hit);
    } else {
      pinned = false;
      clearSelection();
    }
  });

  stage.addEventListener("pointerleave", () => {
    if (!pinned) clearSelection();
  });

  // --- zoom ------------------------------------------------------------------------------------------
  function clampCenter([x, y]) {
    const [x0, y0, x1, y1] = network.bounds;
    return [Math.min(x1, Math.max(x0, x)), Math.min(y1, Math.max(y0, y))];
  }

  function setZoom(idx) {
    state.zoomIdx = Math.max(0, Math.min(ZOOMS.length - 1, idx));
    if (state.zoomIdx === 0) state.center = null;
    else state.center = clampCenter(state.center ?? view.center);
    layout();
  }

  zoomIn.addEventListener("click", () => setZoom(state.zoomIdx + 1));
  zoomOut.addEventListener("click", () => setZoom(state.zoomIdx - 1));

  // --- time controls ---------------------------------------------------------------------------------
  btnNow.addEventListener("click", goLive);

  btnPlay.addEventListener("click", () => {
    if (state.live) {
      enterReplay();
      state.playing = false;
    } else {
      state.playing = !state.playing;
    }
    lastFrame = 0;
    tick(true);
  });

  for (const b of speedBtns) {
    b.addEventListener("click", () => {
      enterReplay();
      state.speed = Number(b.dataset.speed);
      state.playing = true;
      lastFrame = 0;
      tick(true);
    });
  }

  scrub.min = String(SCRUB_MIN);
  scrub.max = String(SCRUB_MAX);
  scrub.addEventListener("input", () => {
    enterReplay();
    state.sim.minutes = Number(scrub.value);
    lastFrame = 0;
    tick(true);
  });

  // --- list view -------------------------------------------------------------------------------------
  for (const b of viewBtns) {
    b.addEventListener("click", () => {
      state.view = b.dataset.view;
      for (const x of viewBtns) x.setAttribute("aria-pressed", String(x === b));
      listPanel.hidden = state.view !== "list";
      stage.querySelector(".map-layers").hidden = state.view === "list";
      if (state.view === "list") renderList(now());
      else layout();
    });
  }

  function renderList(t) {
    const rows = placed
      .map((tr) => {
        const pattern = schedule.patterns[tr.entry.pattern];
        const dest = network.stations[pattern.stops[pattern.stops.length - 1]].short;
        const next = tr.next === null ? "—" : network.stations[pattern.stops[tr.next]].short;
        const mins = tr.next === null ? null : Math.max(0, Math.ceil(tr.nextAt - (t.minutes + tr.dayOffset)));
        return { line: pattern.line, dest, next, mins };
      })
      .sort((a, b) => a.line.localeCompare(b.line) || a.dest.localeCompare(b.dest) || (a.mins ?? 0) - (b.mins ?? 0));
    listCount.textContent = `${rows.length} trains running at ${formatClock(t.minutes)}`;
    listBody.replaceChildren(
      ...rows.map((r) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${swatch(r.line)} ${lineName[r.line]}</td><td>${r.dest}</td><td>${r.next}</td><td class="is-num">${r.mins === null ? "—" : r.mins < 1 ? "Arriving" : `${r.mins} min`}</td>`;
        return tr;
      }),
    );
  }

  // --- screen-reader summary -------------------------------------------------------------------------
  function updateSummary(t) {
    const lines = new Set(placed.map((p) => p.line));
    summary.textContent =
      placed.length === 0
        ? `No trains running at ${formatClock(t.minutes)}.`
        : `${placed.length} trains running on ${lines.size} lines at ${formatClock(t.minutes)}.`;
  }

  // --- lifecycle -------------------------------------------------------------------------------------
  readColors();
  new ResizeObserver(() => layout()).observe(stage);
  new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting && !document.hidden)).observe(stage);
  document.addEventListener("visibilitychange", () => setVisible(!document.hidden));
  reducedMotion.addEventListener("change", () => tick(true));
  matchMedia("(resolution: 1dppx)").addEventListener?.("change", layout);
  layout();
  tick(true);
  document.fonts?.ready.then(layout); // label sizes change once Inter has loaded
}

function errorMessage(retry) {
  const div = document.createElement("div");
  div.className = "message message--error";
  div.innerHTML = `<p class="message__text"><svg class="icon" aria-hidden="true"><use href="#i-circle-alert"/></svg>
    The map data didn't load. Check your connection and try again.</p>
    <button class="btn btn--subtle" type="button">Retry</button>`;
  div.querySelector("button").addEventListener("click", retry);
  return div;
}
