-- The evidence behind the site's station-closures band (docs/STATION_CLOSURES.md): one row per station with data in
-- the latest full calendar year, with its service-weekday trips (entries + exits), rank from the least used, recovery
-- vs the baseline year, change vs the year before, and the nearest station that stays open if every station in the
-- bart_closure_candidates seed closes (straight-line haversine distance, Earth radius 3958.8 miles).
with period as (
    -- the latest calendar year whose data reaches Dec 31
    select max(extract(year from trip_date)) as period_year
    from {{ ref('fct_station_daily') }}
    where extract(month from trip_date) = 12 and extract(day from trip_date) = 31
),

weekday_rows as (
    select f.station_code, d.year, f.trip_date, f.entries, f.exits
    from {{ ref('fct_station_daily') }} as f
    inner join {{ ref('dim_date') }} as d on f.trip_date = d.date_day
    cross join period as p
    where d.is_service_weekday
        and d.year in (p.period_year, p.period_year - 1, {{ var('baseline_year') }})
),

station_years as (
    select
        station_code,
        year,
        count(*) as days,
        avg(entries) as avg_entries,
        avg(exits) as avg_exits,
        avg(entries + exits) as avg_trips
    from weekday_rows
    group by 1, 2
),

systemwide as (
    select year, avg(total_entries) as avg_entries
    from (
        select trip_date, year, sum(entries) as total_entries from weekday_rows group by 1, 2
    ) as daily
    group by 1
),

stations as (
    select station_code, station_name, lat, lon from {{ ref('dim_station') }} where is_current
),

candidates as (
    select
        station_code,
        closure_group,
        case when trim(closure_segment) != '' then trim(closure_segment) end as closure_segment
    from {{ ref('bart_closure_candidates') }}
),

open_stations as (
    select s.station_code, s.station_name, s.lat, s.lon
    from stations as s
    left join candidates as c on s.station_code = c.station_code
    where c.station_code is null
),

distances as (
    select
        s.station_code,
        o.station_code as nearest_open_code,
        o.station_name as nearest_open_name,
        2 * 3958.8 * asin(sqrt(
            power(sin((o.lat - s.lat) * acos(-1) / 360), 2)
            + cos(s.lat * acos(-1) / 180) * cos(o.lat * acos(-1) / 180) * power(sin((o.lon - s.lon) * acos(-1) / 360), 2)
        )) as miles
    from stations as s
    cross join open_stations as o
    where o.station_code != s.station_code
),

nearest as (
    select station_code, nearest_open_code, nearest_open_name, miles as nearest_open_miles
    from distances
    where miles is not null
    qualify row_number() over (partition by station_code order by miles, nearest_open_code) = 1
),

latest as (
    select y.*, p.period_year
    from station_years as y
    inner join period as p on y.year = p.period_year
)

select
    l.station_code,
    coalesce(s.station_name, l.station_code) as station_name,
    c.closure_group,
    c.closure_segment,
    l.period_year,
    l.days as service_weekdays,
    l.avg_entries as avg_weekday_entries,
    l.avg_exits as avg_weekday_exits,
    l.avg_trips as avg_weekday_trips,
    rank() over (order by l.avg_trips) as rank_lowest,
    count(*) over () as stations_ranked,
    -- every trip has one entry, so systemwide entries = trips; entries + exits = trips that start or end here
    l.avg_trips / nullif(sl.avg_entries, 0) as share_of_weekday_trips,
    case when b.days >= 200 then b.avg_trips end as baseline_avg_weekday_trips,
    l.avg_trips / nullif(case when b.days >= 200 then b.avg_trips end, 0) as recovery_ratio,
    sl.avg_entries / nullif(sb.avg_entries, 0) as system_recovery_ratio,
    pr.avg_trips as prev_year_avg_weekday_trips,
    l.avg_trips / nullif(pr.avg_trips, 0) - 1 as change_vs_prev_year,
    n.nearest_open_code,
    n.nearest_open_name,
    n.nearest_open_miles
from latest as l
left join stations as s on l.station_code = s.station_code
left join candidates as c on l.station_code = c.station_code
left join station_years as b on l.station_code = b.station_code and b.year = {{ var('baseline_year') }}
left join station_years as pr on l.station_code = pr.station_code and pr.year = l.period_year - 1
left join systemwide as sl on sl.year = l.period_year
left join systemwide as sb on sb.year = {{ var('baseline_year') }}
left join nearest as n on l.station_code = n.station_code
