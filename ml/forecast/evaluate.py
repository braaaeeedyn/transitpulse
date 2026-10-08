"""Walk-forward validation and paired bootstrap confidence intervals.

Each fold has a forecast origin; the model is trained only on rows whose *target* date is at or before the origin
(and whose origin lies inside the training window), then scored on the 14 days after the origin. Errors are pooled
over folds, stations and horizons. Uncertainty comes from a paired bootstrap over stations: resample stations with
replacement and recompute every metric on the same resample for both models, so the CI for the difference accounts
for the two models being scored on the same days.
"""

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
        out = test_rows[["station_code", "origin", "target_date", "horizon", "y"]].copy()
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


def metrics(df: pd.DataFrame) -> dict:
    err = df["p50"] - df["y"]
    base = df["baseline"] - df["y"]
    return {
        "mae_lgbm": float(err.abs().mean()),
        "rmse_lgbm": float(np.sqrt((err**2).mean())),
        "mae_baseline": float(base.abs().mean()),
        "rmse_baseline": float(np.sqrt((base**2).mean())),
        "coverage_p10_p90": float(((df["y"] >= df["p10"]) & (df["y"] <= df["p90"])).mean()),
    }


def paired_bootstrap(df: pd.DataFrame, b: int = 1000, seed: int = 0, level: float = 0.95) -> dict:
    """Point estimates and percentile CIs for MAE/RMSE of both models, their differences (baseline - model) and
    the p10-p90 coverage, resampling stations with replacement. Deterministic for a given seed."""
    per = df.assign(
        ae_m=(df["p50"] - df["y"]).abs(),
        se_m=(df["p50"] - df["y"]) ** 2,
        ae_b=(df["baseline"] - df["y"]).abs(),
        se_b=(df["baseline"] - df["y"]) ** 2,
        inside=((df["y"] >= df["p10"]) & (df["y"] <= df["p90"])).astype(float),
        n=1.0,
    )
    sums = per.groupby("station_code", observed=True)[["ae_m", "se_m", "ae_b", "se_b", "inside", "n"]].sum()
    s = sums.to_numpy()  # (stations, 6)
    n_st = len(s)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_st, size=(b, n_st))
    weights = np.zeros((b, n_st))
    np.add.at(weights, (np.arange(b)[:, None], draws), 1.0)
    boot = weights @ s  # (b, 6) resampled totals

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
