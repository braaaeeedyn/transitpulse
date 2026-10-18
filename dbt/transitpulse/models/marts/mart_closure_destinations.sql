-- Where riders from each station in the bart_closure_candidates seed go: its top 3 destinations by average
-- service-weekday trips in the period year of mart_station_closures (trips back to the same station left out).
with listed as (
    select station_code, period_year from {{ ref('mart_station_closures') }} where closure_group is not null
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
    inner join listed as l on t.origin_code = l.station_code
    group by 1, 2
),

with_totals as (
    select origin_code, destination_code, trips, sum(trips) over (partition by origin_code) as origin_trips
    from pairs
),

ranked as (
    select
        origin_code,
        destination_code,
        trips,
        origin_trips,
        row_number() over (partition by origin_code order by trips desc, destination_code) as destination_rank
    from with_totals
    where destination_code != origin_code
)

select
    r.origin_code,
    r.destination_code,
    coalesce(s.station_name, r.destination_code) as destination_name,
    l.period_year,
    r.trips / (select count(*) from days) as avg_weekday_trips,
    r.trips / nullif(r.origin_trips, 0) as share_of_origin_trips,
    r.destination_rank
from ranked as r
inner join listed as l on r.origin_code = l.station_code
left join {{ ref('dim_station') }} as s on r.destination_code = s.station_code and s.is_current
where r.destination_rank <= 3
