"""Post-hoc, not pre-registered: the eBART corridor and legacy effects net of a linear pre-trend in the gap.

Decided on 2026-10-14, after the pre-registered results were seen, because the monthly series drifts up against the
controls before the opening (docs/FINDINGS.md, Limitations). It is exploratory and does not change the
pre-registered verdict in api/data/findings.json.

    uv run --group ml python -m analysis.causal.trend_adjusted            # headline numbers of a fresh run
    uv run --group ml python -m analysis.causal.trend_adjusted --write    # write trend_adjusted.json
    uv run --group ml python -m analysis.causal.trend_adjusted --check    # recompute; exit 1 if the file differs
    uv run --group ml python -m analysis.causal.trend_adjusted --summary  # headline numbers of the committed file

Per unit (the corridor aggregate and the pooled legacy stations, built as the pre-registered analysis builds them),
gap_t = treated log outcome - mean control log outcome:
- primary, monthly (avg weekday entries, the pre-registered monthly window): fit gap_t = a + beta * t by OLS over the
  pre-period months (e < 0); the adjusted effect is the mean over the post months (e >= 0) of gap_t - (a + beta * t).
- secondary, weekly (the primary weekly design): the weekly double difference minus beta (that unit's monthly
  pre-period slope) times the months between the mean post week and the mean pre week, i.e. the monthly trend
  extrapolated across the weekly window.
- inference: the same procedure on every pre-registered placebo draw (sets of 3 controls against the other 31;
  corridor sets summed before the log), giving [b - q(0.975), b - q(0.025)] and the two-sided RI p.
Inputs are only the committed CSVs and the pre-registration; the output is byte-stable like findings.json.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.causal import design, did
from analysis.causal.run import CORRIDOR, load_inputs, render

OUT = Path(__file__).with_name("trend_adjusted.json")
DECIDED_ON = "2026-10-14"
DAYS_PER_MONTH = 365.2425 / 12
UNITS = ("corridor", "legacy")


def _ols(t: np.ndarray) -> np.ndarray:
    """(2, n) matrix P with (a, beta) = P @ y for the OLS fit y = a + beta * t."""
    x = np.column_stack([np.ones(len(t)), t])
    return np.linalg.solve(x.T @ x, x.T)


def trend_weights(t: np.ndarray, fit: np.ndarray, post: np.ndarray) -> np.ndarray:
    """w with gap @ w = mean over `post` of gap_t - (a + beta * t), (a, beta) fitted by OLS over `fit` periods."""
    w = np.zeros(len(t))
    w[post] = 1.0 / post.sum()
    w[fit] -= np.array([1.0, t[post].mean()]) @ _ols(t[fit])
    return w


def slope_weights(t: np.ndarray, fit: np.ndarray) -> np.ndarray:
    """w with gap @ w = the OLS slope beta of gap on t over `fit` periods."""
    w = np.zeros(len(t))
    w[fit] = _ols(t[fit])[1]
    return w


def gaps(p: pd.DataFrame, d: design.Design, unit: str, outcome: str):
    """(real gap per period, placebo gaps (draws x periods), event time, period labels) for `unit`, against the
    pre-registered controls, with the pre-registered placebo draws."""
    pool = list(d.controls)
    lpool, e, periods = did.wide(p, pool, outcome)
    if unit == "corridor":
        real, _ = did.gap(did.aggregate_unit(p, d.corridor, CORRIDOR), [CORRIDOR], pool, outcome)
    else:
        real, _ = did.gap(p, d.treated, pool, outcome)
    sets = did.draw_sets(len(pool), d.placebo_draws[unit], d.seed)
    k = sets.shape[1]
    onehot = np.zeros((len(sets), len(pool)))
    np.put_along_axis(onehot, sets, 1.0, axis=1)
    rest = (lpool.sum(axis=0)[None, :] - onehot @ lpool) / (len(pool) - k)
    if unit == "corridor":
        treated = np.log(onehot @ did.wide(p, pool, outcome, log=False)[0])
    else:
        treated = onehot @ lpool / k
    return real, treated - rest, e, periods


def _estimate(b: float, draws: np.ndarray, d: design.Design, beta: float, unadjusted: float) -> dict:
    q_lo, q_hi = np.quantile(draws, d.ci_quantiles, method="linear")
    ci = [float(b - q_hi), float(b - q_lo)]
    return {
        "trend_per_month": beta,
        "unadjusted_b": unadjusted,
        "unadjusted_pct": did.pct(unadjusted),
        "b": b,
        "pct": did.pct(b),
        "placebo_ci": ci,
        "placebo_ci_pct": [did.pct(x) for x in ci],
        "ri_p": float((1 + np.sum(np.abs(draws) >= abs(b) - 1e-12)) / (1 + len(draws))),
        "n_draws": len(draws),
    }


def compute(station_week: pd.DataFrame, station_month: pd.DataFrame, d: design.Design) -> dict:
    month = did.monthly_panel(station_month, d)
    weekly = did.weekly_panel(station_week, d)
    out: dict = {"monthly": {}, "weekly": {}}
    for unit in UNITS:
        g, g_draws, e, _ = gaps(month, d, unit, "avg_weekday_entries")
        t, fit, post = e.astype(float), e < 0, e >= 0
        adj, slope = trend_weights(t, fit, post), slope_weights(t, fit)
        beta, beta_draws = float(g @ slope), g_draws @ slope
        out["monthly"][unit] = _estimate(
            float(g @ adj), g_draws @ adj, d, beta, float(g @ did.post_weights(e))
        )
        out["monthly"]["fit_months"], out["monthly"]["post_months"] = int(fit.sum()), int(post.sum())

        wg, wg_draws, we, periods = gaps(weekly, d, unit, "entries")
        days = (pd.to_datetime(pd.Series(periods)) - pd.Timestamp(d.week_zero)).dt.days.to_numpy()
        months_apart = float((days[we >= 0].mean() - days[we < 0].mean()) / DAYS_PER_MONTH)
        dd_w = did.post_weights(we)
        b_w, b_w_draws = float(wg @ dd_w), wg_draws @ dd_w
        out["weekly"][unit] = _estimate(
            b_w - beta * months_apart, b_w_draws - beta_draws * months_apart, d, beta, b_w
        )
        out["weekly"]["months_between_post_and_pre_means"] = months_apart
    return {
        "status": "post-hoc, not pre-registered",
        "decided_on": DECIDED_ON,
        "note": (
            "Exploratory: chosen after the pre-registered results were seen. It does not change the pre-registered "
            "verdict in api/data/findings.json."
        ),
        "preregistration_sha256": d.sha256,
        "unit": "log points; trend_per_month is the OLS slope of the monthly pre-period gap",
        **out,
    }


def summary(doc: dict) -> dict:
    out = {"status": doc["status"]}
    for freq in ("monthly", "weekly"):
        for unit in UNITS:
            e, key = doc[freq][unit], f"{freq}_{unit}"
            out[f"{key}_trend_per_month"] = e["trend_per_month"]
            out[f"{key}_unadjusted_pct"] = e["unadjusted_pct"]
            out[f"{key}_pct"] = e["pct"]
            out[f"{key}_ci_pct_lo"], out[f"{key}_ci_pct_hi"] = e["placebo_ci_pct"]
            out[f"{key}_ri_p"] = e["ri_p"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help=f"write {OUT.name}")
    ap.add_argument("--check", action="store_true", help=f"recompute; exit 1 if {OUT.name} differs")
    ap.add_argument("--summary", action="store_true", help=f"headline numbers of the committed {OUT.name}")
    args = ap.parse_args()
    if args.summary:
        print(json.dumps(summary(json.loads(OUT.read_text(encoding="utf-8")))))
        return 0
    text = render(compute(*load_inputs(), design.load()))
    if args.check:
        committed = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else ""
        if committed != text:
            print(f"{OUT} differs from a fresh run of the committed data", file=sys.stderr)
            return 1
        print(f"{OUT}: reproducible")
        return 0
    if args.write:
        OUT.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps(summary(json.loads(text))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
