-- How many service-weekday trips in the period year start or end at a listed station: the first 10 (closure group 1)
-- and all 15 (groups 1 and 2) of the bart_closure_candidates seed. A trip between two listed stations counts once.
with listed as (
    select station_code, closure_group, period_year
    from {{ ref('mart_station_closures') }}
    where closure_group is not null
),

days as (
    select d.date_day
    from {{ ref('dim_date') }} as d
    inner join (select distinct period_year from listed) as p on d.year = p.period_year
    where d.is_service_weekday
),

pairs as (
    select t.origin_code, t.destination_code, sum(t.trips) as trips
    from {{ ref('fct_trips_hourly') }} as t
    inner join days on t.trip_date = days.date_day
    group by 1, 2
),

scenarios as (
    select 'first_10' as scenario, 1 as max_group
    union all
    select 'all_15' as scenario, 2 as max_group
),

members as (
    select s.scenario, l.station_code
    from scenarios as s
    inner join listed as l on l.closure_group <= s.max_group
),

touching as (
    select
        s.scenario,
        sum(case when mo.station_code is not null or md.station_code is not null then p.trips else 0 end)
            as trips_touching,
        sum(p.trips) as trips
    from scenarios as s
    cross join pairs as p
    left join members as mo on mo.scenario = s.scenario and mo.station_code = p.origin_code
    left join members as md on md.scenario = s.scenario and md.station_code = p.destination_code
    group by 1
),

counts as (
    select scenario, count(*) as stations from members group by 1
)

select
    t.scenario,
    coalesce(c.stations, 0) as stations,
    (select max(period_year) from listed) as period_year,
    t.trips_touching / (select count(*) from days) as avg_weekday_trips_touching,
    t.trips / (select count(*) from days) as system_avg_weekday_trips,
    t.trips_touching / nullif(t.trips, 0) as share_of_weekday_trips
from touching as t
left join counts as c on t.scenario = c.scenario
