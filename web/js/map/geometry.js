// Map geometry: fitting the network into the container, parallel lanes on shared track, and sampling points
// along a path. Data coordinates are 0–1000 "map units"; everything drawn is converted to CSS pixels.

/**
 * A view maps map units -> CSS pixels for a container of size w×h.
 * It fits `bounds` (with padding) into the container, keeping aspect ratio, then applies zoom around `center`.
 */
export function makeView(bounds, w, h, { zoom = 1, center = null, pad = 0.06, padPx = null } = {}) {
  const [x0, y0, x1, y1] = bounds;
  const bw = x1 - x0;
  const bh = y1 - y0;
  const px = padPx ?? { top: 0, right: 0, bottom: 0, left: 0 };
  const innerW = Math.max(1, w - px.left - px.right);
  const innerH = Math.max(1, h - px.top - px.bottom);
  const fit = Math.min(innerW / (bw * (1 + 2 * pad)), innerH / (bh * (1 + 2 * pad)));
  const scale = fit * zoom;
  const cx = center ? center[0] : x0 + bw / 2;
  const cy = center ? center[1] : y0 + bh / 2;
  const ox = px.left + innerW / 2 - cx * scale;
  const oy = px.top + innerH / 2 - cy * scale;
  return {
    w,
    h,
    scale,
    zoom,
    center: [cx, cy],
    toPx: (x, y) => [ox + x * scale, oy + y * scale],
    toMap: (sx, sy) => [(sx - ox) / scale, (sy - oy) / scale],
  };
}

/** Unit normal for a direction, flipped so it always points west or south (DESIGN.md §6 lane order). */
function westSouthNormal(dx, dy) {
  const len = Math.hypot(dx, dy) || 1;
  let nx = -dy / len;
  let ny = dx / len;
  // screen y grows downward: "west or south" means -x or +y
  if (-nx + ny < 0) {
    nx = -nx;
    ny = -ny;
  }
  return [nx, ny];
}

/**
 * Offset a pixel polyline sideways by `d` pixels. The side is fixed per edge (from its chord) so every segment of
 * the edge shifts the same way; vertex normals are averaged with a miter limit to avoid spikes on sharp bends.
 */
export function offsetPolyline(pts, d) {
  if (d === 0 || pts.length < 2) return pts.map((p) => [p[0], p[1]]);
  const first = pts[0];
  const last = pts[pts.length - 1];
  const [cnx, cny] = westSouthNormal(last[0] - first[0], last[1] - first[1]);
  const segNormals = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const dx = pts[i + 1][0] - pts[i][0];
    const dy = pts[i + 1][1] - pts[i][1];
    const len = Math.hypot(dx, dy) || 1;
    let nx = -dy / len;
    let ny = dx / len;
    if (nx * cnx + ny * cny < 0) {
      nx = -nx;
      ny = -ny;
    }
    segNormals.push([nx, ny]);
  }
  return pts.map((p, i) => {
    const a = segNormals[Math.max(0, i - 1)];
    const b = segNormals[Math.min(segNormals.length - 1, i)];
    let nx = a[0] + b[0];
    let ny = a[1] + b[1];
    const len = Math.hypot(nx, ny) || 1;
    nx /= len;
    ny /= len;
    const cos = nx * b[0] + ny * b[1];
    const miter = Math.min(2, 1 / Math.max(cos, 0.5));
    return [p[0] + nx * d * miter, p[1] + ny * d * miter];
  });
}

/** Pre-compute cumulative lengths so points can be sampled by fraction of length. */
export function measure(pts) {
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  }
  return { pts, cum, length: cum[cum.length - 1] };
}

/** Point and heading (radians) at fraction f (0..1) of a measured polyline. */
export function pointAt(m, f) {
  const target = Math.min(1, Math.max(0, f)) * m.length;
  let i = 1;
  while (i < m.cum.length - 1 && m.cum[i] < target) i++;
  const a = m.pts[i - 1];
  const b = m.pts[i];
  const seg = m.cum[i] - m.cum[i - 1] || 1;
  const t = (target - m.cum[i - 1]) / seg;
  return {
    x: a[0] + (b[0] - a[0]) * t,
    y: a[1] + (b[1] - a[1]) * t,
    angle: Math.atan2(b[1] - a[1], b[0] - a[0]),
  };
}

/** Lane offset in pixels for lane `i` of `n` lanes. */
export function laneOffset(i, n, lineWidth, gap) {
  return (i - (n - 1) / 2) * (lineWidth + gap);
}

/** SVG path data for a pixel polyline. */
export function pathData(pts) {
  return pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
}
