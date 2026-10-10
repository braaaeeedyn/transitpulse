"""Difference-in-differences estimators and inference for the eBART study.

Panels are long DataFrames with columns `unit`, `period` (a sortable label), `e` (event time; e >= 0 is post) and
one or more outcome columns in levels (entries, exits, avg_weekday_entries). Outcomes are logged here, after any
aggregation (`aggregate_unit` sums levels first).

- `twfe`: y = unit FE + period FE + b * D, statsmodels OLS, CR1 standard errors clustered by unit (use_t=True).
- `event_study`: unit and period FE plus treated x bin dummies for every bin but the reference; CR1 CIs and the
  joint Wald test of the pre-bins.
- `dd` / `dd_bins`: the same coefficients as exact double differences of unit x period means (balanced panels).
  Tests assert they equal statsmodels to 1e-8; the placebo draws use them.
- `placebo`: in-space placebo (Conley-Taber style) interval, randomization-inference p, per-bin placebo bands and
  the pre-trend RI p, from reassigning treatment to sets of control stations only.
- `verdict` / `caution`: the pre-registered decision rules.
"""

import itertools
import math
from dataclasses import dataclass, field
from functools import cache

import numpy as np
import pandas as pd

from analysis.causal.design import Design, Draws

# ---------------------------------------------------------------------------------------------------------------
# panels


def weekly_panel(station_week: pd.DataFrame, d: Design) -> pd.DataFrame:
    """station_week.csv → analysis panel: window weeks only, transition weeks dropped, and every week dropped (for
    all units) in which any treated, buffer or control station is missing a day."""
    df = station_week.rename(columns={"station_code": "unit", "week_start": "period"}).copy()
    df["period"] = df["period"].astype(str)
    start = pd.to_datetime(df["period"]).dt.date
    df = df[(start >= d.first_week) & (start <= d.last_week)].copy()
    df["e"] = [d.week_e(w) for w in pd.to_datetime(df["period"]).dt.date]
    df = df[~df["e"].isin(d.transition_weeks)]
    core = df[df["unit"].isin(d.analysis_stations)]
    n_core = len(d.analysis_stations)
    complete = core[core["days"] == 7].groupby("period")["unit"].nunique()
    keep = set(complete[complete == n_core].index)
    return df[df["period"].isin(keep)].reset_index(drop=True)


def monthly_panel(station_month: pd.DataFrame, d: Design) -> pd.DataFrame:
    """station_month_weekday.csv → analysis panel: window months only, transition months dropped."""
    df = station_month.rename(columns={"station_code": "unit", "month": "period"}).copy()
    df = df[(df["period"] >= d.first_month) & (df["period"] <= d.last_month)]
    df = df[~df["period"].isin(d.transition_months)].copy()
    df["e"] = [d.month_e(m) for m in df["period"]]
    return df.reset_index(drop=True)


def in_time_panel(panel: pd.DataFrame, fake_zero_e: int, last_e: int) -> pd.DataFrame:
    """The in-time placebo: only periods with e <= last_e, event time re-centred on a fake event at fake_zero_e."""
    out = panel[panel["e"] <= last_e].copy()
    out["e"] = out["e"] - fake_zero_e
    return out


def aggregate_unit(panel: pd.DataFrame, stations, name: str) -> pd.DataFrame:
    """Append one unit `name` whose outcomes are the per-period sums over `stations` (levels, before any log). A
    station with no row in a period counts as 0. Periods come from the panel, so the unit is balanced."""
    value_cols = [c for c in panel.columns if c not in ("unit", "period", "e", "days")]
    periods = panel[["period", "e"]].drop_duplicates()
    sums = panel[panel["unit"].isin(list(stations))].groupby("period")[value_cols].sum()
    agg = periods.merge(sums, left_on="period", right_index=True, how="left").fillna(
        dict.fromkeys(value_cols, 0)
    )
    agg.insert(0, "unit", name)
    return pd.concat([panel, agg], ignore_index=True)


def wide(panel: pd.DataFrame, units, outcome: str, log: bool = True) -> tuple[np.ndarray, np.ndarray, list]:
    """(units x periods matrix, event time per period, period labels) for a balanced subset; raises if any of the
    units is missing a period or (when logging) has a non-positive value."""
    units = list(units)
    sub = panel[panel["unit"].isin(units)]
    m = sub.pivot(index="unit", columns="period", values=outcome).reindex(index=units)
    if m.isna().to_numpy().any():
        raise ValueError(f"unbalanced panel for {outcome}: {m.isna().sum(axis=1)[lambda s: s > 0].to_dict()}")
    periods = list(m.columns)
    e = sub.drop_duplicates("period").set_index("period")["e"].reindex(periods).to_numpy()
    x = m.to_numpy(dtype=float)
    if log:
        if (x <= 0).any():
            raise ValueError(f"non-positive {outcome} cannot be logged")
        x = np.log(x)
    return x, e, periods


# ---------------------------------------------------------------------------------------------------------------
# statsmodels TWFE and event study (CR1 by unit)


def _design(units, periods, extra: np.ndarray) -> np.ndarray:
    """[extra regressors, a dummy per unit, a dummy per period except the first]."""
    u = pd.get_dummies(pd.Categorical(units), dtype=float).to_numpy()
    p = pd.get_dummies(pd.Categorical(periods), dtype=float).to_numpy()[:, 1:]
    return np.column_stack([extra, u, p])


def _fit(panel, treated, controls, outcome, regs):
    import statsmodels.api as sm

    units = list(treated) + list(controls)
    sub = panel[panel["unit"].isin(units)].sort_values(["unit", "period"])
    wide(panel, units, outcome)  # balanced and loggable, or raise
    y = np.log(sub[outcome].to_numpy(dtype=float))
    is_t = sub["unit"].isin(list(treated)).to_numpy()
    x = _design(sub["unit"].to_numpy(), sub["period"].to_numpy(), regs(is_t, sub["e"].to_numpy()))
    groups = pd.Categorical(sub["unit"]).codes
    res = sm.OLS(y, x).fit(cov_type="cluster", cov_kwds={"groups": groups}, use_t=True)
    return res, sub


def twfe(panel: pd.DataFrame, treated, controls, outcome: str = "entries", alpha: float = 0.05) -> dict:
    """b on D = treated x (e >= 0), with CR1 SE/CI clustered by unit (t with G-1 df)."""
    res, sub = _fit(panel, treated, controls, outcome, lambda t, e: (t & (e >= 0)).astype(float)[:, None])
    lo, hi = res.conf_int(alpha=alpha)[0]
    return {
        "b": float(res.params[0]),
        "se": float(res.bse[0]),
        "cluster_ci": [float(lo), float(hi)],
        "p": float(res.pvalues[0]),
        "n_treated": len(list(treated)),
        "n_controls": len(list(controls)),
        "n_periods": int(sub["period"].nunique()),
        "n_obs": len(sub),
    }


def event_study(
    panel: pd.DataFrame, treated, controls, outcome: str, bins, ref_bin, alpha: float = 0.05
) -> dict:
    """Coefficients on treated x bin for every bin but `ref_bin`, CR1 CIs, and the joint Wald (F) test that the
    pre-bins (e < 0, reference excluded) are all zero."""
    bins = [tuple(b) for b in bins]
    est = [b for b in bins if b != tuple(ref_bin)]

    def regs(t, e):
        return np.column_stack([(t & (e >= lo) & (e <= hi)).astype(float) for lo, hi in est])

    res, _ = _fit(panel, treated, controls, outcome, regs)
    ci = res.conf_int(alpha=alpha)
    rows = []
    for lo, hi in bins:
        if (lo, hi) == tuple(ref_bin):
            rows.append(
                {"bin_start": lo, "bin_end": hi, "coef": 0.0, "se": 0.0, "cluster_lo": 0.0, "cluster_hi": 0.0}
            )
            continue
        j = est.index((lo, hi))
        rows.append(
            {
                "bin_start": lo,
                "bin_end": hi,
                "coef": float(res.params[j]),
                "se": float(res.bse[j]),
                "cluster_lo": float(ci[j][0]),
                "cluster_hi": float(ci[j][1]),
            }
        )
    pre = [est.index(b) for b in est if b[1] < 0]
    r = np.zeros((len(pre), len(res.params)))
    for i, j in enumerate(pre):
        r[i, j] = 1.0
    wald = res.f_test(r) if pre else None
    return {
        "bins": rows,
        "pretrend_wald_p": float(wald.pvalue) if wald is not None else None,
        "pretrend_wald_stat": float(np.squeeze(wald.fvalue)) if wald is not None else None,
    }


# ---------------------------------------------------------------------------------------------------------------
# exact double differences (balanced panels)


def post_weights(e: np.ndarray) -> np.ndarray:
    """w with b = gap · w: mean over post periods minus mean over pre periods."""
    post = e >= 0
    return np.where(post, 1.0 / post.sum(), -1.0 / (~post).sum())


def bin_weights(e: np.ndarray, bins, ref_bin) -> np.ndarray:
    """periods x bins matrix W with coef_k = gap · W[:, k]: bin mean minus reference-bin mean (0 for the reference)."""

    def mean_w(lo, hi):
        m = (e >= lo) & (e <= hi)
        if not m.any():
            raise ValueError(f"no periods in bin [{lo}, {hi}]")
        return m / m.sum()

    ref = mean_w(*ref_bin)
    return np.column_stack([mean_w(lo, hi) - ref for lo, hi in bins])


def gap(panel: pd.DataFrame, treated, controls, outcome: str) -> tuple[np.ndarray, np.ndarray]:
    """(mean log outcome of the treated - mean of the controls, per period; event time per period)."""
    yt, e, _ = wide(panel, treated, outcome)
    yc, _, _ = wide(panel, controls, outcome)
    return yt.mean(axis=0) - yc.mean(axis=0), e


def dd(panel: pd.DataFrame, treated, controls, outcome: str = "entries") -> float:
    """The TWFE b as a double difference of means (equal to statsmodels' on a balanced panel)."""
    g, e = gap(panel, treated, controls, outcome)
    return float(g @ post_weights(e))


def dd_bins(panel: pd.DataFrame, treated, controls, outcome: str, bins, ref_bin) -> np.ndarray:
    """The event-study coefficients (reference bin = 0) as double differences of means."""
    g, e = gap(panel, treated, controls, outcome)
    return g @ bin_weights(e, bins, ref_bin)


# ---------------------------------------------------------------------------------------------------------------
# placebo / randomization inference


@cache
def draw_sets(n_pool: int, draws: Draws, seed: int) -> np.ndarray:
    """Placebo sets as an (N, size) array of indices into the control pool, in draw order (read-only, cached).
    Every combination when `draws.n` is None or at least the number of combinations; otherwise `draws.n` distinct
    random sets, each drawn without replacement by numpy's default_rng(seed) and kept the first time it appears."""
    k = draws.size
    total = math.comb(n_pool, k)
    if draws.n is None or draws.n >= total:
        sets = np.array(list(itertools.combinations(range(n_pool), k)), dtype=int).reshape(-1, k)
    else:
        rng = np.random.default_rng(seed)
        seen: dict[tuple, None] = {}
        while len(seen) < draws.n:
            seen.setdefault(tuple(sorted(rng.choice(n_pool, size=k, replace=False).tolist())), None)
        sets = np.array(list(seen), dtype=int)
    sets.flags.writeable = False
    return sets


@dataclass
class PlaceboResult:
    b: float
    placebo_ci: list[float]
    ri_p: float
    n_draws: int
    draws_b: np.ndarray = field(repr=False)
    bins: list[dict] | None = None
    pretrend_ri_p: float | None = None


def _quantiles(x: np.ndarray, qs) -> np.ndarray:
    return np.quantile(x, qs, axis=0, method="linear")


def placebo(
    panel: pd.DataFrame,
    treated,
    pool,
    outcome: str,
    draws: Draws,
    seed: int,
    quantiles: tuple[float, float],
    *,
    aggregate: bool = False,
    bins=None,
    ref_bin=None,
) -> PlaceboResult:
    """In-space placebo inference for one estimand.

    The real estimate uses `treated` vs the whole `pool` (the controls). Each placebo draw treats a set S of
    `draws.size` pool stations and uses the rest of the pool as its controls; with `aggregate`, S (and the real
    treated) is summed into one unit before the log, as the corridor is.
    - placebo interval: [b - q_hi, b - q_lo] of the placebo estimates (numpy linear quantiles)
    - randomization p: (1 + #{|b_p| >= |b|}) / (1 + N), two-sided
    - with `bins`: per-bin bands [coef - q_hi, coef - q_lo], and the pre-trend RI p of S = sum of squared pre-bin
      coefficients (reference excluded): (1 + #{S_p >= S}) / (1 + N)
    """
    pool = list(pool)
    lpool, e, periods = wide(panel, pool, outcome)
    if aggregate:
        lev, _, _ = wide(panel, pool, outcome, log=False)
        t_lev, _, tp = wide(
            aggregate_unit(panel, treated, "__treated__"), ["__treated__"], outcome, log=False
        )
        if tp != periods:
            raise ValueError("treated and pool periods differ")
        real_t = np.log(t_lev[0])
    else:
        real_t = wide(panel, treated, outcome)[0].mean(axis=0)
    real_gap = real_t - lpool.mean(axis=0)

    w = post_weights(e)[:, None]
    if bins is not None:
        w = np.column_stack([w, bin_weights(e, bins, ref_bin)])
    real = real_gap @ w

    sets = draw_sets(len(pool), draws, seed)
    n, k = len(pool), sets.shape[1]
    onehot = np.zeros((len(sets), n))
    np.put_along_axis(onehot, sets, 1.0, axis=1)
    rest_mean = (lpool.sum(axis=0)[None, :] - onehot @ lpool) / (n - k)
    tr = np.log(onehot @ lev) if aggregate else (onehot @ lpool) / k
    placebo_vals = (tr - rest_mean) @ w  # (N, 1 + bins)

    q_lo, q_hi = _quantiles(placebo_vals, quantiles)
    b = float(real[0])
    pb = placebo_vals[:, 0]
    out = PlaceboResult(
        b=b,
        placebo_ci=[float(b - q_hi[0]), float(b - q_lo[0])],
        ri_p=float((1 + np.sum(np.abs(pb) >= abs(b) - 1e-12)) / (1 + len(pb))),
        n_draws=len(pb),
        draws_b=pb,
    )
    if bins is not None:
        out.bins = [
            {
                "bin_start": lo,
                "bin_end": hi,
                "coef": float(real[1 + j]),
                "lo": float(real[1 + j] - q_hi[1 + j]),
                "hi": float(real[1 + j] - q_lo[1 + j]),
            }
            for j, (lo, hi) in enumerate(bins)
        ]
        pre = [1 + j for j, (lo, hi) in enumerate(bins) if hi < 0 and (lo, hi) != tuple(ref_bin)]
        s_real = float(np.sum(real[pre] ** 2))
        s_draw = np.sum(placebo_vals[:, pre] ** 2, axis=1)
        out.pretrend_ri_p = float((1 + np.sum(s_draw >= s_real - 1e-12)) / (1 + len(s_draw)))
    return out


# ---------------------------------------------------------------------------------------------------------------
# derived quantities and decision rules


def pct(b: float) -> float:
    """Log points → percent change, 100 * (exp(b) - 1)."""
    return 100.0 * math.expm1(b)


def implied_daily_entries(post_mean_weekly: float, b: float, ci: list[float]) -> dict:
    """Corridor entries a day attributable to the effect: post-period actual mean weekly entries * (1 - exp(-b)) / 7,
    the same transformation applied to the interval bounds."""

    def f(x):
        return post_mean_weekly * -math.expm1(-x) / 7

    return {"point": f(b), "lo": f(ci[0]), "hi": f(ci[1])}


def verdict(corridor_ci, legacy_ci) -> str:
    """new: corridor interval above 0; fewer: below 0; moved: corridor contains 0 and legacy below 0; else
    inconclusive."""
    if corridor_ci[0] > 0:
        return "new"
    if corridor_ci[1] < 0:
        return "fewer"
    if legacy_ci[1] < 0:
        return "moved"
    return "inconclusive"


def caution(
    legacy_pretrend_p: float,
    corridor_pretrend_p: float,
    monthly_corridor_ci,
    weekly_corridor_b: float,
    p: float,
) -> bool:
    """True if either pre-trend RI p < p, or the monthly corridor interval excludes 0 with the opposite sign to the
    weekly corridor estimate."""
    if legacy_pretrend_p < p or corridor_pretrend_p < p:
        return True
    lo, hi = monthly_corridor_ci
    if lo > 0 and weekly_corridor_b < 0:
        return True
    return hi < 0 and weekly_corridor_b > 0


def headline(
    panel: pd.DataFrame, d: Design, outcome: str = "entries", controls=None, cluster: bool = True
) -> dict:
    """The two estimates the verdict uses (legacy pooled and the corridor aggregate, placebo intervals from the
    pre-registered draws) plus the legacy CR1 interval, and the verdict."""
    controls = list(controls if controls is not None else d.controls)
    common = {"pool": controls, "outcome": outcome, "seed": d.seed, "quantiles": d.ci_quantiles}
    leg = placebo(panel, d.treated, draws=d.placebo_draws["legacy"], **common)
    cor = placebo(panel, d.corridor, draws=d.placebo_draws["corridor"], aggregate=True, **common)
    out = {
        "legacy": {"b": leg.b, "placebo_ci": leg.placebo_ci, "ri_p": leg.ri_p, "n_draws": leg.n_draws},
        "corridor": {"b": cor.b, "placebo_ci": cor.placebo_ci, "ri_p": cor.ri_p, "n_draws": cor.n_draws},
    }
    if cluster:
        out["legacy"]["cluster_ci"] = twfe(panel, d.treated, controls, outcome)["cluster_ci"]
    out["verdict"] = verdict(cor.placebo_ci, leg.placebo_ci)
    return out
