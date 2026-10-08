"""Small, dependency-free geometry helpers for building the map data."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class Projection:
    """Equirectangular projection centred on the network, scaled into a 0–1000 box (SVG y points down).

    Longitude is shrunk by cos(mid-latitude) so distances look right at the Bay's latitude.
    """

    lon0: float  # west edge of the content
    lat0: float  # north edge of the content
    k: float  # cos(mid-latitude)
    scale: float  # viewBox units per degree of latitude
    x_off: float
    y_off: float

    @classmethod
    def fit(cls, lonlats: Sequence[Point], size: float = 1000.0, margin: float = 40.0) -> Projection:
        lons = [p[0] for p in lonlats]
        lats = [p[1] for p in lonlats]
        k = math.cos(math.radians((min(lats) + max(lats)) / 2))
        w = (max(lons) - min(lons)) * k
        h = max(lats) - min(lats)
        scale = (size - 2 * margin) / max(w, h)
        # centre the content inside the square
        x_off = (size - w * scale) / 2
        y_off = (size - h * scale) / 2
        return cls(lon0=min(lons), lat0=max(lats), k=k, scale=scale, x_off=x_off, y_off=y_off)

    def __call__(self, lon: float, lat: float) -> Point:
        x = self.x_off + (lon - self.lon0) * self.k * self.scale
        y = self.y_off + (self.lat0 - lat) * self.scale
        return (x, y)

    def inverse(self, x: float, y: float) -> Point:
        lon = self.lon0 + (x - self.x_off) / (self.k * self.scale)
        lat = self.lat0 - (y - self.y_off) / self.scale
        return (lon, lat)


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def nearest_index(points: Sequence[Point], target: Point, start: int = 0) -> int:
    """Index of the vertex in points[start:] closest to target."""
    best_i, best_d = start, float("inf")
    for i in range(start, len(points)):
        d = dist(points[i], target)
        if d < best_d:
            best_i, best_d = i, d
    return best_i


def _perp_dist(p: Point, a: Point, b: Point) -> float:
    if a == b:
        return dist(p, a)
    (x, y), (x1, y1), (x2, y2) = p, a, b
    return abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1) / dist(a, b)


def simplify(points: Sequence[Point], tolerance: float) -> list[Point]:
    """Douglas–Peucker line simplification (iterative, keeps endpoints)."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        best_k, best_d = -1, tolerance
        for k in range(i + 1, j):
            d = _perp_dist(points[k], points[i], points[j])
            if d > best_d:
                best_k, best_d = k, d
        if best_k != -1:
            keep[best_k] = True
            stack += [(i, best_k), (best_k, j)]
    return [p for p, kept in zip(points, keep, strict=True) if kept]


def polyline_length(points: Sequence[Point]) -> float:
    return sum(dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def round_pts(points: Sequence[Point], nd: int = 1) -> list[list[float]]:
    return [[round(x, nd), round(y, nd)] for x, y in points]
