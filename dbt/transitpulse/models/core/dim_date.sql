-- Calendar dimension covering every day in the ridership data.
with bounds as (
    select min(trip_date) as first_day, max(trip_date) as last_day from {{ ref('stg_bart_od') }}
),

spine as (
    {{ date_spine("(select first_day from bounds)", "(select last_day from bounds)") }}
),

holidays as (
    select distinct trip_date, holiday_name from {{ ref('stg_bart_od') }} where is_holiday
)

select
    s.date_day,
    extract(year from s.date_day) as year,
    extract(month from s.date_day) as month,
    {{ iso_week('s.date_day') }} as iso_week,
    {{ day_of_week('s.date_day') }} as weekday,
    {{ day_of_week('s.date_day') }} in (1, 7) as is_weekend,
    h.trip_date is not null as is_holiday,
    h.holiday_name,
    {{ day_of_week('s.date_day') }} not in (1, 7) and h.trip_date is null as is_service_weekday,
    {{ dbt.date_trunc('month', 's.date_day') }} as month_start
from spine as s
left join holidays as h on s.date_day = h.trip_date
