-- Recovery vs the baseline year (2019): each station's weekday entries divided by its average weekday entries
-- in the same ISO week of the baseline ISO year (2018-12-31 .. 2019-12-29). Weekends and holidays are excluded on
-- both sides.
with daily as (
    select f.trip_date, f.station_code, f.entries, d.iso_year, d.iso_week
    from {{ ref('fct_station_daily') }} as f
    inner join {{ ref('dim_date') }} as d on f.trip_date = d.date_day
    where d.is_service_weekday
),

baseline as (
    select station_code, iso_week, avg(entries) as baseline_entries
    from daily
    where iso_year = {{ var('baseline_year') }}
    group by 1, 2
)

select
    d.trip_date,
    d.station_code,
    d.entries,
    b.baseline_entries,
    d.entries / nullif(b.baseline_entries, 0) as recovery_ratio,
    -- period-over-period: change vs the same station one week earlier
    d.entries - lag(d.entries) over (partition by d.station_code order by d.trip_date) as entries_change_vs_prev_weekday,
    avg(d.entries) over (
        partition by d.station_code order by d.trip_date rows between 4 preceding and current row
    ) as entries_5_weekday_avg
from daily as d
left join baseline as b
    on d.station_code = b.station_code and d.iso_week = b.iso_week
where d.iso_year != {{ var('baseline_year') }}
