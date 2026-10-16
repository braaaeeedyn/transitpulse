"""docker-compose.yml (`make up`) read as YAML, without Docker: the services, their wiring, the read-only data mount,
a pinned Ollama image, the start order and the port. The running stack is tested in tests/compose (marker docker)."""

import os
import re
from pathlib import Path

import yaml

import tasks

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_services_and_a_pinned_ollama():
    assert set(SERVICES) == {"ollama", "ollama-pull", "api"}
    for name in ("ollama", "ollama-pull"):
        assert re.fullmatch(r"ollama/ollama:\d+\.\d+\.\d+", SERVICES[name]["image"]), (
            f"{name}: a pinned version"
        )
    ollama = SERVICES["ollama"]
    # a named volume unless TP_OLLAMA_DATA points at a host model directory
    assert ollama["volumes"] == ["${TP_OLLAMA_DATA:-ollama}:/root/.ollama"]
    assert "ollama" in COMPOSE["volumes"]
    assert ollama["healthcheck"]["test"] == ["CMD", "ollama", "list"]


def test_model_pull_runs_once_after_ollama_is_healthy():
    pull = SERVICES["ollama-pull"]
    assert pull["image"] == SERVICES["ollama"]["image"]
    assert pull["command"] == ["pull", "${TP_OLLAMA_MODEL:-llama3.1:8b}"]
    assert pull["environment"] == {"OLLAMA_HOST": "http://ollama:11434"}
    assert pull["depends_on"] == {"ollama": {"condition": "service_healthy"}}
    assert pull["restart"] == "no"


def test_api_wiring():
    api = SERVICES["api"]
    assert api["build"] == "."
    assert api["ports"] == ["${TP_PORT:-8000}:8080"]
    assert api["environment"] == {
        "TP_AGENT_ENABLED": "true",
        "TP_AGENT_LLM": "${TP_AGENT_LLM:-ollama}",
        "TP_OLLAMA_URL": "${TP_OLLAMA_URL:-http://ollama:11434}",
        "TP_OLLAMA_MODEL": "${TP_OLLAMA_MODEL:-llama3.1:8b}",
        "TP_WAREHOUSE": "${TP_WAREHOUSE:-none}",
        "TP_DUCKDB_PATH": "/app/data/transitpulse.duckdb",
    }
    assert api["volumes"] == ["./data:/app/data:ro"]  # the container can't change the warehouse
    assert api["depends_on"] == {"ollama-pull": {"condition": "service_completed_successfully"}}
    probe = api["healthcheck"]["test"]
    assert probe[:2] == ["CMD", "python"] and "/api/health" in probe[-1]  # the slim image has no curl


def test_up_task_uses_the_local_warehouse_like_api(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(tasks, "run", lambda *cmd: calls.append((cmd, os.environ.get("TP_WAREHOUSE"))))
    monkeypatch.setattr(tasks, "ROOT", tmp_path)
    for name in ("TP_WAREHOUSE", "TP_GCP_PROJECT"):
        monkeypatch.setenv(name, "x")  # recorded first, so the variables are restored afterwards
        monkeypatch.delenv(name)

    tasks.up()  # a fresh clone: no warehouse file
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "transitpulse.duckdb").touch()
    tasks.up()
    assert calls == [
        (("docker", "compose", "up", "--build"), None),
        (("docker", "compose", "up", "--build"), "duckdb"),
    ]
    assert re.search(r"^up: ; \$\(T\) up$", (ROOT / "Makefile").read_text(encoding="utf-8"), flags=re.M)
