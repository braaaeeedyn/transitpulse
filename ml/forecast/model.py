"""The forecast model (one global LightGBM per quantile) and the seasonal-naive baseline it must beat."""

import os

import numpy as np
import pandas as pd

from ml.forecast.features import CATEGORICAL, FEATURES

QUANTILES = (0.1, 0.5, 0.9)

DEFAULT_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 50,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.9,
    "reg_lambda": 1.0,
    # TP_ML_THREADS: match the machine's cores (2 on the Oracle VM; see deploy/oracle/transitpulse.env.example)
    "n_jobs": int(os.environ.get("TP_ML_THREADS", "4")),
}


def seasonal_naive(rows: pd.DataFrame) -> np.ndarray:
    """Baseline: the last observed value on the target's weekday at or before the origin."""
    return rows["naive"].to_numpy(dtype="float64")


def order_quantiles(pred: np.ndarray) -> np.ndarray:
    """Make (n, 3) quantile predictions monotone (p10 ≤ p50 ≤ p90) and non-negative."""
    return np.clip(np.sort(np.asarray(pred, dtype="float64"), axis=1), 0, None)


class QuantileForecaster:
    """Three LightGBM regressors (alpha = 0.1, 0.5, 0.9) on level-scaled targets. Deterministic for a given seed."""

    def __init__(self, seed: int = 0, **params):
        self.seed = seed
        self.params = {**DEFAULT_PARAMS, **params}
        self.models = {}

    def fit(self, rows: pd.DataFrame) -> "QuantileForecaster":
        import lightgbm as lgb

        x = rows[FEATURES]
        target = rows["y"].to_numpy() / rows["level"].to_numpy()
        for q in QUANTILES:
            model = lgb.LGBMRegressor(
                objective="quantile",
                alpha=q,
                random_state=self.seed,
                deterministic=True,
                force_row_wise=True,
                verbose=-1,
                **self.params,
            )
            model.fit(x, target, categorical_feature=CATEGORICAL)
            self.models[q] = model
        return self

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        x = rows[FEATURES]
        raw = np.column_stack([self.models[q].predict(x) for q in QUANTILES])
        scaled = order_quantiles(raw) * rows["level"].to_numpy()[:, None]
        return pd.DataFrame(scaled, columns=["p10", "p50", "p90"], index=rows.index)
