-- Monthly trips per origin-destination pair, with month-over-month and year-over-year change and each
-- destination's rank among trips leaving the same origin.
with monthly as (
    select
        {{ dbt.date_trunc('month', 'trip_date') }} as month_start,
        origin_code,
        destination_code,
        sum(trips) as trips
    from {{ ref('fct_trips_hourly') }}
    group by 1, 2, 3
)

select
    m.month_start,
    m.origin_code,
    m.destination_code,
    m.trips,
    m.trips - lag(m.trips) over (
        partition by m.origin_code, m.destination_code order by m.month_start
    ) as trips_change_vs_prev_month,
    ly.trips as trips_same_month_last_year,
    (m.trips - ly.trips) / nullif(ly.trips, 0) as yoy_change,
    rank() over (partition by m.month_start, m.origin_code order by m.trips desc) as rank_from_origin
from monthly as m
left join monthly as ly
    on ly.origin_code = m.origin_code
    and ly.destination_code = m.destination_code
    and ly.month_start = {{ dbt.dateadd('year', -1, 'm.month_start') }}
