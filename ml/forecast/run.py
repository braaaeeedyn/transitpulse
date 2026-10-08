"""Train, validate and publish the 14-day station forecast.

    uv run --group ml python -m ml.forecast.run [--warehouse duckdb|bigquery] [--duckdb-path PATH]
                                                [--horizon 14] [--folds 6] [--seed 0] [--train-days 730]

Steps: read marts.fct_station_daily → walk-forward validation (LightGBM quantiles vs seasonal naive, ≥ 6 folds)
→ paired bootstrap CIs over stations → refit on all data up to the last date → forecast the next `horizon` days
for every station → write marts.forecast_station_daily (replaced) and append a row to ml.forecast_runs.
The forecast starts the day after the last date in the data ("data through"), not today.
"""

import argparse
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ml.forecast import evaluate, features, io, model

ROOT = Path(__file__).resolve().parents[2]


def run_forecast(
    history: pd.DataFrame,
    *,
    horizon: int = 14,
    folds: int = 6,
    step: int = 14,
    train_days: int = 730,
    seed: int = 0,
    bootstrap: int = 1000,
    params: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (forecast rows, one-row run log)."""
    params = params or {}
    t0 = time.monotonic()
    started = datetime.now(UTC)
    panel = features.to_panel(history)
    last = panel.index.max()
    origins = evaluate.fold_origins(last, folds=folds, step=step, horizon=horizon)
    hol = features.us_holidays(panel.index.min(), last + pd.Timedelta(days=horizon + 1))
    rows = features.make_rows(
        panel, horizon, origin_start=origins[0] - pd.Timedelta(days=train_days), holidays_set=hol
    )

    test, fold_info = evaluate.walk_forward(rows, origins, train_days=train_days, seed=seed, **params)
    stats = evaluate.paired_bootstrap(test, b=bootstrap, seed=seed)

    train, _ = evaluate.fold_split(rows, last, train_days)
    final = model.QuantileForecaster(seed=seed, **params).fit(rows[train])
    future = features.make_rows(
        panel, horizon, origin_start=last, origin_end=last, holidays_set=hol, future=True
    )
    pred = final.predict(future)
    generated = datetime.now(UTC)
    run_id = f"fc-{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"

    forecast = pd.DataFrame(
        {
            "run_id": run_id,
            "generated_at": pd.Timestamp(generated),
            "station_code": future["station_code"].astype(str).to_numpy(),
            "forecast_date": pd.to_datetime(future["target_date"]).dt.date.to_numpy(),
            "horizon_day": future["horizon"].astype("int64").to_numpy(),
            "p10": pred["p10"].round(1).to_numpy(),
            "p50": pred["p50"].round(1).to_numpy(),
            "p90": pred["p90"].round(1).to_numpy(),
        }
    ).sort_values(["station_code", "forecast_date"], ignore_index=True)

    run = {
        "run_id": run_id,
        "started_at": pd.Timestamp(started),
        "generated_at": pd.Timestamp(generated),
        "data_through": last.date(),
        "forecast_start": (last + pd.Timedelta(days=1)).date(),
        "train_days": train_days,
        "train_start": pd.Timestamp(rows.loc[train, "target_date"].min()).date(),
        "folds": len(fold_info),
        "fold_step_days": step,
        "horizon": horizon,
        "n_stations": int(forecast["station_code"].nunique()),
        "n_test_rows": len(test),
        **{k: v for k, v in stats.items() if k != "n_stations"},
        "seed": seed,
        "params_json": json.dumps(
            {
                **model.DEFAULT_PARAMS,
                **params,
                "quantiles": list(model.QUANTILES),
                "features": features.FEATURES,
                "baseline": "seasonal naive (last same weekday at or before the origin)",
            }
        ),
        "fold_metrics_json": json.dumps(fold_info),
        "duration_sec": round(time.monotonic() - t0, 1),
    }
    return forecast, pd.DataFrame([run])


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--warehouse", choices=["duckdb", "bigquery"], default=None)
    ap.add_argument("--duckdb-path", type=Path, default=None)
    ap.add_argument("--project", default=os.environ.get("TP_GCP_PROJECT"))
    ap.add_argument("--horizon", type=int, default=14)
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--train-days", type=int, default=730)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument(
        "--n-estimators", type=int, default=None, help="override the model size (tests use a small one)"
    )
    ap.add_argument("--n-jobs", type=int, default=None, help="LightGBM threads (default 4)")
    args = ap.parse_args(argv)

    warehouse = args.warehouse or os.environ.get("TP_WAREHOUSE") or "duckdb"
    if warehouse not in ("duckdb", "bigquery"):
        warehouse = "duckdb"
    path = args.duckdb_path or Path(os.environ.get("TP_DUCKDB_PATH", "data/transitpulse.duckdb"))
    if not path.is_absolute():
        path = ROOT / path
    params = {"n_estimators": args.n_estimators} if args.n_estimators else {}
    if args.n_jobs:
        params["n_jobs"] = args.n_jobs

    history = io.read_history(warehouse, duckdb_path=path, project=args.project)
    forecast, run = run_forecast(
        history,
        horizon=args.horizon,
        folds=args.folds,
        train_days=args.train_days,
        seed=args.seed,
        bootstrap=args.bootstrap,
        params=params,
    )
    io.write_outputs(warehouse, forecast, run, duckdb_path=path, project=args.project)
    r = run.iloc[0].to_dict()
    print(
        f"run {r['run_id']}: data through {r['data_through']}, {r['folds']} folds, {r['n_stations']} stations\n"
        f"  LightGBM MAE {r['mae_lgbm']:.1f} [{r['mae_lgbm_lo']:.1f}, {r['mae_lgbm_hi']:.1f}]  "
        f"RMSE {r['rmse_lgbm']:.1f} [{r['rmse_lgbm_lo']:.1f}, {r['rmse_lgbm_hi']:.1f}]\n"
        f"  baseline MAE {r['mae_baseline']:.1f} [{r['mae_baseline_lo']:.1f}, {r['mae_baseline_hi']:.1f}]  "
        f"RMSE {r['rmse_baseline']:.1f} [{r['rmse_baseline_lo']:.1f}, {r['rmse_baseline_hi']:.1f}]\n"
        f"  MAE improvement {r['mae_diff']:.1f} [{r['mae_diff_lo']:.1f}, {r['mae_diff_hi']:.1f}]  "
        f"p10-p90 coverage {r['coverage_p10_p90']:.3f} [{r['coverage_p10_p90_lo']:.3f}, {r['coverage_p10_p90_hi']:.3f}]"
        f"  ({r['duration_sec']} s)",
        flush=True,
    )
    return r


if __name__ == "__main__":
    main()
