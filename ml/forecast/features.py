"""Feature rows for direct multi-horizon forecasting of daily station entries.

One row per (station, forecast origin t, horizon h = 1..H), predicting entries on the target date d = t + h.
Every feature uses only data dated at or before the origin t; target-date features are calendar facts known in
advance (weekday, month, US federal holidays). Lags are calendar-based: a row whose 28-day history window has a
missing day (e.g. across the 2020-2024 gap in the local data) is dropped, never bridged.

Values are scaled by the station's 28-day mean at the origin (`level`), so one global model fits busy and quiet
stations alike; predictions are multiplied back by `level`.
"""

import numpy as np
import pandas as pd

WINDOW = 28  # days of history every row needs

FEATURES = [
    "station",
    "horizon",
    "target_weekday",
    "target_month",
    "target_is_holiday",
    "target_near_holiday",
    "naive_day_is_holiday",
    "last_ratio",
    "prev_ratio",
    "mean7_ratio",
    "naive_ratio",
    "same_weekday_mean_ratio",
    "cv28",
]
CATEGORICAL = ["station"]


def us_holidays(start, end) -> set[pd.Timestamp]:
    """US federal holidays (observed dates included) between two dates."""
    import holidays

    years = range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1)
    return {pd.Timestamp(d) for d in holidays.US(years=years)}


def to_panel(daily: pd.DataFrame) -> pd.DataFrame:
    """Long (trip_date, station_code, entries) → wide float panel on a complete daily calendar (NaN = no data)."""
    df = daily.assign(trip_date=pd.to_datetime(daily["trip_date"]))
    wide = df.pivot_table(index="trip_date", columns="station_code", values="entries", aggfunc="sum")
    full = pd.date_range(wide.index.min(), wide.index.max(), freq="D")
    return wide.reindex(full).astype("float64").sort_index(axis=1)


def make_rows(
    panel: pd.DataFrame,
    horizon: int = 14,
    origin_start=None,
    origin_end=None,
    holidays_set: set | None = None,
    future: bool = False,
) -> pd.DataFrame:
    """Feature rows for every origin in [origin_start, origin_end] (default: the whole panel) and h = 1..horizon.

    With `future=False` rows need an observed target; with `future=True` targets may lie past the panel's end
    (the actual forecast) and `y` is NaN. Rows whose 28-day history isn't complete are always dropped.
    """
    dates = panel.index
    values = panel.to_numpy()  # (T, S)
    n_days, n_stations = values.shape
    stations = np.asarray(panel.columns)

    roll28 = panel.rolling(WINDOW, min_periods=WINDOW)
    level = roll28.mean().to_numpy()
    std28 = roll28.std().to_numpy()
    mean7 = panel.rolling(7, min_periods=7).mean().to_numpy()

    lo = 0 if origin_start is None else int(dates.searchsorted(pd.Timestamp(origin_start)))
    hi = (
        n_days - 1
        if origin_end is None
        else int(dates.searchsorted(pd.Timestamp(origin_end), side="right")) - 1
    )
    lo = max(lo, WINDOW - 1)
    if hi < lo:
        return pd.DataFrame(
            columns=["origin", "target_date", "station_code", "y", "level", "naive", *FEATURES]
        )

    hol = (
        holidays_set
        if holidays_set is not None
        else us_holidays(dates[0], dates[-1] + pd.Timedelta(days=horizon))
    )
    origins = np.arange(lo, hi + 1)
    origin_dates = dates[origins]
    frames = []
    for h in range(1, horizon + 1):
        target_dates = origin_dates + pd.Timedelta(days=h)
        tgt_idx = origins + h
        inside = tgt_idx < n_days
        y = np.full((len(origins), n_stations), np.nan)
        y[inside] = values[tgt_idx[inside]]
        # seasonal naive: the latest day at or before the origin with the target's weekday (k = 0..6 days back)
        k = (origin_dates.dayofweek - target_dates.dayofweek) % 7
        naive_idx = origins - np.asarray(k)
        naive = values[naive_idx]
        # the four latest same-weekday values (all inside the 28-day window)
        same_wd = np.mean([values[naive_idx - 7 * j] for j in range(4)], axis=0)
        lvl = level[origins]
        frame = {
            "origin": np.repeat(origin_dates.values, n_stations),
            "target_date": np.repeat(target_dates.values, n_stations),
            "station_code": np.tile(stations, len(origins)),
            "y": y.ravel(),
            "level": lvl.ravel(),
            "naive": naive.ravel(),
            "horizon": np.full(len(origins) * n_stations, h, dtype="int16"),
            "target_weekday": np.repeat(target_dates.dayofweek.values, n_stations),
            "target_month": np.repeat(target_dates.month.values, n_stations),
            "target_is_holiday": np.repeat([d in hol for d in target_dates], n_stations),
            "target_near_holiday": np.repeat(
                [
                    (d - pd.Timedelta(days=1)) in hol or (d + pd.Timedelta(days=1)) in hol
                    for d in target_dates
                ],
                n_stations,
            ),
            "naive_day_is_holiday": np.repeat([dates[i] in hol for i in naive_idx], n_stations),
            "last_ratio": (values[origins] / lvl).ravel(),
            "prev_ratio": (values[origins - 1] / lvl).ravel(),
            "mean7_ratio": (mean7[origins] / lvl).ravel(),
            "naive_ratio": (naive / lvl).ravel(),
            "same_weekday_mean_ratio": (same_wd / lvl).ravel(),
            "cv28": (std28[origins] / lvl).ravel(),
        }
        frames.append(pd.DataFrame(frame))
    rows = pd.concat(frames, ignore_index=True)
    feature_cols = [c for c in FEATURES if c != "station"]
    ok = np.isfinite(rows["level"]) & (rows["level"] > 0)
    ok &= np.isfinite(rows[feature_cols].astype("float64")).all(axis=1)
    if not future:
        ok &= np.isfinite(rows["y"])
    rows = rows[ok].reset_index(drop=True)
    rows["station"] = pd.Categorical(rows["station_code"], categories=list(stations))
    for c in ("target_is_holiday", "target_near_holiday", "naive_day_is_holiday"):
        rows[c] = rows[c].astype("int8")
    return rows
