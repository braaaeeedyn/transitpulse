-- Rush-hour profile per station over the most recent 90 days of service weekdays:
-- the peak hour, its share of the day's entries, and how busy the station is relative to all others.
with recent as (
    select date_day
    from {{ ref('dim_date') }}
    where is_service_weekday
        and date_day > (select cast({{ dbt.dateadd('day', -90, 'max(date_day)') }} as date) from {{ ref('dim_date') }})
),

hourly as (
    select t.origin_code as station_code, t.trip_hour, sum(t.trips) as entries
    from {{ ref('fct_trips_hourly') }} as t
    inner join recent as r on t.trip_date = r.date_day
    group by 1, 2
),

profile as (
    select
        station_code,
        trip_hour,
        entries,
        sum(entries) over (partition by station_code) as day_total,
        row_number() over (partition by station_code order by entries desc, trip_hour) as hour_rank
    from hourly
)

select
    station_code,
    trip_hour as peak_hour,
    entries / nullif(day_total, 0) as peak_hour_share,
    day_total / (select count(*) from recent) as avg_weekday_entries,
    percent_rank() over (order by day_total) as busyness_percentile
from profile
qualify hour_rank = 1
