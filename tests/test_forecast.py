"""Forecasting (ml/forecast): leakage-free features, the baseline, walk-forward folds, bootstrap CIs, quantile
ordering, and an end-to-end run that writes both output tables into a temporary DuckDB warehouse."""

import itertools
import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from ml.forecast import evaluate, features, model, run

STATIONS = {"AAAA": 9000, "BBBB": 3000, "CCCC": 600, "DDDD": 15000}
WEEKLY = [0.35, 1.0, 1.08, 1.1, 1.05, 0.9, 0.5]  # Mon..Sun


def synthetic_history(days: int = 300, start: str = "2025-01-01", seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=days, freq="D")
    rows = []
    for code, base in STATIONS.items():
        trend = np.linspace(0.95, 1.05, days)
        noise = rng.normal(1, 0.05, days)
        weekly = np.array([WEEKLY[d.dayofweek] for d in dates])
        entries = np.round(base * trend * weekly * noise).astype(int)
        rows.append(pd.DataFrame({"trip_date": dates.date, "station_code": code, "entries": entries}))
    return pd.concat(rows, ignore_index=True)


@pytest.fixture(scope="module")
def panel():
    return features.to_panel(synthetic_history())


def test_features_use_only_data_up_to_origin(panel):
    origin = panel.index[150]
    cols = [*features.FEATURES, "level", "naive"]
    before = features.make_rows(panel, 14, origin, origin, holidays_set=set(), future=True)
    assert len(before) == len(STATIONS) * 14

    # wreck everything after the origin: the features must not change (only the targets do)
    future_changed = panel.copy()
    future_changed.loc[future_changed.index > origin] = 1e9
    after = features.make_rows(future_changed, 14, origin, origin, holidays_set=set(), future=True)
    pd.testing.assert_frame_equal(before[cols], after[cols])
    assert (after["y"] == 1e9).all()

    # a missing day inside the 28-day window drops that station's rows (no bridging)
    gap = panel.copy()
    gap.loc[origin - pd.Timedelta(days=5), "AAAA"] = np.nan
    rows = features.make_rows(gap, 14, origin, origin, holidays_set=set(), future=True)
    assert "AAAA" not in set(rows["station_code"])
    assert len(rows) == (len(STATIONS) - 1) * 14


def test_seasonal_naive_repeats_last_same_weekday(panel):
    origin = panel.index[120]
    rows = features.make_rows(panel, 14, origin, origin, holidays_set=set())
    for r in rows.itertuples():
        target = pd.Timestamp(r.target_date)
        ref = max(d for d in panel.index if d <= origin and d.dayofweek == target.dayofweek)
        assert (origin - ref).days <= 6
        assert r.naive == panel.loc[ref, r.station_code]
    base = model.seasonal_naive(rows)
    seven = rows[rows["horizon"] == 7]  # a week ahead: the origin day itself
    assert np.array_equal(seven["naive"].to_numpy(), panel.loc[origin, seven["station_code"]].to_numpy())
    assert np.array_equal(base, rows["naive"].to_numpy())


def test_walk_forward_folds_never_train_on_test_dates(panel):
    last = panel.index.max()
    origins = evaluate.fold_origins(last, folds=6, step=14, horizon=14)
    assert len(origins) == 6
    assert origins[-1] == last - pd.Timedelta(days=14)
    assert all((b - a).days == 14 for a, b in itertools.pairwise(origins))
    rows = features.make_rows(panel, 14, holidays_set=set())
    for origin in origins:
        train, test = evaluate.fold_split(rows, origin, train_days=730)
        assert train.any() and test.sum() == len(STATIONS) * 14
        assert rows.loc[train, "target_date"].max() <= origin
        assert rows.loc[test, "target_date"].min() > origin
        assert rows.loc[test, "target_date"].max() <= last
        assert not (train & test).any()
    # a short training window only reaches back that far
    train, _ = evaluate.fold_split(rows, origins[0], train_days=30)
    assert rows.loc[train, "origin"].min() >= origins[0] - pd.Timedelta(days=30)

    preds, folds = evaluate.walk_forward(rows, origins, train_days=730, seed=0, n_estimators=20, n_jobs=1)
    assert len(folds) == 6
    for f in folds:
        fold_rows = preds[preds["fold"] == f["fold"]]
        assert (fold_rows["target_date"] > pd.Timestamp(f["origin"])).all()


def test_bootstrap_ci_is_deterministic_and_brackets_estimate():
    rng = np.random.default_rng(3)
    n = 2000
    y = rng.uniform(100, 5000, n)
    df = pd.DataFrame(
        {
            "station_code": rng.choice([f"S{i:03d}" for i in range(40)], n),
            "y": y,
            "p50": y + rng.normal(0, 100, n),
            "baseline": y + rng.normal(0, 200, n),
        }
    )
    df["p10"] = df["p50"] - 150
    df["p90"] = df["p50"] + 150
    a = evaluate.paired_bootstrap(df, b=1000, seed=7)
    b = evaluate.paired_bootstrap(df, b=1000, seed=7)
    assert a == b
    for k in ("mae_lgbm", "rmse_lgbm", "mae_baseline", "rmse_baseline", "mae_diff", "coverage_p10_p90"):
        assert a[f"{k}_lo"] <= a[k] <= a[f"{k}_hi"], k
    assert a["mae_diff"] == pytest.approx(a["mae_baseline"] - a["mae_lgbm"])
    assert a["mae_diff_lo"] > 0  # the baseline here is twice as noisy
    assert a["n_stations"] == 40 and a["bootstrap_b"] == 1000
    assert evaluate.paired_bootstrap(df, b=1000, seed=8)["mae_diff_lo"] != a["mae_diff_lo"]


def test_quantiles_ordered_and_non_negative(panel):
    fixed = model.order_quantiles(np.array([[5.0, 3.0, -1.0], [1.0, 2.0, 3.0], [-4.0, -2.0, -3.0]]))
    assert fixed.tolist() == [[0.0, 3.0, 5.0], [1.0, 2.0, 3.0], [0.0, 0.0, 0.0]]

    rows = features.make_rows(panel, 14, holidays_set=set())
    last = panel.index.max()
    train, _ = evaluate.fold_split(rows, last, 730)
    fc = model.QuantileForecaster(seed=0, n_estimators=30, n_jobs=1).fit(rows[train])
    future = features.make_rows(panel, 14, last, last, holidays_set=set(), future=True)
    pred = fc.predict(future)
    assert len(pred) == len(STATIONS) * 14
    assert (pred["p10"] >= 0).all()
    assert (pred["p10"] <= pred["p50"]).all() and (pred["p50"] <= pred["p90"]).all()
    again = model.QuantileForecaster(seed=0, n_estimators=30, n_jobs=1).fit(rows[train]).predict(future)
    pd.testing.assert_frame_equal(pred, again)  # deterministic


def test_run_writes_tables_to_duckdb(tmp_path):
    db = tmp_path / "wh.duckdb"
    history = synthetic_history()
    con = duckdb.connect(str(db))
    con.execute("create schema marts")
    con.register("h", history)
    con.execute(
        "create table marts.fct_station_daily as select cast(trip_date as date) as trip_date, * exclude (trip_date) from h"
    )
    con.close()
    args = [
        "--warehouse",
        "duckdb",
        "--duckdb-path",
        str(db),
        "--bootstrap",
        "200",
        "--n-estimators",
        "30",
        "--n-jobs",
        "1",
    ]

    first = run.main(args)
    last = max(history["trip_date"])
    con = duckdb.connect(str(db), read_only=True)
    try:
        fc = con.execute(
            "select station_code, count(*), min(forecast_date), max(forecast_date), min(horizon_day), max(horizon_day) "
            "from marts.forecast_station_daily group by 1 order by 1"
        ).fetchall()
        assert [r[0] for r in fc] == sorted(STATIONS)
        for _, n, d0, d1, h0, h1 in fc:
            assert (n, h0, h1) == (14, 1, 14)
            assert d0 == last + pd.Timedelta(days=1).to_pytimedelta()
            assert d1 == last + pd.Timedelta(days=14).to_pytimedelta()
        bad = con.execute(
            "select count(*) from marts.forecast_station_daily where not (0 <= p10 and p10 <= p50 and p50 <= p90)"
        ).fetchone()[0]
        assert bad == 0
        runs = con.execute(
            "select run_id, data_through, folds, horizon, n_stations, mae_lgbm, mae_lgbm_lo, mae_lgbm_hi, "
            "mae_baseline, mae_diff, mae_diff_lo, mae_diff_hi, coverage_p10_p90, bootstrap_b, params_json "
            "from ml.forecast_runs"
        ).fetchall()
        assert len(runs) == 1
        r = runs[0]
        assert r[0] == first["run_id"] and r[1] == last and r[2] >= 6 and r[3] == 14 and r[4] == len(STATIONS)
        assert r[6] <= r[5] <= r[7] and r[10] <= r[9] <= r[11]
        assert 0 <= r[12] <= 1 and r[13] == 200
        assert '"n_estimators": 30' in r[14]
    finally:
        con.close()

    second = run.main(args)  # the forecast table is replaced, the run log appended
    con = duckdb.connect(str(db), read_only=True)
    try:
        assert (
            con.execute("select count(*) from marts.forecast_station_daily").fetchone()[0]
            == len(STATIONS) * 14
        )
        assert {
            r[0] for r in con.execute("select distinct run_id from marts.forecast_station_daily").fetchall()
        } == {second["run_id"]}
        assert con.execute("select count(*) from ml.forecast_runs").fetchone()[0] == 2
    finally:
        con.close()


# --- interval calibration (rolling split-conformal on CQR scores) ----------------------------------------------


def test_conformal_quantile_is_finite_sample_corrected():
    scores = np.arange(1.0, 11.0)  # 1..10
    # rank ceil((10 + 1) * 0.8) = 9, not the plain 80th percentile (8.2)
    assert evaluate.conformal_quantile(scores, 0.8) == 9.0
    assert evaluate.conformal_quantile(scores[::-1], 0.8) == 9.0  # order doesn't matter
    assert evaluate.conformal_quantile(np.arange(1.0, 5.0), 0.8) == 4.0  # ceil(5 * 0.8) = 4 = n
    assert evaluate.conformal_quantile([1.0, 2.0, 3.0], 0.8) == float("inf")  # too few scores to promise 80%
    assert evaluate.conformal_quantile([-0.5, -0.2, -0.1, -0.3, -0.4], 0.5) == -0.3  # narrowing is allowed

    rows = pd.DataFrame({"y": [100.0, 50.0, 300.0], "p10": [80.0, 60.0, 100.0], "p90": [120.0, 90.0, 200.0],
                         "level": [100.0, 100.0, 50.0]})  # fmt: skip
    # inside the band: minus the distance to the nearer edge; outside: how far out; both in units of level
    assert evaluate.conformal_scores(rows).tolist() == pytest.approx([-0.2, 0.1, 2.0])


def _fold_preds(n_folds: int, step: int = 14, horizon: int = 14, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    start = pd.Timestamp("2025-01-01")
    for f in range(n_folds):
        origin = start + pd.Timedelta(days=step * f)
        for st in ("AAAA", "BBBB"):
            for h in range(1, horizon + 1):
                y = 1000 * rng.uniform(0.6, 1.4)
                out.append({"station_code": st, "origin": origin, "target_date": origin + pd.Timedelta(days=h),
                            "horizon": h, "y": y, "level": 1000.0, "baseline": 1000.0, "p10": 900.0,
                            "p50": 1000.0, "p90": 1100.0, "fold": f})  # fmt: skip
    return pd.DataFrame(out)


def test_conformal_scores_use_only_earlier_folds():
    preds = _fold_preds(5)
    test, qs = evaluate.calibrate(preds, calib_folds=2)
    assert sorted(test["fold"].unique()) == [0, 1, 2]  # folds 2..4 are the test folds, renumbered
    for i, f in enumerate((2, 3, 4)):
        expected = evaluate.conformal_quantile(
            evaluate.conformal_scores(preds[preds["fold"].isin([f - 2, f - 1])]), 0.8
        )
        assert qs[i] == pytest.approx(expected)
        part = test[test["fold"] == i]
        assert np.allclose(part["upper"], part["p90"] + expected * part["level"])
        assert (part["lower"] >= 0).all() and (part["lower"] <= part["p50"]).all()
        assert (part["upper"] >= part["p50"]).all()

    # changing a test fold's actuals changes nothing for itself or any earlier fold
    wrecked = preds.copy()
    wrecked.loc[wrecked["fold"] == 4, "y"] = 1e9
    _, qs2 = evaluate.calibrate(wrecked, calib_folds=2)
    assert qs2 == qs
    # ...but it moves the published forecast's q, which uses the last calib_folds folds
    assert evaluate.final_conformal_q(wrecked, 2) > evaluate.final_conformal_q(preds, 2)

    # overlapping folds (step < horizon) would leak a test fold's own days into its calibration: refused
    with pytest.raises(AssertionError):
        evaluate.calibrate(_fold_preds(4, step=7), calib_folds=2)

    # calib_folds = 0: the band is the raw p10-p90
    raw, qs0 = evaluate.calibrate(preds, calib_folds=0)
    assert set(qs0.values()) == {0.0}
    assert np.allclose(raw["lower"], raw["p10"]) and np.allclose(raw["upper"], raw["p90"])


def test_calibration_keeps_p50_and_mae():
    history = synthetic_history()
    small = {"n_estimators": 30, "n_jobs": 1}
    fc0, run0 = run.run_forecast(history, calib_folds=0, bootstrap=200, params=small)
    fc6, run6 = run.run_forecast(history, calib_folds=6, bootstrap=200, params=small)
    r0, r6 = run0.iloc[0], run6.iloc[0]
    # the same six test folds and the same p50, so the point metrics and their CIs don't move
    f0 = [(f["origin"], f["mae_lgbm"]) for f in json.loads(r0["fold_metrics_json"])]
    f6 = [(f["origin"], f["mae_lgbm"]) for f in json.loads(r6["fold_metrics_json"])]
    assert f0 == f6 and len(f6) == 6
    for k in (
        "mae_lgbm",
        "mae_lgbm_lo",
        "mae_lgbm_hi",
        "rmse_lgbm",
        "mae_baseline",
        "mae_diff",
        "coverage_p10_p90",
    ):
        assert r6[k] == pytest.approx(r0[k], abs=1e-6), k
    pd.testing.assert_series_equal(fc0["p50"], fc6["p50"])
    pd.testing.assert_series_equal(fc0["p10"], fc6["p10"])
    # without calibration the published band is the raw one
    assert r0["calib_folds"] == 0 and r0["conformal_q"] == 0.0
    assert r0["coverage_calibrated"] == pytest.approx(r0["coverage_p10_p90"])
    assert np.allclose(fc0["upper"], fc0["p90"], atol=0.051)
    assert r6["calib_folds"] == 6 and r6["interval_nominal"] == 0.8
    assert "conformal" in r6["interval_method"]


def test_run_writes_calibrated_band_and_run_columns(tmp_path):
    db = tmp_path / "wh.duckdb"
    history = synthetic_history()
    con = duckdb.connect(str(db))
    con.execute("create schema marts")
    con.register("h", history)
    con.execute(
        "create table marts.fct_station_daily as select cast(trip_date as date) as trip_date, * exclude (trip_date) from h"
    )
    con.close()
    args = ["--warehouse", "duckdb", "--duckdb-path", str(db), "--bootstrap", "200", "--n-estimators", "30",
            "--n-jobs", "1", "--calib-folds", "6"]  # fmt: skip
    first = run.main(args)
    cols = [
        "coverage_calibrated",
        "coverage_calibrated_lo",
        "coverage_calibrated_hi",
        "interval_nominal",
        "interval_method",
        "conformal_q",
        "calib_folds",
        "mean_width_raw",
        "mean_width_calibrated",
        "fold_metrics_json",
    ]
    con = duckdb.connect(str(db), read_only=True)
    try:
        bad = con.execute(
            "select count(*) from marts.forecast_station_daily "
            "where not (0 <= lower and lower <= p50 and p50 <= upper) or lower is null or upper is null"
        ).fetchone()[0]
        assert bad == 0
        n = con.execute("select count(*) from marts.forecast_station_daily").fetchone()[0]
        assert n == len(STATIONS) * 14
        row = con.execute(
            f"select {', '.join(cols)} from ml.forecast_runs where run_id = ?", [first["run_id"]]
        )
        r = dict(zip(cols, row.fetchone(), strict=True))
    finally:
        con.close()
    assert all(v is not None for v in r.values()), r
    assert r["coverage_calibrated_lo"] <= r["coverage_calibrated"] <= r["coverage_calibrated_hi"]
    assert 0 <= r["coverage_calibrated"] <= 1
    assert r["interval_nominal"] == 0.8 and r["calib_folds"] == 6
    assert r["mean_width_raw"] > 0 and r["mean_width_calibrated"] >= 0
    folds = json.loads(r["fold_metrics_json"])
    assert len(folds) == 6 and [f["fold"] for f in folds] == list(range(6))
    assert all("coverage_calibrated" in f and "conformal_q" in f for f in folds)


RUN_V1 = {
    "run_id": "fc-old",
    "generated_at": pd.Timestamp("2026-01-01 00:00", tz="UTC"),
    "mae_lgbm": 300.0,
    "coverage_p10_p90": 0.7,
}


def _forecast_rows(run_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"run_id": [run_id], "station_code": ["EMBR"], "forecast_date": [pd.Timestamp("2026-01-01").date()],
         "p10": [1.0], "p50": [2.0], "p90": [3.0], "lower": [0.5], "upper": [3.5]}
    )  # fmt: skip


def test_forecast_runs_schema_evolves_duckdb(tmp_path):
    from ml.forecast import io

    db = tmp_path / "wh.duckdb"
    io.write_outputs("duckdb", _forecast_rows("fc-old"), pd.DataFrame([RUN_V1]), duckdb_path=db)
    v2 = {**RUN_V1, "run_id": "fc-new", "coverage_calibrated": 0.79, "interval_method": "split-conformal"}
    io.write_outputs("duckdb", _forecast_rows("fc-new"), pd.DataFrame([v2]), duckdb_path=db)
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "select run_id, mae_lgbm, coverage_calibrated, interval_method from ml.forecast_runs order by run_id"
        ).fetchall()
    finally:
        con.close()
    assert rows == [("fc-new", 300.0, 0.79, "split-conformal"), ("fc-old", 300.0, None, None)]


def test_bigquery_append_allows_field_addition(monkeypatch):
    from google.cloud import bigquery

    from ml.forecast import io

    calls = []

    class FakeJob:
        def result(self):
            return None

    class FakeClient:
        def __init__(self, project=None, location=None):
            self.project = project

        def load_table_from_dataframe(self, df, table, job_config=None):
            calls.append((table, list(df.columns), job_config))
            return FakeJob()

    monkeypatch.setattr(bigquery, "Client", FakeClient)
    v2 = {**RUN_V1, "coverage_calibrated": 0.79}
    io.write_outputs("bigquery", _forecast_rows("fc-new"), pd.DataFrame([v2]), project="proj")
    by_table = {t: (cols, cfg) for t, cols, cfg in calls}
    cols, cfg = by_table["proj.ml.forecast_runs"]
    assert "coverage_calibrated" in cols
    assert cfg.write_disposition == "WRITE_APPEND"
    assert cfg.schema_update_options == [bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]
    cols, cfg = by_table["proj.marts.forecast_station_daily"]
    assert {"lower", "upper"} <= set(cols) and cfg.write_disposition == "WRITE_TRUNCATE"
