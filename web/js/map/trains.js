// Canvas layer: small pill-shaped trains, one per running trip, sitting in their own line's lane (DESIGN.md §6).

import { pointAt } from "./geometry.js";

/** Train length in CSS px: clamp(6px, 1.2% of map width, 14px); width is 42% of length. */
export function trainSize(mapWidth) {
  const length = Math.min(14, Math.max(6, mapWidth * 0.012));
  return { length, width: length * 0.42 };
}

/** Pixel position + heading for one train (see schedule.tripPosition for the fields of `train`). */
export function placeTrain(train, schedule, geom) {
  const pattern = schedule.patterns[train.entry.pattern];
  const line = pattern.line;
  if (train.atStation) {
    const s = geom.stations[pattern.stops[train.stop]];
    // heading: along the hop just finished, or the one about to start
    const hopIdx = train.hop >= 0 ? train.hop : 0;
    const [edgeIdx, dir] = pattern.hops[hopIdx] ?? [null, 1];
    let angle = 0;
    if (edgeIdx !== null) {
      const m = geom.lanes[edgeIdx][line];
      const p = pointAt(m, 0.5);
      angle = p.angle + (dir === 1 ? 0 : Math.PI);
    }
    return { x: s.x, y: s.y, angle, line };
  }
  const [edgeIdx, dir] = pattern.hops[train.hop];
  const m = geom.lanes[edgeIdx][line];
  const p = pointAt(m, dir === 1 ? train.frac : 1 - train.frac);
  return { x: p.x, y: p.y, angle: p.angle + (dir === 1 ? 0 : Math.PI), line };
}

function pill(ctx, length, width) {
  const r = width / 2;
  const h = length / 2 - r;
  ctx.beginPath();
  ctx.moveTo(-h, -r);
  ctx.lineTo(h, -r);
  ctx.arc(h, 0, r, -Math.PI / 2, Math.PI / 2);
  ctx.lineTo(-h, r);
  ctx.arc(-h, 0, r, Math.PI / 2, (3 * Math.PI) / 2);
  ctx.closePath();
}

/** Draw every placed train. `colors` maps line id -> CSS colour; `selectedTrip` gets the 1.5× + halo treatment. */
export function drawTrains(ctx, placed, { size, colors, ink, canvasColor, selectedTrip, dpr, w, h }) {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  let selected = null;
  for (const t of placed) {
    if (t.trip === selectedTrip) {
      selected = t;
      continue;
    }
    ctx.save();
    ctx.translate(t.x, t.y);
    ctx.rotate(t.angle);
    pill(ctx, size.length, size.width);
    ctx.fillStyle = colors[t.line];
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = ink;
    ctx.stroke();
    ctx.restore();
  }
  if (selected) {
    const L = size.length * 1.5;
    const W = size.width * 1.5;
    ctx.save();
    ctx.translate(selected.x, selected.y);
    ctx.rotate(selected.angle);
    // halo: white gap then a 2 px ink ring
    pill(ctx, L + 8, W + 8);
    ctx.fillStyle = canvasColor;
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = ink;
    ctx.stroke();
    pill(ctx, L, W);
    ctx.fillStyle = colors[selected.line];
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.restore();
  }
}

/** Nearest train within `radius` px of (x, y), or null. */
export function hitTrain(placed, x, y, radius) {
  let best = null;
  let bestD = radius;
  for (const t of placed) {
    const d = Math.hypot(t.x - x, t.y - y);
    if (d <= bestD) {
      best = t;
      bestD = d;
    }
  }
  return best;
}
