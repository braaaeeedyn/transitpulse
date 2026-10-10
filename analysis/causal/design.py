"""The pre-registered eBART design, read from `preregistration.json` (fixed 2026-10-09, never edited) with
`preregistration-amendment-1.json` (fixed 2026-10-10, never edited) applied on top.

Every station set, window, bin, draw count and the seed comes from those files; nothing here repeats them.

    from analysis.causal import design
    d = design.load()          # validated Design
    d.controls, d.weekly_bins(), d.placebo_draws["corridor"], ...
"""

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

PREREG_PATH = Path(__file__).with_name("preregistration.json")
AMENDMENT_PATHS = (Path(__file__).with_name("preregistration-amendment-1.json"),)


@dataclass(frozen=True)
class Draws:
    """How the placebo sets for one estimand are drawn: `size` controls per set, `n` random distinct sets, or every
    combination when `n` is None."""

    size: int
    n: int | None


@dataclass(frozen=True)
class Design:
    raw: dict
    sha256: str  # of the original preregistration.json
    fixed_on: str
    question: str
    event_date: date
    # station sets
    treated: tuple[str, ...]
    new: tuple[str, ...]
    corridor: tuple[str, ...]
    buffer: tuple[str, ...]
    excluded: dict[str, str]
    controls: tuple[str, ...]
    controls_suburban: tuple[str, ...]
    # weekly (primary)
    first_week: date
    last_week: date
    week_zero: date
    transition_weeks: tuple[int, ...]
    week_bin_width: int
    week_pre_bins: tuple[tuple[int, int], ...]
    week_ref_bin: tuple[int, int]
    week_post_bins_text: str
    # monthly (robustness)
    first_month: str
    last_month: str
    month_zero: str
    transition_months: tuple[str, ...]
    month_bin_width: int
    month_ref_bin: tuple[int, int]
    month_earliest_bin: tuple[int, int]
    # inference
    placebo_draws: dict[str, Draws]
    seed: int
    ci_quantiles: tuple[float, float]
    caution_p: float
    in_time_fake_week: date
    in_time_last_e: int
    # (file name, sha256, fixed_on) of each amendment applied to `raw`, in order
    amendments: tuple[tuple[str, str, str], ...] = ()

    @property
    def analysis_stations(self) -> tuple[str, ...]:
        """Stations that enter some estimate as their own unit (treated, buffer, controls)."""
        return self.treated + self.buffer + self.controls

    def week_e(self, week_start: date) -> int:
        days = (week_start - self.week_zero).days
        if days % 7:
            raise ValueError(f"{week_start} is not a week start aligned with {self.week_zero}")
        return days // 7

    def month_e(self, month: str) -> int:
        y, m = map(int, month.split("-"))
        y0, m0 = map(int, self.month_zero.split("-"))
        return (y - y0) * 12 + (m - m0)

    def weekly_bins(self) -> list[tuple[int, int]]:
        """Every weekly event-study bin, pre (incl. the reference) then post, cut at the window end."""
        last_e = self.week_e(self.last_week)
        first, step_end, last_end = _post_bins(self.week_post_bins_text)
        if first[0] != 0 or first[1] - first[0] + 1 != self.week_bin_width or last_end != last_e:
            raise ValueError("weekly post bins disagree with the window or bin width")
        post = [
            (s, min(s + self.week_bin_width - 1, last_e)) for s in range(0, last_e + 1, self.week_bin_width)
        ]
        if post[1][1] != step_end:
            raise ValueError("weekly post bins disagree with the bin width")
        return list(self.week_pre_bins) + post

    def monthly_bins(self) -> list[tuple[int, int]]:
        """Monthly bins: `month_bin_width`-month bins back from the reference bin, the earliest one absorbing the
        remainder up to the first month; post bins from e=0 cut at the window end."""
        w = self.month_bin_width
        first_e, last_e = self.month_e(self.first_month), self.month_e(self.last_month)
        pre = []
        end = self.month_ref_bin[1]
        while end - w + 1 > self.month_earliest_bin[1]:
            pre.append((end - w + 1, end))
            end -= w
        pre.append(self.month_earliest_bin)
        pre.reverse()
        if pre[0][0] != first_e or end != self.month_earliest_bin[1] or self.month_ref_bin not in pre:
            raise ValueError("monthly bins disagree with the window, earliest or reference bin")
        post = [(s, min(s + w - 1, last_e)) for s in range(0, last_e + 1, w)]
        return pre + post


def _post_bins(text: str) -> tuple[tuple[int, int], int, int]:
    pairs = [(int(a), int(b)) for a, b in re.findall(r"\[(-?\d+),\s*(-?\d+)\]", text)]
    return pairs[0], pairs[1][1], pairs[-1][1]


def _draws(text: str, n_pool: int) -> Draws:
    """Parse e.g. "all C(34,3) = 5984 sets of 3 controls", "10000 distinct random sets of 5 controls",
    "all 34 single controls"."""
    if text.startswith("all"):
        m = re.search(r"C\((\d+),(\d+)\)", text)
        if m:
            if int(m.group(1)) != n_pool:
                raise ValueError(f"placebo pool size in {text!r} is not {n_pool}")
            return Draws(int(m.group(2)), None)
        m = re.match(r"all (\d+) single", text)
        if m and int(m.group(1)) == n_pool:
            return Draws(1, None)
        raise ValueError(f"cannot parse placebo draws {text!r}")
    m = re.match(r"(\d+) distinct random sets of (\d+)", text)
    if not m:
        raise ValueError(f"cannot parse placebo draws {text!r}")
    return Draws(int(m.group(2)), int(m.group(1)))


def _in_time(texts: list[str]) -> tuple[date, int]:
    t = next(t for t in texts if t.startswith("in-time placebo"))
    last_e = int(re.search(r"e <= (-?\d+)", t).group(1))
    fake = date.fromisoformat(re.search(r"(\d{4}-\d{2}-\d{2})", t).group(1))
    return fake, last_e


def parse(raw: dict, sha256: str = "") -> Design:
    st, pr, mo, inf = raw["stations"], raw["primary"], raw["robustness_monthly"], raw["inference"]
    n_pool = len(st["controls"])
    fake, last_e = _in_time(inf["falsification"])
    return Design(
        raw=raw,
        sha256=sha256,
        fixed_on=raw["fixed_on"],
        question=raw["question"],
        event_date=date.fromisoformat(raw["event"]["date"]),
        treated=tuple(st["treated_legacy"]),
        new=tuple(st["new"]),
        corridor=tuple(st["corridor"]),
        buffer=tuple(st["buffer"]),
        excluded=dict(st["excluded"]),
        controls=tuple(st["controls"]),
        controls_suburban=tuple(st["controls_suburban"]),
        first_week=date.fromisoformat(pr["window"]["first_week_start"]),
        last_week=date.fromisoformat(pr["window"]["last_week_start"]),
        week_zero=date.fromisoformat(pr["event_week_zero_start"]),
        transition_weeks=tuple(pr["transition_weeks_dropped"]),
        week_bin_width=pr["event_study_bins_weeks"],
        week_pre_bins=tuple(tuple(b) for b in pr["event_study_pre_bins"]),
        week_ref_bin=tuple(pr["event_study_reference_bin"]),
        week_post_bins_text=pr["event_study_post_bins"],
        first_month=mo["window"]["first_month"],
        last_month=mo["window"]["last_month"],
        month_zero=mo["event_month_zero"],
        transition_months=tuple(mo["transition_months_dropped"]),
        month_bin_width=mo["event_study_bins_months"],
        month_ref_bin=tuple(mo["event_study_reference_bin"]),
        month_earliest_bin=tuple(mo["event_study_earliest_bin"]),
        placebo_draws={k: _draws(v, n_pool) for k, v in inf["placebo_draws"].items()},
        seed=inf["seed"],
        ci_quantiles=tuple(sorted(float(q) for q in re.findall(r"q\((0\.\d+)\)", inf["headline_ci"]))),
        caution_p=float(re.search(r"p < (0\.\d+)", raw["decision_rules"]["caution_flag"]).group(1)),
        in_time_fake_week=fake,
        in_time_last_e=last_e,
    )


def validate(d: Design, stations=None) -> None:
    """Raise ValueError if the sets overlap, the corridor isn't treated + new, the placebo set sizes don't match the
    estimands, or (given the panel's stations) the sets don't cover them exactly."""
    sets = {
        "treated": d.treated,
        "new": d.new,
        "buffer": d.buffer,
        "excluded": tuple(d.excluded),
        "controls": d.controls,
    }
    seen: dict[str, str] = {}
    for name, members in sets.items():
        if len(set(members)) != len(members):
            raise ValueError(f"duplicate station in {name}")
        for s in members:
            if s in seen:
                raise ValueError(f"{s} is in both {seen[s]} and {name}")
            seen[s] = name
    if set(d.corridor) != set(d.treated) | set(d.new) or len(d.corridor) != len(set(d.corridor)):
        raise ValueError("corridor must be exactly treated + new")
    if not set(d.controls_suburban) <= set(d.controls):
        raise ValueError("suburban controls must be a subset of the controls")
    if len(d.controls) != 34:
        raise ValueError(f"expected 34 controls, got {len(d.controls)}")
    # corridor placebos match the corridor's pre-opening composition, the legacy stations (Amendment 1)
    sizes = {"legacy": len(d.treated), "corridor": len(d.treated), "buffer": len(d.buffer), "per_station": 1}
    for k, n in sizes.items():
        if d.placebo_draws[k].size != n:
            raise ValueError(f"placebo sets for {k} have {d.placebo_draws[k].size} stations, expected {n}")
    if len(d.ci_quantiles) != 2 or not 0 < d.ci_quantiles[0] < 0.5 < d.ci_quantiles[1] < 1:
        raise ValueError(f"bad placebo interval quantiles {d.ci_quantiles}")
    if d.week_zero.weekday() != 0 or d.first_week.weekday() != 0 or d.last_week.weekday() != 0:
        raise ValueError("weeks must start on a Monday (ISO weeks)")
    if not 0 <= (d.week_zero - d.event_date).days < 7:
        raise ValueError("week zero must be the first full week after the event")
    if stations is not None and set(stations) != set(seen):
        missing, extra = set(stations) - set(seen), set(seen) - set(stations)
        raise ValueError(
            f"station sets don't cover the panel: unassigned {sorted(missing)}, absent {sorted(extra)}"
        )
    d.weekly_bins()
    d.monthly_bins()


def apply_amendment(raw: dict, amendment: dict, sha256: str) -> dict:
    """A copy of `raw` with the amendment's `changes` applied. Each change is a dotted path into `raw` whose current
    value must equal `was`; it is set to `now`. Raises if the amendment is for another file or a `was` differs."""
    if amendment["amends_sha256"] != sha256:
        raise ValueError(f"amendment is for sha256 {amendment['amends_sha256']}, not {sha256}")
    out = json.loads(json.dumps(raw))
    for path, change in amendment["changes"].items():
        *parents, key = path.split(".")
        node = out
        for p in parents:
            node = node[p]
        if key not in node or node[key] != change["was"]:
            raise ValueError(f"amendment expects {path} = {change['was']!r}, found {node.get(key)!r}")
        node[key] = change["now"]
    return out


@cache
def load(path: Path = PREREG_PATH, amendments: tuple[Path, ...] = AMENDMENT_PATHS) -> Design:
    """The original pre-registration with every amendment applied (each one required), validated."""
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    raw = json.loads(data)
    applied = []
    for a in amendments:
        a_data = Path(a).read_bytes()  # a missing amendment is an error
        a_raw = json.loads(a_data)
        raw = apply_amendment(raw, a_raw, sha)
        applied.append((Path(a).name, hashlib.sha256(a_data).hexdigest(), a_raw["fixed_on"]))
    d = dataclasses.replace(parse(raw, sha), amendments=tuple(applied))
    validate(d)
    return d
