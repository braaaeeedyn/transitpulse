-- One row per calendar month with data: the series behind the site's "Ridership since 2019" chart.
-- Months with no data (e.g. years not loaded locally) have no row, so charts show a gap instead of bridging it.
select
    cast({{ dbt.date_trunc('month', 'trip_date') }} as date) as month_start,
    count(*) as days,
    avg(total_entries) as avg_daily_entries,
    sum(total_entries) as total_entries,
    avg(case when is_service_weekday then recovery_ratio end) as avg_service_weekday_recovery,
    avg(case when is_service_weekday then peak_hour_share end) as avg_service_weekday_peak_hour_share
from {{ ref('mart_kpis_daily') }}
group by 1
