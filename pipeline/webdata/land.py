"""Bay Area land polygons for the map background.

Source: US Census cartographic boundary file `cb_2023_us_county_500k` (public domain). Cartographic boundaries are
clipped to the shoreline, so the union of the Bay Area counties is an accurate land shape at this scale
(Natural Earth, named in DESIGN.md, is too coarse at 1:10M to show the Bay clearly).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import shapefile  # pyshp
from shapely.geometry import MultiPolygon, Polygon, box, shape
from shapely.ops import transform, unary_union

from pipeline.webdata.geometry import Projection

COUNTIES_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
# California county FIPS for the nine Bay Area counties.
BAY_AREA = {"001", "013", "041", "055", "075", "081", "085", "095", "097"}
# Clip window in viewBox units: wide enough for the 16:9 crop of the map (DESIGN.md §6) with room to spare.
CLIP = (-600.0, -150.0, 1600.0, 1150.0)
SIMPLIFY_TOLERANCE = 0.8
MIN_AREA = 30.0  # drop specks smaller than this (viewBox units²)


def _read_counties(path: Path):
    with zipfile.ZipFile(path) as z:
        base = next(n[:-4] for n in z.namelist() if n.endswith(".shp"))
        reader = shapefile.Reader(
            shp=io.BytesIO(z.read(base + ".shp")),
            shx=io.BytesIO(z.read(base + ".shx")),
            dbf=io.BytesIO(z.read(base + ".dbf")),
        )
        fields = [f[0] for f in reader.fields[1:]]
        for sr in reader.iterShapeRecords():
            rec = dict(zip(fields, sr.record, strict=True))
            if rec["STATEFP"] == "06" and rec["COUNTYFP"] in BAY_AREA:
                yield shape(sr.shape.__geo_interface__)


def build_land(counties_zip: Path, proj: Projection) -> dict:
    land = unary_union(list(_read_counties(counties_zip)))
    projected = transform(lambda lon, lat, z=None: proj(lon, lat), land)
    clipped = projected.intersection(box(*CLIP)).simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    polys = [clipped] if isinstance(clipped, Polygon) else list(getattr(clipped, "geoms", []))
    polys = [p for p in polys if isinstance(p, Polygon) and p.area >= MIN_AREA]
    polys.sort(key=lambda p: -p.area)

    def ring(coords) -> list[list[float]]:
        return [[round(x, 1), round(y, 1)] for x, y in list(coords)[:-1]]

    return {
        "version": 1,
        "source": "US Census Bureau, cb_2023_us_county_500k (public domain)",
        "clip": list(CLIP),
        "polygons": [[ring(p.exterior.coords), *[ring(h.coords) for h in p.interiors]] for p in polys],
    }


__all__ = ["COUNTIES_URL", "MultiPolygon", "build_land"]
