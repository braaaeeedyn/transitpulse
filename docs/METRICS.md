# TransitPulse KPIs

Each KPI has one definition, computed once in dbt (`marts.mart_kpis_daily` / `marts.mart_recovery` /
`marts.mart_peak_load`). The website, Looker Studio and Power BI read these columns rather than re-deriving them,
so every surface shows the same number.

**Shared definitions**
- **Entries**: trips that *start* at a station (origin in the BART OD data). System entries = all trips.
- **Service weekday**: Monday–Friday, not a US federal holiday (`dim_date.is_service_weekday`).
- **Baseline**: ISO year 2019 (`var('baseline_year')`), the last full pre-pandemic year: Mon 2018-12-31 to Sun
  2019-12-29. ISO weeks are always paired with their ISO year (`dim_date.iso_year`, `iso_week`), never with the
  calendar year: 2019-12-30/31 are ISO week 1 of *2020*, 2018-12-31 is ISO week 1 of 2019. Days in ISO year 2019
  are the baseline and are not rows of `mart_recovery`.

| KPI | Definition | Formula | Column | The question it answers |
|---|---|---|---|---|
| Recovery % | A day's entries compared with a normal 2019 day at the same time of year | service-weekday entries ÷ average service-weekday entries in the same ISO week of ISO year 2019 | `mart_kpis_daily.recovery_ratio` (system), `mart_recovery.recovery_ratio` (station) | How close is ridership to pre-pandemic levels? |
| Daily entries | Total trips started that day | Σ trips | `mart_kpis_daily.total_entries` | How many people rode? |
| Rolling 28-day average | Smoothed daily entries | mean entries over the calendar days present in [d − 27, d]; `rolling_28d_days` says how many (28 without gaps) | `mart_kpis_daily.rolling_28d_avg_entries`, `.rolling_28d_days` | What's the trend without weekday/weekend noise? |
| YoY change | Change vs the same weekday 52 weeks earlier | (entries − entries 364 days earlier) ÷ entries 364 days earlier | `mart_kpis_daily.yoy_change` | Is ridership growing year over year? |
| Peak-hour share | How concentrated travel is in the busiest hour | busiest hour's entries ÷ day's entries | `mart_kpis_daily.peak_hour_share` (system), `mart_peak_load.peak_hour_share` (station, last 90 service weekdays) | How peaky is demand (crowding, staffing)? |
| Busiest station / share | The station with the most entries that day, and its share of all entries | max station entries; ÷ total | `mart_kpis_daily.busiest_station`, `.busiest_station_share` | Where is demand concentrated? |

## Values on the local build (checked 2026-10-09, ISO-year baseline)

| | 2019 | 2025 |
|---|---|---|
| Average daily entries | 324,958 | 149,335 |
| Average service-weekday recovery | 1.00 (≈ by definition: calendar 2019's Dec 30–31 compare with ISO week 1 of 2019) | **0.430** |
| Average peak-hour share | 0.113 | 0.107 |

Busiest station on most 2025 days: Embarcadero (224 days), then Powell St (137). Busiest weekday hour at
the top five stations: 17:00 (5 PM).

## Website KPI tiles (`GET /api/kpis`)

The tiles summarise the **28 days ending on the latest date in `mart_kpis_daily`** ("data through"). Windows are
picked by date in the API; `rolling_28d_avg_entries` is a calendar window too but isn't used by the tiles.

| Tile | Value | Delta |
|---|---|---|
| Recovery vs 2019 | mean `recovery_ratio` over the window's service weekdays | points vs the same window 364 days earlier, only if every one of those days is loaded |
| Average daily entries | mean `total_entries` over the window | Σ entries ÷ Σ `entries_364_days_earlier` − 1, only if every day has its year-earlier value |
| Peak-hour share | mean `peak_hour_share` over the window's service weekdays | points vs the mean over ISO-year-2019 service weekdays in the same ISO weeks (matched as (ISO year, ISO week) pairs) |
| Busiest station | the `busiest_station` on the most days in the window | (text) its mean `busiest_station_share` on those days |

Local values (28 days to 2025-12-31, after the ISO-year fix, 2026-10-09): 38.2%, 115,501, 10.9% (−0.87 pts vs
2019), Powell Street at 9.9% (busiest on 17 of 28 days). The recovery and entries deltas are empty locally because 2024 isn't loaded.

## Bikes vs trains (`marts.mart_bikes_vs_trains`, monthly)

| Metric | Definition | Column |
|---|---|---|
| Bay Wheels trips | trips that start in the month (after cleaning: `pipeline/baywheels.py`) | `bike_trips` |
| Bikes per day / BART entries per day | the month's total ÷ the days in that month with data | `bike_avg_daily_trips`, `bart_avg_daily_entries` |
| Index vs 2019 | per-day value ÷ the same calendar month's per-day value in 2019 × 100 | `bike_index_2019`, `bart_index_2019` |
| Bikes per 1,000 BART entries | 1000 × `bike_trips` ÷ `bart_entries` | `bikes_per_1000_bart_entries` |

Daily detail is in `marts.fct_bike_trips_daily`: trips split by member/casual, e-bike/classic/unknown (the 2019
schema has no bike type) and dockless (no start station).

| | 2019 | 2025 |
|---|---|---|
| Bay Wheels trips | 2,506,867 | 4,395,116 |
| Bikes per 1,000 BART entries | 21.1 | 80.6 |
| Bay Wheels index vs 2019 (monthly range) | 100 | 127–210 |
| BART index vs 2019 (monthly range) | 100 | 43–48 |

## Forecast interval coverage (`ml.forecast_runs`, `GET /api/forecast/{code}`)

| Metric | Definition | Column |
|---|---|---|
| Raw coverage | share of back-test days (6 test folds × 14 days × stations) whose actual entries fell inside the model's p10–p90 | `coverage_p10_p90` (+ `_lo`/`_hi`, 95% bootstrap CI over stations) |
| Calibrated coverage | the same share for the published band `lower`–`upper` (split-conformal, below) | `coverage_calibrated` (+ `_lo`/`_hi`) |
| Nominal | the coverage the band aims for: 0.80 (p10 to p90) | `interval_nominal` |
| Band width | mean (upper − lower) ÷ the station's 28-day mean level, raw and published | `mean_width_raw`, `mean_width_calibrated` |
| Conformal adjustment | how far each edge of the published forecast's band moves, in units of the station's level | `conformal_q` |

- **Calibration.** Rolling split-conformal on CQR scores: score = max(p10 − actual, actual − p90) ÷ level. Each test
  fold moves both edges by the ⌈(n + 1) × 0.8⌉-th smallest score of the 6 folds just *before* it (all targets at or
  before that fold's origin), so a test fold never calibrates its own band. The published forecast uses the last 6
  folds. p50 is unchanged, so MAE/RMSE don't change.
- **What the site calls the band.** "80% range" only when the band is calibrated and its back-tested coverage is
  within 5 points of 80%. A calibrated band outside that is the "calibrated model range" (p10/p90 widened, so never
  called the 10th–90th percentile); an uncalibrated band is the "model range (10th–90th percentile)". The source
  line says "narrower than it should be" below 75% and "wider than needed" above 85%. If calibration lands farther
  from 80% than the raw band, the API serves the raw band.

## Ask TransitPulse eval (`eval/questions.yaml`, `python -m eval.run_eval`)

| Metric | Definition |
|---|---|
| Execution accuracy | share of the in-scope questions (66) whose answer rows equal the gold SQL's rows: as a multiset (in order when the gold SQL ends in `ORDER BY … LIMIT`), any column order/names when the column counts match, numbers at relative tolerance 1e-4, dates as ISO strings. A refusal or error counts as wrong. |
| Refusal accuracy | share of the out-of-scope questions (10) the agent refused |
| Guardrail rejections | questions that ended because both SQL attempts were rejected by the guardrails |
| Latency p50/p95 | wall time per question through the whole graph (route, SQL, query, answer) |

`--llm fake` scripts the FakeLLM with the gold SQL (an oracle): it checks the harness and must score 1.0. The model
numbers are in `eval/results/summary-*.json`, written only with `--save-summary`; first run (llama3.1:8b, local DuckDB, 2026-10-09): execution accuracy
**0.27** (18/66), refusal accuracy 1.0, 0 guardrail rejections, p50 2.4 s / p95 6.4 s.

## Causal estimates (eBART study, `api/data/findings.json`, `GET /api/findings`)

Defined by the pre-registration (`analysis/causal/preregistration.json` + Amendment 1); the write-up is
[`FINDINGS.md`](FINDINGS.md).

| Estimand | Definition |
|---|---|
| b | The difference-in-differences coefficient on ln(weekly entries): (treated − controls) mean log entries after the opening minus the same gap before, with station and week fixed effects (34 control stations; e = −1, the transition week, dropped) |
| % | 100 × (e^b − 1) |
| Legacy | PITT, NCON and CONC pooled with equal weight against the 34 controls |
| Corridor | ANTC + PCTR + PITT + NCON + CONC **summed into one unit before the log**, so moved riders cancel and new riders show |
| Buffer | ORIN, LAFY, WCRK and PHIL pooled (a spillover check) |
| Per station | PITT, NCON and CONC each against the controls |
| Implied daily entries | Post-period mean weekly corridor entries × (1 − e^−b) / 7, averaged over all days; the same transform is applied to the interval bounds |

**Intervals.**
- **Placebo interval (headline, "95% interval" on the site).** Treatment is reassigned to sets of control stations,
  and the estimate is recomputed with the rest of the controls. The interval is [b − q97.5, b − q2.5] of those
  placebo estimates (numpy linear quantiles). The sets:
  - legacy: all C(34,3) = 5,984 sets of 3;
  - corridor: all 5,984 sets of 3, **each summed into one unit**, because the real corridor is 3 stations before
    the opening (Amendment 1);
  - buffer: 10,000 random sets of 4 (seed 20180526);
  - per station: the 34 single controls;
  - with the 16 suburban controls: every combination (560 for sets of 3, 1,820 for sets of 4).
- **RI p:** (1 + #{|b_placebo| ≥ |b|}) / (1 + N), two-sided. Per station its floor is 1/35.
- **CR1 interval:** statsmodels cluster-robust by station, t with G − 1 degrees of freedom. It is reported but not
  the headline: on synthetic data it covers 0.79–0.83, against 0.925–0.965 for the placebo intervals.
- **Pre-trend tests:**
  - RI p of the sum of squared pre-period event-study bin coefficients (legacy and corridor);
  - the CR1 joint Wald test (legacy).
- **Verdict:**
  - new if the corridor interval is above 0;
  - moved if it contains 0 and the legacy interval is below 0;
  - fewer if it is below 0;
  - otherwise inconclusive.
- **Caution flag:** a weekly pre-trend RI p < 0.10, or a monthly corridor interval that excludes 0 with the opposite
  sign.

## Cross-tool check (M2, to do)
Once the Power BI report exists, pick 3 KPIs for one week and confirm that DAX = dbt mart value; record it here.
