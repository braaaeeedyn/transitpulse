-- One row per day with every KPI in docs/METRICS.md, so the website, Looker Studio and Power BI all read the
-- same numbers.
with system_daily as (
    select trip_date, sum(entries) as total_entries
    from {{ ref('fct_station_daily') }}
    group by 1
),

system_hourly as (
    select trip_date, max(hour_entries) as peak_hour_entries
    from (
        select trip_date, trip_hour, sum(trips) as hour_entries
        from {{ ref('fct_trips_hourly') }}
        group by 1, 2
    ) as h
    group by 1
),

busiest as (
    select trip_date, station_code as busiest_station, entries as busiest_station_entries
    from {{ ref('fct_station_daily') }}
    qualify row_number() over (partition by trip_date order by entries desc, station_code) = 1
),

baseline as (
    select d.iso_week, avg(s.total_entries) as baseline_entries
    from system_daily as s
    inner join {{ ref('dim_date') }} as d on s.trip_date = d.date_day
    where d.iso_year = {{ var('baseline_year') }} and d.is_service_weekday
    group by 1
),

-- Calendar 28-day window [d - 27, d]: days missing from the data are not replaced by older ones
rolling as (
    select s.trip_date, avg(w.total_entries) as rolling_28d_avg_entries, count(*) as rolling_28d_days
    from system_daily as s
    inner join system_daily as w
        on w.trip_date <= s.trip_date
        and w.trip_date >= cast({{ dbt.dateadd('day', -27, 's.trip_date') }} as date)
    group by 1
),

joined as (
    select
        s.trip_date,
        d.weekday,
        d.is_service_weekday,
        s.total_entries,
        h.peak_hour_entries,
        b.busiest_station,
        b.busiest_station_entries,
        base.baseline_entries
    from system_daily as s
    inner join {{ ref('dim_date') }} as d on s.trip_date = d.date_day
    left join system_hourly as h on s.trip_date = h.trip_date
    left join busiest as b on s.trip_date = b.trip_date
    left join baseline as base on d.iso_week = base.iso_week and d.is_service_weekday
)

select
    j.trip_date,
    j.weekday,
    j.is_service_weekday,
    j.total_entries,
    -- Recovery % = weekday entries / average weekday entries in the same ISO week of 2019
    case when j.is_service_weekday then j.total_entries / nullif(j.baseline_entries, 0) end as recovery_ratio,
    -- Peak-hour share = busiest hour's entries / the day's entries
    j.peak_hour_entries / nullif(j.total_entries, 0) as peak_hour_share,
    j.busiest_station,
    j.busiest_station_entries,
    -- Busiest-station share = the busiest station's share of all entries that day
    j.busiest_station_entries / nullif(j.total_entries, 0) as busiest_station_share,
    -- Rolling 28-day average of daily entries over the calendar days present in [d - 27, d]
    r.rolling_28d_avg_entries,
    r.rolling_28d_days,
    -- YoY = vs the same weekday 52 weeks (364 days) earlier
    ly.total_entries as entries_364_days_earlier,
    (j.total_entries - ly.total_entries) / nullif(ly.total_entries, 0) as yoy_change
from joined as j
left join rolling as r on j.trip_date = r.trip_date
left join system_daily as ly on ly.trip_date = cast({{ dbt.dateadd('day', -364, 'j.trip_date') }} as date)
