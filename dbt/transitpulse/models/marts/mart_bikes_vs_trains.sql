-- Monthly BART entries vs Bay Wheels trips, each also as an index vs the same calendar month of 2019 (= 100).
-- Full outer join of the two monthly series: bike months can extend past the BART data (and dim_date), and either
-- side may have months the other doesn't, so neither is inner-joined to the other or to dim_date.
with bart as (
    select
        cast({{ dbt.date_trunc('month', 'trip_date') }} as date) as month_start,
        sum(entries) as bart_entries,
        count(distinct trip_date) as bart_days
    from {{ ref('fct_station_daily') }}
    group by 1
),

bikes as (
    select
        cast({{ dbt.date_trunc('month', 'trip_date') }} as date) as month_start,
        sum(trips) as bike_trips,
        count(*) as bike_days
    from {{ ref('fct_bike_trips_daily') }}
    group by 1
),

joined as (
    select
        coalesce(b.month_start, k.month_start) as month_start,
        b.bart_entries,
        b.bart_days,
        k.bike_trips,
        k.bike_days,
        b.bart_entries / nullif(b.bart_days, 0) as bart_avg_daily_entries,
        k.bike_trips / nullif(k.bike_days, 0) as bike_avg_daily_trips
    from bart as b
    full outer join bikes as k on b.month_start = k.month_start
),

baseline as (
    select
        extract(month from month_start) as month_of_year,
        bart_avg_daily_entries as bart_baseline,
        bike_avg_daily_trips as bike_baseline
    from joined
    where extract(year from month_start) = {{ var('baseline_year') }}
)

select
    j.month_start,
    j.bart_entries,
    j.bart_days,
    j.bike_trips,
    j.bike_days,
    j.bart_avg_daily_entries,
    j.bike_avg_daily_trips,
    100 * j.bart_avg_daily_entries / nullif(base.bart_baseline, 0) as bart_index_2019,
    100 * j.bike_avg_daily_trips / nullif(base.bike_baseline, 0) as bike_index_2019,
    1000.0 * j.bike_trips / nullif(j.bart_entries, 0) as bikes_per_1000_bart_entries
from joined as j
left join baseline as base on extract(month from j.month_start) = base.month_of_year
