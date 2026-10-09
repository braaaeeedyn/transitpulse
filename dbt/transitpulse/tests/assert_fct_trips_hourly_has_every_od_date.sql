-- Every date in the cleaned origin-destination data must be in the hourly fact. Guards against incremental runs
-- that skip a backfilled (older) year, which used to happen silently.
select distinct s.trip_date
from {{ ref('stg_bart_od') }} as s
left join (select distinct trip_date from {{ ref('fct_trips_hourly') }}) as f
    on s.trip_date = f.trip_date
where f.trip_date is null
