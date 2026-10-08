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

## Cross-tool check (M2, to do)
Once the Power BI report exists, pick 3 KPIs for one week and confirm that DAX = dbt mart value; record it here.
