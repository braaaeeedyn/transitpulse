-- Latest observation of each station (input to the SCD2 snapshot).
select
    cast(station_code as {{ dbt.type_string() }}) as station_code,
    cast(station_name as {{ dbt.type_string() }}) as station_name,
    cast(lat as {{ dbt.type_float() }}) as lat,
    cast(lon as {{ dbt.type_float() }}) as lon,
    cast(feed_version as {{ dbt.type_string() }}) as feed_version,
    cast(observed_at as {{ dbt.type_timestamp() }}) as observed_at
from {{ source('raw', 'bart_stations') }}
qualify row_number() over (partition by station_code order by observed_at desc) = 1
