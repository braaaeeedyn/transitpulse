"""Local load test: start the API on a generated fixture warehouse, run Locust headless, report latency per endpoint.

    uv run --group load --group agent python load/run_local.py [--users N] [--seconds S] [--json] [--duckdb-path P]

Without --users it runs 1, 10 and 25 users in turn. The warehouse is the dbt fixture the tests use
(tests/dbt_fixture_data.py, built in a child `uv run --group dbt` process into a temp dir) unless --duckdb-path names
an existing DuckDB file. The agent runs with the fake LLM (TP_AGENT_LLM=fake: no model, no network) and the per-IP
rate limit lifted, because every simulated user comes from 127.0.0.1. These are local numbers on this machine, not
Cloud Run's.

Exits non-zero only if the server fails to start or any request fails.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
LOCUSTFILE = ROOT / "load" / "locustfile.py"
DEFAULT_USERS = (1, 10, 25)
ENDPOINTS = ("forecast", "kpis", "ask")

# The shared fixture's forecast run row only has what the agent tests need; give it every column a real weekly run
# writes (ml/forecast/io.py), so /api/forecast takes the same code path as production.
COMPLETE_FORECAST_RUN = """
alter table ml.forecast_runs add column if not exists mae_diff_lo double;
alter table ml.forecast_runs add column if not exists mae_diff_hi double;
alter table ml.forecast_runs add column if not exists coverage_p10_p90_lo double;
alter table ml.forecast_runs add column if not exists coverage_p10_p90_hi double;
alter table ml.forecast_runs add column if not exists coverage_calibrated_lo double;
alter table ml.forecast_runs add column if not exists coverage_calibrated_hi double;
alter table ml.forecast_runs add column if not exists interval_nominal double;
alter table ml.forecast_runs add column if not exists interval_method varchar;
alter table ml.forecast_runs add column if not exists calib_folds integer;
update ml.forecast_runs set mae_diff_lo = 4.0, mae_diff_hi = 11.0, coverage_p10_p90_lo = 0.69,
    coverage_p10_p90_hi = 0.73, coverage_calibrated_lo = 0.76, coverage_calibrated_hi = 0.80, interval_nominal = 0.8,
    interval_method = 'split-conformal CQR, rolling 6 folds', calib_folds = 6;
"""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def build_fixture(tmp: Path) -> Path:
    """The dbt fixture warehouse, built by a child process that has the dbt group (this one needn't)."""
    code = (
        "import sys, pathlib; from dbt_fixture_data import build_fixture_warehouse; "
        "build_fixture_warehouse(pathlib.Path(sys.argv[1]))"
    )
    cmd = ["uv", "run", "--inexact", "--group", "dbt", "python", "-c", code, str(tmp)]
    out = subprocess.run(cmd, cwd=ROOT / "tests", capture_output=True, text=True, timeout=900)
    if out.returncode:
        raise SystemExit(f"fixture warehouse build failed:\n{(out.stdout + out.stderr)[-3000:]}")
    db = tmp / "fixture.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute(COMPLETE_FORECAST_RUN)
    finally:
        con.close()
    return db


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(db: Path, port: int, log_file) -> subprocess.Popen:
    env = {
        **os.environ,
        "TP_WAREHOUSE": "duckdb",
        "TP_DUCKDB_PATH": str(db),
        "TP_AGENT_ENABLED": "true",
        "TP_AGENT_LLM": "fake",
        "TP_AGENT_RATE_PER_MIN": "1000000",  # one client IP for every simulated user
        "TP_TRUST_PROXY": "false",
    }
    cmd = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(port)]
    cmd += ["--no-access-log"]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"the API exited during startup (code {proc.returncode})")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as res:
                if res.status == 200:
                    return proc
        except OSError:
            time.sleep(0.3)
    stop_server(proc)
    raise SystemExit("the API didn't answer /healthz within 60 s")


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def run_locust(host: str, users: int, seconds: int, workdir: Path) -> dict:
    prefix = workdir / f"u{users}"
    cmd = [
        sys.executable, "-m", "locust", "-f", str(LOCUSTFILE), "--headless", "--host", host,
        "--users", str(users), "--spawn-rate", str(users), "--run-time", f"{seconds}s",
        "--csv", str(prefix), "--only-summary", "--loglevel", "WARNING", "--stop-timeout", "10",
    ]  # fmt: skip
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=seconds + 120)
    stats_file = Path(f"{prefix}_stats.csv")
    if not stats_file.exists():
        raise SystemExit(f"locust produced no stats (exit {out.returncode}):\n{out.stderr[-2000:]}")
    result: dict = {"users": users, "seconds": seconds, "endpoints": {}}
    with stats_file.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (
                row["Name"] if row["Name"] in ENDPOINTS else ("all" if row["Name"] == "Aggregated" else None)
            )
            if name is None:
                continue
            result["endpoints"][name] = {
                "requests": int(row["Request Count"]),
                "failures": int(row["Failure Count"]),
                "rps": round(float(row["Requests/s"]), 2),
                "p50_ms": _ms(row["50%"]),
                "p95_ms": _ms(row["95%"]),
                "p99_ms": _ms(row["99%"]),
                "max_ms": _ms(row["Max Response Time"]),
            }
    failures_file = Path(f"{prefix}_failures.csv")
    if failures_file.exists():
        with failures_file.open(newline="", encoding="utf-8") as f:
            result["failure_messages"] = [
                f"{r['Name']}: {r['Error'][:200]} (x{r['Occurrences']})" for r in csv.DictReader(f)
            ]
    return result


def _ms(value: str) -> float | None:
    return None if value in ("", "N/A") else round(float(value), 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--users", type=int, help="run only this many users (default: 1, 10 and 25 in turn)")
    ap.add_argument("--seconds", type=int, default=20, help="duration of each run (default 20)")
    ap.add_argument("--json", action="store_true", help="print the results as JSON on stdout")
    ap.add_argument("--duckdb-path", type=Path, help="use this warehouse instead of building the fixture")
    args = ap.parse_args(argv)
    user_counts = (args.users,) if args.users else DEFAULT_USERS

    with tempfile.TemporaryDirectory(prefix="tp-load-") as tmp_name:
        tmp = Path(tmp_name)
        if args.duckdb_path:
            db = args.duckdb_path.resolve()
        else:
            log("building the fixture warehouse (dbt) ...")
            t0 = time.monotonic()
            db = build_fixture(tmp / "fixture")
            log(f"  built in {time.monotonic() - t0:.0f} s")
        port = free_port()
        with (tmp / "server.log").open("w", encoding="utf-8") as server_log:
            proc = start_server(db, port, server_log)
            try:
                runs = []
                for users in user_counts:
                    log(f"locust: {users} user(s) for {args.seconds} s ...")
                    runs.append(run_locust(f"http://127.0.0.1:{port}", users, args.seconds, tmp))
            finally:
                stop_server(proc)
        server_output = (tmp / "server.log").read_text(encoding="utf-8", errors="replace")

    report = {
        "warehouse": "duckdb fixture" if not args.duckdb_path else str(args.duckdb_path),
        "llm": "fake",
        "runs": runs,
    }
    failed = sum(e["failures"] for r in runs for n, e in r["endpoints"].items() if n != "all")
    report["failures"] = failed
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in runs:
            print(f"{r['users']} user(s), {r['seconds']} s")
            for name in (*ENDPOINTS, "all"):
                e = r["endpoints"].get(name)
                if e:
                    print(
                        f"  {name:9} n={e['requests']:5} fail={e['failures']:3} rps={e['rps']:7} "
                        f"p50={e['p50_ms']} p95={e['p95_ms']} p99={e['p99_ms']} ms"
                    )
    if failed:
        for r in runs:
            for m in r.get("failure_messages", []):
                log(f"FAILED {m}")
        if "Traceback" in server_output:
            log(server_output[-3000:])
        return 1
    missing = sorted({n for r in runs for n in ENDPOINTS if not r["endpoints"].get(n, {}).get("requests")})
    if missing:
        log(f"warning: no requests recorded for {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
