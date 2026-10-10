"""Synthetic panels with a known eBART effect, to validate the estimator and its intervals before any real run.

    uv run --group ml python -m analysis.causal.synthetic --sims 200 --seed 0 --json

Each panel has the pre-registered stations (treated, new, controls) and weeks (window minus transition weeks), with
ln entries = station FE + a shared seasonal week effect + AR(1) station noise, and one of three scenarios:
- "null":  no effect anywhere; the new stations carry no riders.
- "moved": PITT loses 20% after the opening and ANTC takes exactly those riders (corridor unchanged).
- "new":   ANTC and PCTR add riders equal to 15% of the legacy corridor (legacy unchanged, corridor +15%).

The study reports bias, RMSE and the coverage of the CR1 and placebo 95% intervals for the legacy and corridor
estimands, the RI rejection rate at 5% under the null, and how often each verdict comes out.
"""

import argparse
import json
import math
import time
from datetime import timedelta

import numpy as np
import pandas as pd

from analysis.causal import design, did

SCENARIOS = ("null", "moved", "new")
MOVED_SHARE = 0.20  # PITT riders who switch to ANTC
NEW_SHARE = 0.15  # new corridor riders, as a share of the legacy corridor
MOVED_FROM, MOVED_TO = "PITT", "ANTC"  # the old terminus and the new terminus
NOISE = {"sigma": 0.04, "rho": 0.5}  # station noise: marginal sd (log points) and AR(1) coefficient


def truth(scenario: str, d: design.Design) -> dict[str, float]:
    """The true legacy (pooled, equal weights) and corridor effects in log points."""
    legacy = {"null": 0.0, "moved": math.log(1 - MOVED_SHARE) / len(d.treated), "new": 0.0}[scenario]
    corridor = {"null": 0.0, "moved": 0.0, "new": math.log(1 + NEW_SHARE)}[scenario]
    return {"legacy": legacy, "corridor": corridor}


def generate(
    scenario: str,
    rng: np.random.Generator,
    d: design.Design | None = None,
    sigma: float = NOISE["sigma"],
    rho: float = NOISE["rho"],
) -> pd.DataFrame:
    """A long weekly panel (unit, period, e, entries) for one scenario."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    d = d or design.load()
    weeks = [d.first_week + timedelta(days=7 * i) for i in range((d.last_week - d.first_week).days // 7 + 1)]
    e = np.array([d.week_e(w) for w in weeks])
    keep = ~np.isin(e, d.transition_weeks)
    weeks, e = [w for w, k in zip(weeks, keep, strict=True) if k], e[keep]
    t = np.arange(len(weeks))
    season = 0.08 * np.sin(2 * np.pi * t / 52) + rng.normal(0, 0.03, len(t))
    legacy_units = list(d.treated) + list(d.controls)
    n = len(legacy_units)
    fe = rng.normal(math.log(35_000), 0.6, n)
    u = np.empty((n, len(t)))
    u[:, 0] = rng.normal(0, sigma, n)
    innov = sigma * math.sqrt(1 - rho**2)
    for j in range(1, len(t)):
        u[:, j] = rho * u[:, j - 1] + rng.normal(0, innov, n)
    level = np.exp(fe[:, None] + season[None, :] + u)  # counterfactual entries
    post = e >= 0
    idx = {s: i for i, s in enumerate(legacy_units)}
    new = {s: np.zeros(len(t)) for s in d.new}
    if scenario == "moved":
        taken = MOVED_SHARE * level[idx[MOVED_FROM]] * post
        level[idx[MOVED_FROM]] -= taken
        new[MOVED_TO] = taken
    elif scenario == "new":
        added = NEW_SHARE * level[[idx[s] for s in d.treated]].sum(axis=0) * post
        shares = np.linspace(0.6, 0.4, len(d.new))
        new = {s: sh * added for s, sh in zip(d.new, shares / shares.sum(), strict=True)}
    units = legacy_units + list(d.new)
    values = np.vstack([level, *(new[s] for s in d.new)])
    return pd.DataFrame(
        {
            "unit": np.repeat(units, len(t)),
            "period": [w.isoformat() for w in weeks] * len(units),
            "e": np.tile(e, len(units)),
            "entries": values.ravel(),
        }
    )


def study(
    sims: int, seed: int, cluster: bool = True, sigma: float = NOISE["sigma"], rho: float = NOISE["rho"]
):
    d = design.load()
    rng = np.random.default_rng(seed)
    out = {
        "sims": sims,
        "seed": seed,
        "noise": {"sigma": sigma, "rho": rho},
        "amendments": [sha for _, sha, _ in d.amendments],
        "scenarios": {},
    }
    t0 = time.monotonic()
    for sc in SCENARIOS:
        tr = truth(sc, d)
        rec = {"legacy": [], "corridor": [], "verdicts": {}}
        for _ in range(sims):
            panel = generate(sc, rng, d, sigma=sigma, rho=rho)
            h = did.headline(panel, d, cluster=cluster)
            for k in ("legacy", "corridor"):
                rec[k].append(h[k])
            rec["verdicts"][h["verdict"]] = rec["verdicts"].get(h["verdict"], 0) + 1
        res = {"verdicts": rec["verdicts"]}
        for k in ("legacy", "corridor"):
            b = np.array([r["b"] for r in rec[k]])
            err = b - tr[k]
            m = {
                "truth": tr[k],
                "bias": float(err.mean()),
                "rmse": float(np.sqrt((err**2).mean())),
                "placebo_coverage": float(
                    np.mean([r["placebo_ci"][0] <= tr[k] <= r["placebo_ci"][1] for r in rec[k]])
                ),
                "placebo_mean_width": float(
                    np.mean([r["placebo_ci"][1] - r["placebo_ci"][0] for r in rec[k]])
                ),
                "ri_reject_5pct": float(np.mean([r["ri_p"] <= 0.05 for r in rec[k]])),
                "placebo_n_draws": rec[k][0]["n_draws"],
            }
            if cluster and k == "legacy":
                m["cr1_coverage"] = float(
                    np.mean([r["cluster_ci"][0] <= tr[k] <= r["cluster_ci"][1] for r in rec[k]])
                )
                m["cr1_mean_width"] = float(
                    np.mean([r["cluster_ci"][1] - r["cluster_ci"][0] for r in rec[k]])
                )
            res[k] = m
        out["scenarios"][sc] = res
    cov = [out["scenarios"][s][k]["placebo_coverage"] for s in SCENARIOS for k in ("legacy", "corridor")]
    out["placebo_coverage_min"] = min(cov)
    if cluster:
        out["cr1_coverage_legacy_min"] = min(out["scenarios"][s]["legacy"]["cr1_coverage"] for s in SCENARIOS)
    out["ri_null_rejection_5pct"] = {
        k: out["scenarios"]["null"][k]["ri_reject_5pct"] for k in ("legacy", "corridor")
    }
    out["seconds"] = round(time.monotonic() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sigma", type=float, default=NOISE["sigma"])
    ap.add_argument("--rho", type=float, default=NOISE["rho"])
    ap.add_argument("--no-cluster", action="store_true", help="skip the statsmodels CR1 fits (faster)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    res = study(args.sims, args.seed, cluster=not args.no_cluster, sigma=args.sigma, rho=args.rho)
    print(json.dumps(res) if args.json else json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
