"""GET /api/findings (api/routes/findings.py): the eBART study's committed results, served without a warehouse."""

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pipeline import webexport

ROOT = Path(__file__).resolve().parents[1]
FINDINGS = ROOT / "api" / "data" / "findings.json"
ORIGIN = "https://braedynthompson.com"


@pytest.fixture(autouse=True)
def _reset():
    yield
    from api import settings
    from api.routes import findings

    settings.get_settings.cache_clear()
    findings._load.cache_clear()


def _client(monkeypatch, path: Path | None = None, cors: str | None = None) -> TestClient:
    monkeypatch.setenv("TP_WAREHOUSE", "none")
    if path is None:
        monkeypatch.delenv("TP_FINDINGS_PATH", raising=False)
    else:
        monkeypatch.setenv("TP_FINDINGS_PATH", str(path))
    if cors is None:
        monkeypatch.delenv("TP_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("TP_CORS_ORIGINS", cors)
    from api import settings
    from api.routes import findings

    settings.get_settings.cache_clear()
    findings._load.cache_clear()
    import api.main

    return TestClient(importlib.reload(api.main).app)


def test_findings_answers_without_a_warehouse(monkeypatch):
    res = _client(monkeypatch).get("/api/findings")
    assert res.status_code == 200
    assert res.json()["verdict"] in {"new", "moved", "fewer", "inconclusive"}


def test_findings_body_equals_the_committed_file(monkeypatch):
    res = _client(monkeypatch).get("/api/findings")
    assert res.json() == json.loads(FINDINGS.read_text(encoding="utf-8"))
    assert res.headers["content-type"].startswith("application/json")


def test_findings_cache_header(monkeypatch):
    res = _client(monkeypatch).get("/api/findings")
    assert res.headers["cache-control"] == "public, max-age=86400"


def test_findings_path_setting_and_shape(monkeypatch, tmp_path):
    doc = {"verdict": "inconclusive", "caution": True, "preregistration": {"sha256": "x", "amendments": []}}
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert _client(monkeypatch, path).get("/api/findings").json() == doc


@pytest.mark.parametrize("content", [None, "not json", "[1, 2]"])
def test_findings_missing_or_invalid_file_is_404(monkeypatch, tmp_path, content):
    path = tmp_path / "findings.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    res = _client(monkeypatch, path).get("/api/findings")
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "findings_not_available"


def test_findings_cors_from_braedynthompson_com(monkeypatch):
    res = _client(monkeypatch, cors=ORIGIN).get("/api/findings", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == ORIGIN


def test_findings_in_static_export_paths():
    paths = webexport._paths({"stations": [{"code": "EMBR"}]})
    assert "api/findings" in paths


def test_findings_committed_file_has_the_preregistration_trail():
    doc = json.loads(FINDINGS.read_text(encoding="utf-8"))
    pre = doc["preregistration"]
    assert pre["sha256"] == "a05df98504818ffd4ea5fb69c720cea37eff76dd55859941acc3ce23d56e40f4"
    assert [a["sha256"] for a in pre["amendments"]] == [
        "96395c97868f556d756415bef915f4fde13d971b5fb7b7cdb95505f876f36061"
    ]
