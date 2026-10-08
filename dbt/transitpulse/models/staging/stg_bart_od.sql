-- Typed, renamed view over the cleaned origin-destination data. Spark already de-duplicated and validated rows;
-- this layer only fixes types and names so every downstream model sees the same contract.
select
    cast(trip_date as date) as trip_date,
    cast(hour as {{ dbt.type_int() }}) as trip_hour,
    cast(origin as {{ dbt.type_string() }}) as origin_code,
    cast(destination as {{ dbt.type_string() }}) as destination_code,
    cast(trips as {{ dbt.type_int() }}) as trips,
    cast(weekday as {{ dbt.type_int() }}) as weekday,
    cast(is_holiday as boolean) as is_holiday,
    cast(holiday as {{ dbt.type_string() }}) as holiday_name
from {{ source('raw', 'bart_od') }}
