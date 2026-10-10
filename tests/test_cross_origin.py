"""Pages on another domain (braedynthompson.com/transitpulse/) calling the API on Cloud Run: CORS and the export."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient

ORIGIN = "https://braedynthompson.com"


def _app(monkeypatch, cors: str | None):
    if cors is None:
        monkeypatch.delenv("TP_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("TP_CORS_ORIGINS", cors)
    monkeypatch.setenv("TP_WAREHOUSE", "none")
    from api import settings

    settings.get_settings.cache_clear()
    import api.main

    return TestClient(importlib.reload(api.main).app)


@pytest.fixture(autouse=True)
def _reset_settings():
    yield
    from api import settings

    settings.get_settings.cache_clear()


def test_allowed_origin_gets_cors_headers(monkeypatch):
    client = _app(
        monkeypatch, f"{ORIGIN}/"
    )  # a trailing slash in the setting still matches the browser's Origin
    res = client.get("/api/kpis", headers={"Origin": ORIGIN})
    assert res.status_code == 503  # no warehouse in this test; CORS still applies to the error
    assert res.headers["access-control-allow-origin"] == ORIGIN


def test_preflight_for_ask_post(monkeypatch):
    client = _app(monkeypatch, ORIGIN)
    res = client.options(
        "/api/ask",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == ORIGIN
    assert "POST" in res.headers["access-control-allow-methods"]


def test_other_origins_and_default_get_no_cors(monkeypatch):
    client = _app(monkeypatch, ORIGIN)
    res = client.get("/api/kpis", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers
    client = _app(monkeypatch, None)  # default: same-origin only
    res = client.get("/api/kpis", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in res.headers


def test_live_export_points_pages_at_the_api(tmp_path):
    from pipeline.webexport import export_live

    out = tmp_path / "transitpulse"
    info = export_live(out, "https://transitpulse-api-abc.a.run.app")
    html = (out / "index.html").read_text(encoding="utf-8")
    assert '<meta name="tp-api-base" content="https://transitpulse-api-abc.a.run.app/" />' in html
    assert 'name="tp-mode"' not in html  # live mode: the Ask box talks to the API
    assert not (out / "api").exists()  # no pre-computed responses
    assert (out / "data" / "network.json").exists() and (out / "js" / "util" / "api.js").exists()
    assert json.loads((out / "snapshot.json").read_text())["mode"] == info["mode"] == "live"


def test_live_export_requires_https(tmp_path):
    from pipeline.webexport import export_live

    with pytest.raises(SystemExit):
        export_live(tmp_path / "x", "http://insecure.example")


def test_cloud_run_terraform_allows_the_portfolio_origin():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "infra" / "terraform"
    assert 'TP_CORS_ORIGINS  = join(",", var.site_origins)' in (root / "cloudrun.tf").read_text()
    assert '"https://braedynthompson.com"' in (root / "variables.tf").read_text()


def test_health_route_reachable_on_run_app():
    """Google's front end answers *.run.app paths ending in "z" (e.g. /healthz) itself, so outside checks use
    /api/health; /healthz stays for probes that reach the container directly."""
    from pathlib import Path

    import api.main

    client = TestClient(api.main.app)
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/healthz").json() == {"ok": True}
    deploy = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml").read_text()
    assert '"$url/api/health"' in deploy and '"$url/healthz"' not in deploy
