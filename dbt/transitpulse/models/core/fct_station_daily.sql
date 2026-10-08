{{
    config(
        partition_by={'field': 'trip_date', 'data_type': 'date', 'granularity': 'month'} if target.type == 'bigquery' else none,
        cluster_by=['station_code'] if target.type == 'bigquery' else none,
    )
}}
-- Fact: entries (trips starting here) and exits (trips ending here) per station per day.
with entries as (
    select trip_date, origin_code as station_code, sum(trips) as entries
    from {{ ref('fct_trips_hourly') }}
    group by 1, 2
),

exits as (
    select trip_date, destination_code as station_code, sum(trips) as exits
    from {{ ref('fct_trips_hourly') }}
    group by 1, 2
)

select
    coalesce(e.trip_date, x.trip_date) as trip_date,
    coalesce(e.station_code, x.station_code) as station_code,
    coalesce(e.entries, 0) as entries,
    coalesce(x.exits, 0) as exits
from entries as e
full outer join exits as x
    on e.trip_date = x.trip_date and e.station_code = x.station_code
