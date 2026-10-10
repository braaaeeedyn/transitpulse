"""The eBART study on the committed data: every pre-registered estimate, written to `api/data/findings.json`.

    uv run --group ml python -m analysis.causal.run            # compute and write findings.json
    uv run --group ml python -m analysis.causal.run --plots    # also docs/img/findings-event-study-*.png
    uv run --group ml python -m analysis.causal.run --check    # recompute; exit 1 if the committed file differs
    uv run --group ml python -m analysis.causal.run --summary  # flat JSON of the headline numbers (committed file)

Inputs are only the committed CSVs in analysis/causal/data/ and the pre-registration (with its amendments). The
output has sorted keys, floats rounded to 6 decimals and dates taken from the data (never the clock), so a
recomputation is byte-identical.
"""

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

from analysis.causal import design, did, monthly, panel

ROOT = Path(__file__).resolve().parents[2]
FINDINGS_PATH = ROOT / "api" / "data" / "findings.json"
IMG = ROOT / "docs" / "img"
PLOTS = {
    "weekly": IMG / "findings-event-study-weekly.png",
    "monthly": IMG / "findings-event-study-monthly.png",
}
CORRIDOR = "__corridor__"
SOURCE = (
    "BART origin-destination data: daily OD files (afcweb.bart.gov, 2018 onward) summed to station x ISO week, "
    "and BART monthly ridership reports (bart.gov, 'Weekday OD' sheets) for 2016-2020. Analysis: "
    "github.com/braaaeeedyn/transitpulse analysis/causal, pre-registered in analysis/causal/preregistration.json."
)


# ---------------------------------------------------------------------------------------------------------------
# estimates


def _estimate(
    p: pd.DataFrame,
    d: design.Design,
    treated,
    pool,
    outcome,
    draws,
    *,
    aggregate=False,
    bins=None,
    ref_bin=None,
    cluster=True,
) -> tuple[dict, did.PlaceboResult]:
    """One estimand: the double difference b, its placebo interval and RI p (pre-registered draws), and (for
    unaggregated estimands) the CR1 interval."""
    r = did.placebo(
        p,
        treated,
        pool,
        outcome,
        d.placebo_draws[draws],
        d.seed,
        d.ci_quantiles,
        aggregate=aggregate,
        bins=bins,
        ref_bin=ref_bin,
    )
    out = {
        "b": r.b,
        "pct": did.pct(r.b),
        "placebo_ci": r.placebo_ci,
        "placebo_ci_pct": [did.pct(x) for x in r.placebo_ci],
        "ri_p": r.ri_p,
        "n_draws": r.n_draws,
        "n_treated": 1 if aggregate else len(list(treated)),
        "n_controls": len(list(pool)),
        "n_periods": int(p["period"].nunique()),
    }
    if cluster and not aggregate:
        fit = did.twfe(p, treated, pool, outcome)
        if abs(fit["b"] - r.b) > 1e-8:  # the fast double difference must equal statsmodels
            raise AssertionError(f"double difference {r.b} != statsmodels {fit['b']}")
        out["cluster_ci"] = fit["cluster_ci"]
    return out, r


def analyse(
    p: pd.DataFrame, d: design.Design, outcome: str, pool, bins=None, ref_bin=None, per_station: bool = False
) -> dict:
    """legacy, corridor and buffer (and optionally per-station) estimates on one panel; with `bins`, the legacy and
    corridor event studies (placebo bands) and their pre-trend RI p."""
    pool = list(pool)
    ev = {"bins": bins, "ref_bin": ref_bin}
    legacy, leg_r = _estimate(p, d, d.treated, pool, outcome, "legacy", **ev)
    corridor, cor_r = _estimate(p, d, d.corridor, pool, outcome, "corridor", aggregate=True, **ev)
    buffer, _ = _estimate(p, d, d.buffer, pool, outcome, "buffer")
    out = {"legacy": legacy, "corridor": corridor, "buffer": buffer}
    if per_station:
        out["per_station"] = {s: _estimate(p, d, [s], pool, outcome, "per_station")[0] for s in d.treated}
    if bins is not None:
        out["pretrend"] = {"legacy_ri_p": leg_r.pretrend_ri_p, "corridor_ri_p": cor_r.pretrend_ri_p}
        out["event_study"] = {"legacy": leg_r.bins, "corridor": cor_r.bins}
    return out


def corridor_post_mean(p: pd.DataFrame, d: design.Design, outcome: str = "entries") -> float:
    """Mean weekly corridor entries over the post weeks actually observed."""
    agg = did.aggregate_unit(p, d.corridor, CORRIDOR)
    agg = agg[(agg["unit"] == CORRIDOR) & (agg["e"] >= 0)]
    return float(agg[outcome].mean())


def compute(station_week: pd.DataFrame, station_month: pd.DataFrame, d: design.Design) -> dict:
    """Every pre-registered number, as the findings.json document."""
    weekly = did.weekly_panel(station_week, d)
    month = did.monthly_panel(station_month, d)
    wbins, mbins = d.weekly_bins(), d.monthly_bins()

    primary = analyse(weekly, d, "entries", d.controls, wbins, d.week_ref_bin, per_station=True)
    cor = primary["corridor"]
    cor["implied_daily_entries"] = did.implied_daily_entries(
        corridor_post_mean(weekly, d), cor["b"], cor["placebo_ci"]
    )
    wald = did.event_study(weekly, d.treated, d.controls, "entries", wbins, d.week_ref_bin)

    mon = analyse(month, d, "avg_weekday_entries", d.controls, mbins, d.month_ref_bin)
    fake_e = d.week_e(d.in_time_fake_week)
    in_time = did.in_time_panel(weekly, fake_e, d.in_time_last_e)
    robustness = {
        "exits": analyse(weekly, d, "exits", d.controls),
        "suburban_controls": analyse(weekly, d, "entries", d.controls_suburban),
        "monthly": mon,
        "in_time_placebo": {
            **analyse(in_time, d, "entries", d.controls),
            "fake_event_week": d.in_time_fake_week.isoformat(),
            "last_week_e": d.in_time_last_e,
        },
    }
    pretrend = {**primary.pop("pretrend"), "legacy_wald_p": wald["pretrend_wald_p"]}
    series = primary.pop("event_study")

    periods = sorted(weekly["period"].unique())
    es = weekly.drop_duplicates("period")["e"]
    last_day = pd.Timestamp(periods[-1]).date() + timedelta(days=6)
    amendments = [
        {
            "file": name,
            "sha256": sha,
            "fixed_on": fixed_on,
            "summary": _amendment_summary(name),
        }
        for name, sha, fixed_on in d.amendments
    ]
    return {
        "question": d.question,
        "generated_at": last_day.isoformat(),  # from the data, not the clock, so --check is byte-stable
        "data_through": last_day.isoformat(),
        "preregistration": {"sha256": d.sha256, "fixed_on": d.fixed_on, "amendments": amendments},
        "design": {
            "event_date": d.event_date.isoformat(),
            "window": {
                "weekly": {
                    "first_week_start": periods[0],
                    "last_week_start": periods[-1],
                    "n_weeks": len(periods),
                    "n_pre_weeks": int((es < 0).sum()),
                    "n_post_weeks": int((es >= 0).sum()),
                    "transition_weeks_dropped": list(d.transition_weeks),
                },
                "monthly": {
                    "first_month": d.first_month,
                    "last_month": d.last_month,
                    "n_months": int(month["period"].nunique()),
                    "transition_months_dropped": list(d.transition_months),
                },
            },
            "treated": list(d.treated),
            "new": list(d.new),
            "corridor": list(d.corridor),
            "buffer": list(d.buffer),
            "excluded": dict(d.excluded),
            "controls": list(d.controls),
            "controls_suburban": list(d.controls_suburban),
            "outcome": d.raw["primary"]["outcome"],
        },
        "estimates": primary,
        "pretrend": pretrend,
        "robustness": robustness,
        "verdict": did.verdict(cor["placebo_ci"], primary["legacy"]["placebo_ci"]),
        "caution": did.caution(
            pretrend["legacy_ri_p"],
            pretrend["corridor_ri_p"],
            mon["corridor"]["placebo_ci"],
            cor["b"],
            d.caution_p,
        ),
        "event_study": {
            "unit": "log points",
            "reference_bin": list(d.week_ref_bin),
            "series": series,
        },
        "source": SOURCE,
    }


def _amendment_summary(name: str) -> str:
    raw = json.loads((design.PREREG_PATH.parent / name).read_text(encoding="utf-8"))
    return raw["title"]


# ---------------------------------------------------------------------------------------------------------------
# output


def _round(x):
    if isinstance(x, float):
        return round(x, 6) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_round(v) for v in x]
    return x


def render(doc: dict) -> str:
    return json.dumps(_round(doc), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    week = pd.read_csv(panel.WEEK_CSV, dtype={"week_start": str})
    month = pd.read_csv(monthly.MONTH_CSV, dtype={"month": str})
    return week, month


def summary(doc: dict) -> dict:
    """The headline numbers, flat (for the metric)."""
    est, rob = doc["estimates"], doc["robustness"]
    out = {"verdict": doc["verdict"], "caution": doc["caution"]}
    for name, e in (
        ("legacy", est["legacy"]),
        ("corridor", est["corridor"]),
        ("buffer", est["buffer"]),
        ("monthly_corridor", rob["monthly"]["corridor"]),
        ("monthly_legacy", rob["monthly"]["legacy"]),
        ("in_time_corridor", rob["in_time_placebo"]["corridor"]),
    ):
        out[f"{name}_pct"] = e["pct"]
        out[f"{name}_ci_pct_lo"], out[f"{name}_ci_pct_hi"] = e["placebo_ci_pct"]
        out[f"{name}_ri_p"] = e["ri_p"]
    imp = est["corridor"]["implied_daily_entries"]
    out.update(
        {
            "implied_daily_entries": imp["point"],
            "implied_daily_entries_lo": imp["lo"],
            "implied_daily_entries_hi": imp["hi"],
            **{f"pretrend_{k}": v for k, v in doc["pretrend"].items()},
            "monthly_pretrend_legacy_ri_p": rob["monthly"]["pretrend"]["legacy_ri_p"],
            "monthly_pretrend_corridor_ri_p": rob["monthly"]["pretrend"]["corridor_ri_p"],
        }
    )
    return out


def plot(doc: dict, which: str, path: Path) -> None:
    """Two small panels (legacy, corridor): ink line of bin coefficients, grey placebo band, zero line, opening."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, grey, rule = "#111111", "#d9d9d9", "#9a9a9a"
    if which == "weekly":
        series, unit = doc["event_study"]["series"], "weeks since opening"
    else:
        series, unit = doc["robustness"]["monthly"]["event_study"], "months since opening"
    titles = {
        "legacy": "Pittsburg/Bay Point, North Concord, Concord",
        "corridor": "Whole line, Concord to Antioch (incl. new stations)",
    }
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, key in zip(axes, ("legacy", "corridor"), strict=True):
        rows = series[key]
        x = [(r["bin_start"] + r["bin_end"]) / 2 for r in rows]
        ax.fill_between(x, [r["lo"] for r in rows], [r["hi"] for r in rows], color=grey, lw=0)
        ax.axhline(0, color=rule, lw=0.8)
        ax.axvline(-0.5, color=rule, lw=0.8, ls="--")
        ax.plot(x, [r["coef"] for r in rows], color=ink, lw=2, marker="o", ms=3)
        ax.set_title(titles[key], fontsize=10, loc="left")
        ax.set_xlabel(unit)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("effect (log points)")
    fig.suptitle(
        f"eBART event study ({which}): bin coefficients with 95% placebo bands",
        fontsize=11,
        x=0.01,
        ha="left",
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, metadata={"Software": None})
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check", action="store_true", help="recompute and compare with the committed findings.json"
    )
    ap.add_argument("--summary", action="store_true", help="print the headline numbers of the committed file")
    ap.add_argument("--plots", action="store_true", help="also write the event-study PNGs to docs/img/")
    ap.add_argument("--out", type=Path, default=FINDINGS_PATH)
    args = ap.parse_args()

    if args.summary:
        print(json.dumps(summary(json.loads(args.out.read_text(encoding="utf-8")))))
        return 0

    d = design.load()
    text = render(compute(*load_inputs(), d))
    if args.check:
        committed = args.out.read_text(encoding="utf-8").replace("\r\n", "\n") if args.out.exists() else ""
        if committed != text:
            print(f"{args.out} differs from a fresh run of the committed data", file=sys.stderr)
            return 1
        print(f"{args.out}: reproducible")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    doc = json.loads(text)
    if args.plots:
        for which, path in PLOTS.items():
            plot(doc, which, path)
    print(json.dumps(summary(doc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
