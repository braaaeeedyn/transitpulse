"""Walk-forward validation and paired bootstrap confidence intervals.

Each fold has a forecast origin; the model is trained only on rows whose *target* date is at or before the origin
(and whose origin lies inside the training window), then scored on the 14 days after the origin. Errors are pooled
over folds, stations and horizons. Uncertainty comes from a paired bootstrap over stations: resample stations with
replacement and recompute every metric on the same resample for both models, so the CI for the difference accounts
for the two models being scored on the same days.

Interval calibration (rolling split-conformal on conformalized-quantile-regression scores): the walk-forward runs
`calib_folds` extra origins *before* the test folds. Each test fold widens (or narrows) the raw p10-p90 band by the
finite-sample 80% quantile of the scores from the `calib_folds` folds just before it, all of whose targets are at
or before that fold's origin. A test fold never calibrates its own band, and p50 is untouched, so MAE/RMSE are the
same as without calibration.
"""

import math

import numpy as np
import pandas as pd

from ml.forecast.model import QuantileForecaster, seasonal_naive


def fold_origins(last_date, folds: int = 6, step: int = 14, horizon: int = 14) -> list[pd.Timestamp]:
    """Fold origins every `step` days, the latest being the last date with `horizon` days of actuals after it."""
    last = pd.Timestamp(last_date) - pd.Timedelta(days=horizon)
    return [last - pd.Timedelta(days=step * i) for i in range(folds)][::-1]


def fold_split(rows: pd.DataFrame, origin, train_days: int) -> tuple[pd.Series, pd.Series]:
    """Boolean masks (train, test) for one fold. Training never sees a target dated after the origin."""
    origin = pd.Timestamp(origin)
    train = (rows["target_date"] <= origin) & (rows["origin"] >= origin - pd.Timedelta(days=train_days))
    test = rows["origin"] == origin
    return train, test


def walk_forward(
    rows: pd.DataFrame, origins: list, train_days: int = 730, seed: int = 0, **params
) -> tuple[pd.DataFrame, list[dict]]:
    """Fit and score one model per fold. Returns the pooled test predictions and per-fold metrics."""
    results = []
    folds = []
    for i, origin in enumerate(origins):
        train, test = fold_split(rows, origin, train_days)
        if not test.any():
            continue
        model = QuantileForecaster(seed=seed, **params).fit(rows[train])
        test_rows = rows[test]
        pred = model.predict(test_rows)
        out = test_rows[["station_code", "origin", "target_date", "horizon", "y", "level"]].copy()
        out["baseline"] = seasonal_naive(test_rows)
        out[["p10", "p50", "p90"]] = pred.to_numpy()
        out["fold"] = i
        results.append(out)
        folds.append(
            {
                "fold": i,
                "origin": str(pd.Timestamp(origin).date()),
                "train_rows": int(train.sum()),
                "train_from": str(pd.Timestamp(rows.loc[train, "target_date"].min()).date()),
                "test_rows": int(test.sum()),
                **{k: round(v, 3) for k, v in metrics(out).items()},
            }
        )
    return pd.concat(results, ignore_index=True), folds


def conformal_scores(df: pd.DataFrame) -> np.ndarray:
    """CQR nonconformity score per row, in units of the station's level: how far the actual fell outside the raw
    p10-p90 band (negative when inside)."""
    lvl = df["level"].to_numpy(dtype="float64")
    y = df["y"].to_numpy(dtype="float64")
    return np.maximum(df["p10"].to_numpy() - y, y - df["p90"].to_numpy()) / lvl


def conformal_quantile(scores, coverage: float = 0.8) -> float:
    """The finite-sample-corrected quantile: the ceil((n + 1) * coverage)-th smallest score (inf if that rank
    exceeds n, i.e. too few scores to promise the coverage)."""
    s = np.sort(np.asarray(scores, dtype="float64"))
    n = len(s)
    k = math.ceil((n + 1) * coverage - 1e-9)
    if n == 0 or k > n:
        return math.inf
    return float(s[k - 1])


def apply_band(df: pd.DataFrame, q) -> tuple[np.ndarray, np.ndarray]:
    """The published band: p10/p90 moved out (q > 0) or in (q < 0) by q x level, kept non-negative and around p50."""
    q = np.broadcast_to(np.asarray(q, dtype="float64"), len(df))
    lvl = df["level"].to_numpy(dtype="float64")
    p50 = df["p50"].to_numpy(dtype="float64")
    lower = np.minimum(np.maximum(df["p10"].to_numpy() - q * lvl, 0.0), p50)
    upper = np.maximum(df["p90"].to_numpy() + q * lvl, p50)
    return lower, upper


def calibrate(preds: pd.DataFrame, calib_folds: int, coverage: float = 0.8) -> tuple[pd.DataFrame, dict]:
    """Add `lower`/`upper` to the walk-forward predictions of the test folds (fold >= calib_folds).

    Test fold i uses the scores of folds i - calib_folds .. i - 1 only. Returns the test-fold rows (folds
    renumbered from 0) and {test fold: q}. With calib_folds = 0 the band is the raw p10-p90."""
    folds = sorted(preds["fold"].unique())
    test_ids = [f for f in folds if f >= calib_folds]
    out = []
    qs = {}
    for f in test_ids:
        rows = preds[preds["fold"] == f].copy()
        if calib_folds:
            calib = preds[(preds["fold"] >= f - calib_folds) & (preds["fold"] < f)]
            origin = rows["origin"].iloc[0]
            # no peeking: every calibration target is at or before this fold's origin
            assert calib.empty or calib["target_date"].max() <= origin, (
                f,
                calib["target_date"].max(),
                origin,
            )
            q = conformal_quantile(conformal_scores(calib), coverage) if not calib.empty else 0.0
        else:
            q = 0.0
        rows["lower"], rows["upper"] = apply_band(rows, q)
        rows["fold"] = f - calib_folds
        qs[int(f - calib_folds)] = q
        out.append(rows)
    return pd.concat(out, ignore_index=True), qs


def final_conformal_q(preds: pd.DataFrame, calib_folds: int, coverage: float = 0.8) -> float:
    """q for the published forecast: the scores of the last `calib_folds` folds (all targets <= data through)."""
    if not calib_folds:
        return 0.0
    last = sorted(preds["fold"].unique())[-calib_folds:]
    return conformal_quantile(conformal_scores(preds[preds["fold"].isin(last)]), coverage)


def interval_widths(df: pd.DataFrame) -> dict:
    """Mean band width relative to the station's level, raw and published."""
    lvl = df["level"].to_numpy(dtype="float64")
    return {
        "mean_width_raw": float(((df["p90"] - df["p10"]).to_numpy() / lvl).mean()),
        "mean_width_calibrated": float(((df["upper"] - df["lower"]).to_numpy() / lvl).mean()),
    }


def metrics(df: pd.DataFrame) -> dict:
    err = df["p50"] - df["y"]
    base = df["baseline"] - df["y"]
    return {
        "mae_lgbm": float(err.abs().mean()),
        "rmse_lgbm": float(np.sqrt((err**2).mean())),
        "mae_baseline": float(base.abs().mean()),
        "rmse_baseline": float(np.sqrt((base**2).mean())),
        "coverage_p10_p90": float(((df["y"] >= df["p10"]) & (df["y"] <= df["p90"])).mean()),
        **(
            {"coverage_calibrated": float(((df["y"] >= df["lower"]) & (df["y"] <= df["upper"])).mean())}
            if "lower" in df
            else {}
        ),
    }


def paired_bootstrap(df: pd.DataFrame, b: int = 1000, seed: int = 0, level: float = 0.95) -> dict:
    """Point estimates and percentile CIs for MAE/RMSE of both models, their differences (baseline - model) and
    the p10-p90 coverage (and the calibrated band's, when `lower`/`upper` are present), resampling stations with
    replacement. Deterministic for a given seed."""
    calibrated = "lower" in df
    per = df.assign(
        ae_m=(df["p50"] - df["y"]).abs(),
        se_m=(df["p50"] - df["y"]) ** 2,
        ae_b=(df["baseline"] - df["y"]).abs(),
        se_b=(df["baseline"] - df["y"]) ** 2,
        inside=((df["y"] >= df["p10"]) & (df["y"] <= df["p90"])).astype(float),
        n=1.0,
        inside_cal=((df["y"] >= df["lower"]) & (df["y"] <= df["upper"])).astype(float) if calibrated else 0.0,
    )
    cols = ["ae_m", "se_m", "ae_b", "se_b", "inside", "n", "inside_cal"]
    sums = per.groupby("station_code", observed=True)[cols].sum()
    s = sums.to_numpy()  # (stations, 7)
    n_st = len(s)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_st, size=(b, n_st))
    weights = np.zeros((b, n_st))
    np.add.at(weights, (np.arange(b)[:, None], draws), 1.0)
    boot = weights @ s  # (b, 7) resampled totals

    def stats(t):
        n = t[..., 5]
        mae_m, mae_b = t[..., 0] / n, t[..., 2] / n
        rmse_m, rmse_b = np.sqrt(t[..., 1] / n), np.sqrt(t[..., 3] / n)
        return {
            "mae_lgbm": mae_m,
            "rmse_lgbm": rmse_m,
            "mae_baseline": mae_b,
            "rmse_baseline": rmse_b,
            "mae_diff": mae_b - mae_m,
            "rmse_diff": rmse_b - rmse_m,
            "coverage_p10_p90": t[..., 4] / n,
            **({"coverage_calibrated": t[..., 6] / n} if calibrated else {}),
        }

    point = stats(s.sum(axis=0))
    samples = stats(boot)
    a = (1 - level) / 2
    out = {"bootstrap_b": b, "bootstrap_seed": seed, "n_stations": n_st}
    for k, est in point.items():
        lo, hi = np.quantile(samples[k], [a, 1 - a])
        out[k] = float(est)
        out[f"{k}_lo"] = float(lo)
        out[f"{k}_hi"] = float(hi)
    return out
