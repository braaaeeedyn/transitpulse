# TransitPulse KPIs

Each KPI has one definition, computed once in dbt (`marts.mart_kpis_daily` / `marts.mart_recovery` /
`marts.mart_peak_load`). The website, Looker Studio and Power BI read these columns rather than re-deriving them,
so every surface shows the same number.

**Shared definitions**
- **Entries**: trips that *start* at a station (origin in the BART OD data). System entries = all trips.
- **Service weekday**: Monday–Friday, not a US federal holiday (`dim_date.is_service_weekday`).
- **Baseline**: 2019 (`var('baseline_year')`), the last full pre-pandemic year.

| KPI | Definition | Formula | Column | The question it answers |
|---|---|---|---|---|
| Recovery % | A day's entries compared with a normal 2019 day at the same time of year | service-weekday entries ÷ average service-weekday entries in the same ISO week of 2019 | `mart_kpis_daily.recovery_ratio` (system), `mart_recovery.recovery_ratio` (station) | How close is ridership to pre-pandemic levels? |
| Daily entries | Total trips started that day | Σ trips | `mart_kpis_daily.total_entries` | How many people rode? |
| Rolling 28-day average | Smoothed daily entries | mean of the last 28 days' entries | `mart_kpis_daily.rolling_28d_avg_entries` | What's the trend without weekday/weekend noise? |
| YoY change | Change vs the same weekday 52 weeks earlier | (entries − entries 364 days earlier) ÷ entries 364 days earlier | `mart_kpis_daily.yoy_change` | Is ridership growing year over year? |
| Peak-hour share | How concentrated travel is in the busiest hour | busiest hour's entries ÷ day's entries | `mart_kpis_daily.peak_hour_share` (system), `mart_peak_load.peak_hour_share` (station, last 90 service weekdays) | How peaky is demand (crowding, staffing)? |
| Busiest station / share | The station with the most entries that day, and its share of all entries | max station entries; ÷ total | `mart_kpis_daily.busiest_station`, `.busiest_station_share` | Where is demand concentrated? |

## Values on the local build (2019 + 2025 data, checked 2026-10-07)

| | 2019 | 2025 |
|---|---|---|
| Average daily entries | 324,958 | 149,335 |
| Average service-weekday recovery | 1.00 (by definition) | **0.431** |
| Average peak-hour share | 0.113 | 0.107 |

Busiest station on most 2025 days: Embarcadero (224 days), then Powell St (137). Busiest weekday hour at
the top five stations: 17:00 (5 PM).

## Website KPI tiles (`GET /api/kpis`)

The tiles summarise the **28 days ending on the latest date in `mart_kpis_daily`** ("data through"). Windows are
picked by date in the API, not with `rolling_28d_avg_entries` (a 28-*row* window that spans gaps in the data).

| Tile | Value | Delta |
|---|---|---|
| Recovery vs 2019 | mean `recovery_ratio` over the window's service weekdays | points vs the same window 364 days earlier, only if every one of those days is loaded |
| Average daily entries | mean `total_entries` over the window | Σ entries ÷ Σ `entries_364_days_earlier` − 1, only if every day has its year-earlier value |
| Peak-hour share | mean `peak_hour_share` over the window's service weekdays | points vs the mean over 2019 service weekdays in the same ISO weeks |
| Busiest station | the `busiest_station` on the most days in the window | (text) its mean `busiest_station_share` on those days |

Local values (28 days to 2025-12-31): 38%, 115,501, 10.9% (−0.9 pts vs 2019), Powell Street at 9.9% (busiest on
17 of 28 days). The recovery and entries deltas are empty locally because 2024 isn't loaded.

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

## Cross-tool check (M2, to do)
Once the Power BI report exists, pick 3 KPIs for one week and confirm that DAX = dbt mart value; record it here.
