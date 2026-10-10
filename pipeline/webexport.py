"""Export the website for hosting on another domain (the portfolio publishes it at braedynthompson.com/transitpulse/
through GitHub Pages, which only serves files). Two modes:

    # live: the pages call the API on Cloud Run (data + Ask TransitPulse)
    uv run python -m pipeline.webexport --api-base https://transitpulse-api-xxxx.a.run.app --to DIR

    # static snapshot: no server at all; every read-only API response is pre-computed
    uv run python -m pipeline.webexport [--warehouse bigquery|duckdb] --to DIR

Live mode copies web/ and adds <meta name="tp-api-base" content="URL"> to index.html; web/js/util/api.js sends every
`api/...` request there, and the API allows the pages' origin through CORS (TP_CORS_ORIGINS, set by Terraform).

Static mode calls the five GET endpoints the page reads (KPIs, ridership trend, bikes vs trains, and per-station
summaries and forecasts) through the real FastAPI app and saves them at the same relative paths without a file
extension (`api/kpis`, `api/forecast/EMBR`, ...), so `fetch("api/...")` works unchanged on a static host. index.html
gets <meta name="tp-mode" content="static">, which tells the Ask box there is no server. A 404 (e.g. a station
without a forecast) is left out, so the static host answers 404 too, as the API would.
"""

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
CHARSET = '<meta charset="utf-8" />'
STATIC_META = '<meta name="tp-mode" content="static" />'


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _copy_site(out: Path, meta: str) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB, out)
    index = out / "index.html"
    html = index.read_text(encoding="utf-8")
    if CHARSET not in html:
        raise SystemExit("web/index.html has no <meta charset>; can't add the export's meta tag")
    index.write_text(html.replace(CHARSET, f"{CHARSET}\n    {meta}", 1), encoding="utf-8", newline="\n")


def _write_info(out: Path, info: dict) -> dict:
    (out / "snapshot.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def export_live(out: Path, api_base: str) -> dict:
    """The pages only, pointed at the live API."""
    if not api_base.startswith("https://"):
        raise SystemExit("--api-base must be the https:// URL of the Cloud Run service")
    base = api_base.rstrip("/") + "/"
    _copy_site(out, f'<meta name="tp-api-base" content="{base}" />')
    return _write_info(out, {"generated_at": _now(), "mode": "live", "api_base": base})


def _client(warehouse: str):
    os.environ["TP_WAREHOUSE"] = warehouse
    os.environ["TP_AGENT_ENABLED"] = "false"
    from api.settings import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)


def _paths(network: dict) -> list[str]:
    codes = sorted(s["code"] for s in network["stations"])
    return [
        "api/kpis",
        "api/trends/ridership",
        "api/trends/bikes-vs-trains",
        *(f"api/stations/{c}/summary" for c in codes),
        *(f"api/forecast/{c}" for c in codes),
    ]


def export_static(out: Path, warehouse: str) -> dict:
    """The pages plus every read-only API response, pre-computed from the warehouse."""
    network = json.loads((WEB / "data" / "network.json").read_text(encoding="utf-8"))
    client = _client(warehouse)
    _copy_site(out, STATIC_META)

    written, missing = 0, []
    for path in _paths(network):
        res = client.get(f"/{path}", headers={"Accept": "application/json"})
        if res.status_code == 404:
            missing.append(path)
            continue
        if res.status_code != 200:
            raise SystemExit(f"{path}: HTTP {res.status_code} {res.text[:200]} (is the warehouse reachable?)")
        dest = out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(res.json(), separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written += 1

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return _write_info(
        out,
        {
            "generated_at": _now(),
            "mode": "static",
            "warehouse": warehouse,
            "commit": commit.stdout.strip() or None,
            "responses": written,
            "not_found": missing,
        },
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-base", help="Cloud Run URL: export the pages only, calling this live API")
    ap.add_argument(
        "--warehouse", choices=["bigquery", "duckdb"], default="bigquery", help="static mode only"
    )
    ap.add_argument("--to", type=Path, default=ROOT / "dist" / "transitpulse")
    args = ap.parse_args(argv)
    out = args.to.resolve()

    if args.api_base:
        info = export_live(out, args.api_base)
        print(f"exported the pages to {args.to}, calling the live API at {info['api_base']}")
        return

    if args.warehouse == "bigquery":
        os.environ.setdefault("TP_GCP_PROJECT", "transitpulse-511002")
    info = export_static(out, args.warehouse)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"exported {info['responses']} responses + the site to {args.to} ({size / 1e6:.1f} MB)")
    if info["not_found"]:
        print(f"  {len(info['not_found'])} paths had no data (404): {', '.join(info['not_found'][:6])} ...")


if __name__ == "__main__":
    main()
