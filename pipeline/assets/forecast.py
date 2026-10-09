"""The weekly station forecast as a Dagster asset (ml/forecast does the work).

Reads marts.fct_station_daily, validates LightGBM against the seasonal-naive baseline, and writes
marts.forecast_station_daily + ml.forecast_runs: into the local DuckDB file in `local` mode, BigQuery in `gcp` mode.
"""

import os
from pathlib import Path

from dagster import AssetExecutionContext, AssetKey, MaterializeResult, MetadataValue, asset

from pipeline.resources import ROOT, Storage


@asset(
    group_name="ml",
    deps=[AssetKey(["marts", "fct_station_daily"])],
    description="14-day forecast of daily entries per station (LightGBM p10/p50/p90 plus a split-conformal "
    "calibrated band), validated walk-forward against a seasonal-naive baseline with bootstrap CIs; run log "
    "appended to ml.forecast_runs.",
)
def forecast_station_daily(context: AssetExecutionContext, storage: Storage) -> MaterializeResult:
    from ml.forecast import io, run

    gcp = storage.mode == "gcp"
    warehouse = "bigquery" if gcp else "duckdb"
    path = Path(os.environ.get("TP_DUCKDB_PATH", str(ROOT / "data" / "transitpulse.duckdb")))
    history = io.read_history(warehouse, duckdb_path=path, project=storage.gcp_project)
    # 6 test folds + 6 warm-up folds that calibrate the published band (about twice the fits of an uncalibrated run)
    forecast, run_log = run.run_forecast(history, folds=6, calib_folds=run.CALIB_FOLDS)
    io.write_outputs(warehouse, forecast, run_log, duckdb_path=path, project=storage.gcp_project)
    r = run_log.iloc[0]
    context.log.info(
        f"MAE {r['mae_lgbm']:.1f} vs baseline {r['mae_baseline']:.1f}; "
        f"improvement 95% CI [{r['mae_diff_lo']:.1f}, {r['mae_diff_hi']:.1f}]"
    )
    return MaterializeResult(
        metadata={
            "run_id": str(r["run_id"]),
            "data_through": str(r["data_through"]),
            "stations": int(r["n_stations"]),
            "mae_lgbm": MetadataValue.float(float(r["mae_lgbm"])),
            "mae_baseline": MetadataValue.float(float(r["mae_baseline"])),
            "mae_diff_ci": MetadataValue.json([float(r["mae_diff_lo"]), float(r["mae_diff_hi"])]),
            "coverage_p10_p90": MetadataValue.float(float(r["coverage_p10_p90"])),
            "coverage_calibrated": MetadataValue.float(float(r["coverage_calibrated"])),
            "conformal_q": MetadataValue.float(float(r["conformal_q"])),
        }
    )
