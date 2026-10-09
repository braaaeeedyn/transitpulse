{{
    config(
        partition_by={'field': 'trip_date', 'data_type': 'date', 'granularity': 'month'} if target.type == 'bigquery' else none,
    )
}}
-- Fact: Bay Wheels *bike* trips per day, split by rider type, bike type and docked vs dockless.
-- Non-bike vehicles in the feed (8 electric_scooter trips in Sept 2024) are excluded, so bikes-vs-trains counts bikes.
select
    trip_date,
    count(*) as trips,
    sum(case when member_type = 'member' then 1 else 0 end) as member_trips,
    sum(case when member_type = 'casual' then 1 else 0 end) as casual_trips,
    sum(case when rideable_type = 'electric_bike' then 1 else 0 end) as ebike_trips,
    sum(case when rideable_type in ('classic_bike', 'docked_bike') then 1 else 0 end) as classic_trips,
    sum(case when rideable_type = 'unknown' then 1 else 0 end) as unknown_type_trips,
    sum(case when is_dockless then 1 else 0 end) as dockless_trips,
    avg(duration_sec) / 60.0 as avg_duration_min
from {{ ref('stg_baywheels_trips') }}
where rideable_type != 'electric_scooter'
group by 1
