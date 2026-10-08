// SVG base layer: land, track (with casing and parallel lanes), stations and labels — drawn in CSS pixels.

import { laneOffset, measure, offsetPolyline, pathData } from "./geometry.js";

const SVG = "http://www.w3.org/2000/svg";
const LABEL_GAP = 5;

function el(name, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

/** Read a numeric CSS length (px) from a custom property on `node`. */
export function cssPx(node, name) {
  return parseFloat(getComputedStyle(node).getPropertyValue(name)) || 0;
}

/**
 * Render the whole base layer into `svg` for the given view. Returns the pixel geometry the trains need:
 *   lanes[edgeIndex][lineId] = measured polyline in px, oriented from edge.a to edge.b
 *   stations[i] = {x, y, r, halfSpan}
 */
export function renderNetwork(svg, { network, land }, view) {
  const lineWidth = cssPx(svg, "--map-line-width");
  const gap = cssPx(svg, "--map-lane-gap");
  const r = cssPx(svg, "--map-station-radius");
  const spacing = lineWidth + gap;

  svg.setAttribute("viewBox", `0 0 ${view.w} ${view.h}`);
  svg.replaceChildren();

  // --- land ---
  if (land) {
    const d = land.polygons
      .map((rings) =>
        rings.map((ring) => pathData(ring.map(([x, y]) => view.toPx(x, y))) + "Z").join(""),
      )
      .join("");
    el("path", { d, class: "map-land" }, svg);
  }

  // --- track: all casings first, then all colours, so casings never cover a neighbouring lane ---
  const casingGroup = el("g", { "aria-hidden": "true" }, svg);
  const lineGroup = el("g", { "aria-hidden": "true" }, svg);
  const lanes = network.edges.map((edge) => {
    const centre = edge.pts.map(([x, y]) => view.toPx(x, y));
    const out = {};
    edge.lines.forEach((line, i) => {
      const pts = offsetPolyline(centre, laneOffset(i, edge.lines.length, lineWidth, gap));
      const d = pathData(pts);
      el("path", { d, class: "map-track map-track--casing" }, casingGroup);
      el("path", { d, class: "map-track map-track--line", stroke: `var(--line-${line})` }, lineGroup);
      out[line] = measure(pts);
    });
    return out;
  });

  // --- stations: plain circles, or a capsule spanning every lane at transfer points ---
  const maxLanes = network.stations.map(() => 1);
  const capsuleDir = network.stations.map(() => null);
  network.edges.forEach((edge) => {
    for (const s of [edge.a, edge.b]) {
      if (edge.lines.length >= maxLanes[s]) {
        maxLanes[s] = edge.lines.length;
        const [ax, ay] = edge.pts[0];
        const [bx, by] = edge.pts[edge.pts.length - 1];
        capsuleDir[s] = Math.atan2(by - ay, bx - ax);
      }
    }
  });

  const stationGroup = el("g", { class: "map-stations" }, svg);
  const labelGroup = el("g", { "aria-hidden": "true" }, svg);
  const labelJobs = [];
  // DESIGN.md v1.0.1: below 600 px map width, capsules overlap each other and hide the trains, so every station
  // is a plain circle there.
  const capsules = view.w >= 600;
  const stations = network.stations.map((s, i) => {
    const [x, y] = view.toPx(s.x, s.y);
    const halfSpan = capsules ? ((maxLanes[i] - 1) * spacing) / 2 : 0;
    let marker;
    if (capsules && maxLanes[i] > 1) {
      // capsule perpendicular to the track direction
      const deg = (capsuleDir[i] * 180) / Math.PI + 90;
      marker = el(
        "rect",
        {
          x: (x - halfSpan - r).toFixed(1),
          y: (y - r).toFixed(1),
          width: (2 * halfSpan + 2 * r).toFixed(1),
          height: (2 * r).toFixed(1),
          rx: r.toFixed(1),
          transform: `rotate(${deg.toFixed(1)} ${x.toFixed(1)} ${y.toFixed(1)})`,
          class: "map-station",
        },
        stationGroup,
      );
    } else {
      marker = el("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: r.toFixed(1), class: "map-station" }, stationGroup);
    }
    marker.dataset.station = String(i);
    labelJobs.push({ i, s, x, y, off: r + halfSpan + LABEL_GAP });
    return { x, y, r, halfSpan, marker };
  });

  placeLabels(labelGroup, labelJobs, stations, lanes, view);
  return { lanes, stations, lineWidth };
}

// --- label placement ----------------------------------------------------------------------------------
// DESIGN.md §6: labels never cross a line; below 600 px only hubs. Labels are placed greedily (hubs first, then
// busier stations), each trying its preferred side then the others; a label that fits nowhere is left out —
// the station is still reachable by tap/hover and in the list view.

const SIDE_ORDER = ["E", "W", "N", "S"];
const LABEL_PAD = 2;

function labelAnchor(side, x, y, off) {
  return {
    E: [x + off, y, "start", "central"],
    W: [x - off, y, "end", "central"],
    N: [x, y - off, "middle", "auto"],
    S: [x, y + off, "middle", "hanging"],
  }[side];
}

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** Points every ~4 px along every lane, used to keep labels off the track. */
function trackSamples(lanes) {
  const pts = [];
  for (const edge of lanes) {
    for (const m of Object.values(edge)) {
      for (let i = 1; i < m.pts.length; i++) {
        const [ax, ay] = m.pts[i - 1];
        const [bx, by] = m.pts[i];
        const n = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / 4));
        for (let k = 0; k <= n; k++) pts.push([ax + ((bx - ax) * k) / n, ay + ((by - ay) * k) / n]);
      }
    }
  }
  return pts;
}

function placeLabels(group, jobs, stations, lanes, view) {
  const hubsOnly = view.w < 600;
  const track = trackSamples(lanes);
  const blocked = stations.map((s) => ({
    x: s.x - s.r - s.halfSpan,
    y: s.y - s.r - s.halfSpan,
    w: 2 * (s.r + s.halfSpan),
    h: 2 * (s.r + s.halfSpan),
  }));
  const placed = [];
  const order = jobs
    .filter((j) => !hubsOnly || j.s.hub)
    .sort((a, b) => Number(b.s.hub) - Number(a.s.hub) || b.s.lines.length - a.s.lines.length || a.i - b.i);

  for (const job of order) {
    const sides = [job.s.label, ...SIDE_ORDER.filter((x) => x !== job.s.label)];
    const text = el("text", { class: `map-label${job.s.hub ? "" : " map-label--minor"}` }, group);
    text.textContent = job.s.short;
    let chosen = null;
    for (const side of sides) {
      const [ax, ay, anchor, baseline] = labelAnchor(side, job.x, job.y, job.off);
      text.setAttribute("x", ax.toFixed(1));
      text.setAttribute("y", ay.toFixed(1));
      text.setAttribute("text-anchor", anchor);
      text.setAttribute("dominant-baseline", baseline);
      const b = text.getBBox();
      const box = { x: b.x - LABEL_PAD, y: b.y - LABEL_PAD, w: b.width + 2 * LABEL_PAD, h: b.height + 2 * LABEL_PAD };
      const inside = box.x >= 0 && box.y >= 0 && box.x + box.w <= view.w && box.y + box.h <= view.h;
      const clear =
        inside &&
        !placed.some((p) => overlaps(p, box)) &&
        !blocked.some((s, k) => k !== job.i && overlaps(s, box)) &&
        !track.some(([px, py]) => px > box.x && px < box.x + box.w && py > box.y && py < box.y + box.h);
      if (clear) {
        chosen = box;
        break;
      }
    }
    if (!chosen && job.s.hub) {
      // hubs always get a label: fall back to the preferred side
      const [ax, ay, anchor, baseline] = labelAnchor(job.s.label, job.x, job.y, job.off);
      text.setAttribute("x", ax.toFixed(1));
      text.setAttribute("y", ay.toFixed(1));
      text.setAttribute("text-anchor", anchor);
      text.setAttribute("dominant-baseline", baseline);
      const b = text.getBBox();
      chosen = { x: b.x, y: b.y, w: b.width, h: b.height };
    }
    if (chosen) placed.push(chosen);
    else text.remove();
  }
}

/** Highlight one station marker (or none). */
export function setActiveStation(stations, index) {
  stations.forEach((s, i) => s.marker.classList.toggle("is-active", i === index));
}
