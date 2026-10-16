# BI build guide: Looker Studio and Power BI on the TransitPulse marts

Both tools read the same dbt marts in BigQuery (project `transitpulse-511002`, dataset `marts`) that the website
reads, so every surface shows the same number. Each KPI is defined once in dbt; see
[`docs/METRICS.md`](../docs/METRICS.md). This guide is all clicks: nothing in the repo has to change except the one
`<meta>` tag at the end of the Looker Studio part, and the files you save into `bi/` at the end of the Power BI part.

## The check week

Check week: **ISO week 2025-W39** (Monday 22 September to Sunday 28 September 2025). It has 7 days of data, 5
service weekdays and no US federal holiday (Labor Day was 1 September, Columbus Day 13 October).

These values come from the local warehouse (`marts.mart_kpis_daily` in `data/transitpulse.duckdb`), whose BART data
for 2018–2025 is the same as BigQuery's. `tests/local/test_bi_week.py` recomputes them and fails if this table
disagrees. Both reports must show exactly these numbers for this week:

| KPI | Definition (`mart_kpis_daily`) | Value for 2025-W39 |
|---|---|---|
| Total entries | `SUM(total_entries)` over the 7 days | **1,128,303** |
| Recovery vs 2019 | mean `recovery_ratio` over the week's service weekdays (`is_service_weekday = true`) | **0.4385** (43.85%) |
| Peak-hour share | mean `peak_hour_share` over the week's service weekdays | **0.1169** (11.69%) |
| Busiest station | the `busiest_station` on the most days of the week, then its mean `busiest_station_share` on those days | **Embarcadero** (EMBR), busiest on **5 of 7 days**, mean share **0.0912** |

The recovery and peak-hour figures are means over service weekdays only, the same rule the site's tiles use. The
peak-hour share over all 7 days would differ, so filter on `is_service_weekday` in both tools.

## Looker Studio (public dashboard)

1. **Connect.** Open [lookerstudio.google.com](https://lookerstudio.google.com) with the Google account that owns
   the GCP project → **Create → Data source → BigQuery → My projects → `transitpulse-511002` → `marts`**. Add one
   data source per table:
   - `mart_kpis_daily` (the daily KPIs: the tiles and the check week);
   - `mart_ridership_monthly` (the monthly ridership trend);
   - `mart_bikes_vs_trains` (the bikes vs trains index);
   - `dim_station` (station names for the busiest-station code).
   In each data source set **Data credentials: Owner's credentials** (so viewers need no BigQuery access) and
   **Data freshness: 12 hours** (fewer BigQuery queries; the data changes at most a few times a day).
2. **Build the report** (**Create → Report**, add the sources). Charts that mirror the site's Trends band:
   - **Scorecard "Recovery vs 2019":** source `mart_kpis_daily`, metric `AVG(recovery_ratio)`, filter
     `is_service_weekday = true`, shown as a percent.
   - **Scorecard "Average daily entries":** `AVG(total_entries)`.
   - **Scorecard "Total entries":** `SUM(total_entries)`.
   - **Scorecard "Peak-hour share":** `AVG(peak_hour_share)`, filter `is_service_weekday = true`, percent.
   - **Table "Busiest station":** a blend of `mart_kpis_daily` and `dim_station` joined on
     `busiest_station` = `station_code` (filter `is_current = true` on `dim_station`); dimension `station_name`,
     metric `Record Count`, sorted descending, 1 row.
   - **Time series "Ridership by month":** source `mart_ridership_monthly`, dimension `month_start`, metric
     `avg_daily_entries`.
   - **Time series "Bikes vs trains, index 2019 = 100":** source `mart_bikes_vs_trains`, dimension `month_start`,
     metrics `bart_index_2019` and `bike_index_2019`.
   - **A date range control** on `trip_date`, default **the last 28 days of data** (to match the site's tiles), with
     the check week available as a custom range.
3. **Check it.** Set the date range to **22 Sep 2025 – 28 Sep 2025**. The scorecards and table must show the
   values in the check-week table above (Looker Studio rounds; switch the scorecards to 4 decimals for the check).
4. **Share.** **Share → Manage access → Anyone with the link → Viewer.** Open the link in a private window to make
   sure it loads without signing in.
5. **Embed.** **File → Embed report → Enable embedding**, choose **Embed URL**, and copy it. It looks like
   `https://lookerstudio.google.com/embed/reporting/<report-id>/page/<page-id>`.
6. **Put it on the site.** Paste the embed URL as the `content` of `<meta name="tp-looker-url" content="">` in
   `web/index.html`. The Trends band then shows a "Dashboard" card: an embedded frame on wide screens, an "Open
   dashboard" link on phones. With the content empty nothing is shown. Re-export the pages afterwards
   (`docs/OWNER_STEPS.md`, the re-export step).

## Power BI Desktop (report, `.pbix`, PDF, screenshots)

1. **Connect.** **Home → Get data → More… → Google BigQuery → Connect**, sign in with the same Google account. In the
   Navigator open `transitpulse-511002` → `marts` and tick:
   - `mart_kpis_daily`, `dim_date`, `dim_station`, `mart_ridership_monthly`, `mart_bikes_vs_trains`.
   Choose **Load** (Import mode; these tables are small, `mart_kpis_daily` has one row per day since 2018).
2. **Model.** In **Model view** create:
   - `mart_kpis_daily[trip_date]` → `dim_date[date_day]` (many to one, single direction);
   - `mart_kpis_daily[busiest_station]` → `dim_station[station_code]` (many to one). `dim_station` is a type-2
     snapshot; in Power Query filter `is_current = TRUE` first so `station_code` is unique.
3. **DAX measures.** On `mart_kpis_daily`, **New measure**, one at a time:

   ```dax
   Total Entries = SUM ( mart_kpis_daily[total_entries] )
   ```

   ```dax
   Service Weekday Recovery =
   CALCULATE (
       AVERAGE ( mart_kpis_daily[recovery_ratio] ),
       mart_kpis_daily[is_service_weekday] = TRUE ()
   )
   ```

   ```dax
   Service Weekday Peak-Hour Share =
   CALCULATE (
       AVERAGE ( mart_kpis_daily[peak_hour_share] ),
       mart_kpis_daily[is_service_weekday] = TRUE ()
   )
   ```

   And, for the busiest-station check (the station busiest on the most days, ties broken by station code):

   ```dax
   Busiest Station =
   VAR ByStation =
       ADDCOLUMNS (
           VALUES ( mart_kpis_daily[busiest_station] ),
           "@days", CALCULATE ( COUNTROWS ( mart_kpis_daily ) )
       )
   VAR Top1 = TOPN ( 1, ByStation, [@days], DESC, mart_kpis_daily[busiest_station], ASC )
   RETURN
       LOOKUPVALUE (
           dim_station[station_name],
           dim_station[station_code], MAXX ( Top1, mart_kpis_daily[busiest_station] )
       )
   ```

   Format `Total Entries` as a whole number with a thousands separator, and the two shares as percentages with 2
   decimals.
4. **Report page.** Cards for the four measures; a line chart of `mart_ridership_monthly[avg_daily_entries]` by
   `month_start`; a line chart of `bart_index_2019` and `bike_index_2019` by `month_start`; slicers on
   `dim_date[iso_year]` and `dim_date[iso_week]`.
5. **Check it.** Set the slicers to **iso_year 2025, iso_week 39**. The cards must read **1,128,303**, **43.85%**,
   **11.69%** and **Embarcadero**, as in the check-week table. If one differs, the usual cause is a missing
   `is_service_weekday` filter or a slicer on `iso_week` without `iso_year`.
6. **Save into `bi/`.**
   - **File → Save as** `bi/transitpulse.pbix`.
   - **File → Export → Export to PDF** → `bi/transitpulse.pdf`.
   - Screenshots of the report page at the check week and at the full range → `bi/screenshot-check-week.png` and
     `bi/screenshot-overview.png`.
   - Optional (the M2 plan line asks for one): a short screen recording of the check, linked from here rather than
     committed if it is large.
7. **Commit** the `.pbix`, PDF and screenshots, then tick the Power BI line of M2 in
   `docs/IMPLEMENTATION_PLAN.md` (`docs/OWNER_STEPS.md` has the order).

## Costs

Both tools query BigQuery on your project. The marts are small (a few MB), and the 12-hour freshness (Looker
Studio) and Import mode (Power BI) keep the number of queries low, well inside BigQuery's free 1 TB a month.
