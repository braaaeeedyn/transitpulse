"""Static checks on the Oracle VM deployment files (deploy/oracle/) and runbook (docs/ORACLE_VM.md).
Nothing here touches the VM; shellcheck runs separately (CI step / docker)."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "oracle"
UNITS = ["transitpulse-dagster-daemon.service", "transitpulse-dagster-web.service"]
LOCAL_KEY = "credentials/sa-pipeline-key.json"  # where docs/ORACLE_VM.md tells you to save the key


def parse_unit(path: Path) -> dict[str, list[tuple[str, str]]]:
    """systemd unit → {section: [(key, value), ...]} (keys may repeat, e.g. Environment=)."""
    sections: dict[str, list[tuple[str, str]]] = {}
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections[current] = []
            continue
        assert current is not None, f"{path.name}: key outside a section: {line}"
        key, sep, value = line.partition("=")
        assert sep, f"{path.name}: not key=value: {line}"
        sections[current].append((key.strip(), value.strip()))
    return sections


def values(section: list[tuple[str, str]], key: str) -> list[str]:
    return [v for k, v in section if k == key]


def test_units_are_well_formed():
    for name in UNITS:
        unit = parse_unit(DEPLOY / name)
        assert {"Unit", "Service", "Install"} <= set(unit), name
        svc = unit["Service"]
        (exec_start,) = values(svc, "ExecStart")
        assert exec_start.startswith("/opt/transitpulse/.venv/bin/"), name
        (user,) = values(svc, "User")
        assert user == "transitpulse" and user != "root", name
        assert values(svc, "EnvironmentFile") == ["/etc/transitpulse/transitpulse.env"], name
        assert values(svc, "WorkingDirectory") == ["/opt/transitpulse"], name
        assert values(svc, "Restart") == ["on-failure"], name
        # the venv must come first on PATH: SparkRunner runs plain `python`
        paths = [v for v in values(svc, "Environment") if v.startswith("PATH=")]
        assert paths and paths[0].startswith("PATH=/opt/transitpulse/.venv/bin:"), name
        assert values(svc, "MemoryMax") and values(svc, "Nice"), name
        assert "network-online.target" in " ".join(values(unit["Unit"], "After")), name
        assert "network-online.target" in " ".join(values(unit["Unit"], "Wants")), name
        assert values(unit["Install"], "WantedBy") == ["multi-user.target"], name
        assert "workspace.yaml" in exec_start

    daemon = parse_unit(DEPLOY / UNITS[0])["Service"]
    assert values(daemon, "ExecStart")[0].split()[0].endswith("/dagster-daemon")
    web = parse_unit(DEPLOY / UNITS[1])["Service"]
    (web_exec,) = values(web, "ExecStart")
    assert web_exec.split()[0].endswith("/dagster-webserver")
    assert re.search(r"(-h|--host) 127\.0\.0\.1\b", web_exec), "the UI must listen on localhost only"
    assert "0.0.0.0" not in (DEPLOY / UNITS[1]).read_text()
    assert "${TP_DAGSTER_PORT}" in web_exec

    workspace = (DEPLOY / "workspace.yaml").read_text()
    assert "module_name: pipeline.definitions" in workspace


def test_env_example_has_required_vars_and_no_secrets():
    text = (DEPLOY / "transitpulse.env.example").read_text(encoding="utf-8")
    env = {}
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, sep, value = line.partition("=")
            assert sep, line
            env[key.strip()] = value.strip()
    required = {
        "TP_PIPELINE_MODE",
        "TP_GCP_PROJECT",
        "TP_RAW_BUCKET",
        "DBT_TARGET",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "DAGSTER_HOME",
        "TP_SPARK_RUNNER",
        "JAVA_HOME",
        "TP_DAGSTER_PORT",
        "TP_DUCKDB_PATH",
        "TP_DATA_ROOT",
    }
    assert required <= set(env)
    assert (
        env["TP_PIPELINE_MODE"] == "gcp" and env["DBT_TARGET"] == "dev" and env["TP_SPARK_RUNNER"] == "python"
    )
    assert (
        env["GOOGLE_APPLICATION_CREDENTIALS"] == "/etc/transitpulse/sa-pipeline-key.json"
    )  # a path, not a key
    assert env["TP_DAGSTER_PORT"].isdigit()
    lowered = text.lower()
    for marker in ("private_key", "begin private key", "client_secret", "password", "api_key", "token="):
        assert marker not in lowered, marker
    for value in env.values():
        assert not re.fullmatch(r"[A-Za-z0-9+/=_-]{40,}", value), "looks like a secret"


def test_bootstrap_script_is_strict_and_protects_the_key():
    script = (DEPLOY / "bootstrap.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash\n")
    assert "\r" not in script  # LF line endings, or bash on the VM chokes
    assert re.search(r"^set -euo pipefail$", script, flags=re.M)
    assert "chmod 600" in script
    assert "uname -m" in script and "aarch64" in script
    assert "apt-get install" in script and "dnf install" in script
    assert "java-17-openjdk-headless" in script and "openjdk-17-jre-headless" in script
    assert "dbt parse" in script
    assert "sync --frozen" in script
    assert "--group pipeline --group dbt --group ml --group spark" in script
    assert "pipeline/dagster.yaml" in script
    assert "daemon-reload" in script and "systemctl enable" in script
    # the env file is only created when absent, never overwritten
    assert re.search(r'if \[\[ ! -f "\$ENV_FILE" \]\]', script)
    # the key is checked (mode 600, owner) and services don't start without it; its contents are never printed
    assert "stat -c '%a'" in script and "stat -c '%U'" in script
    assert re.search(r'key_ok" != true', script) and "die " in script
    assert not re.search(r"\b(cat|less|more|head|tail)\b[^\n]*(key_path|KEY_FILE)", script)
    assert "0.0.0.0" not in script


def test_key_path_is_gitignored():
    res = subprocess.run(["git", "check-ignore", "-q", LOCAL_KEY], cwd=ROOT, check=False)
    assert res.returncode == 0, f"{LOCAL_KEY} is not ignored by git"
    assert LOCAL_KEY in (ROOT / "docs" / "ORACLE_VM.md").read_text(encoding="utf-8")


def test_runbook_covers_required_sections():
    text = (ROOT / "docs" / "ORACLE_VM.md").read_text(encoding="utf-8")
    headings = [h.lower() for h in re.findall(r"^#+ (.+)$", text, flags=re.M)]
    for needed in (
        "prerequisites",
        "key",
        "scp",
        "bootstrap",
        "ssh tunnel",
        "first backfill",
        "verify",
        "update",
        "uninstall",
        "troubleshooting",
    ):
        assert any(needed in h for h in headings), needed
    for fact in (
        "free -h",
        "df -h",
        "seismicsocal",
        "systemctl status",
        "journalctl -u",
        "ssh -N -L",
        "aarch64",
    ):
        assert fact in text.lower() or fact in text, fact
    assert "second VM" in text  # states that no second VM is assumed
