-- Typed view over the cleaned Bay Wheels trips. pipeline/baywheels.py already validated, de-duplicated and
-- normalised both source schemas; this layer fixes types so every adapter sees the same contract.
-- started_at / ended_at are Pacific clock times stored without a time zone (as published).
select
    cast(ride_id as {{ dbt.type_string() }}) as ride_id,
    cast(started_at as {{ dbt.type_timestamp() }}) as started_at,
    cast(ended_at as {{ dbt.type_timestamp() }}) as ended_at,
    cast(duration_sec as {{ dbt.type_float() }}) as duration_sec,
    cast(start_station_id as {{ dbt.type_string() }}) as start_station_id,
    cast(start_station_name as {{ dbt.type_string() }}) as start_station_name,
    cast(end_station_id as {{ dbt.type_string() }}) as end_station_id,
    cast(end_station_name as {{ dbt.type_string() }}) as end_station_name,
    cast(start_lat as {{ dbt.type_float() }}) as start_lat,
    cast(start_lng as {{ dbt.type_float() }}) as start_lng,
    cast(end_lat as {{ dbt.type_float() }}) as end_lat,
    cast(end_lng as {{ dbt.type_float() }}) as end_lng,
    cast(rideable_type as {{ dbt.type_string() }}) as rideable_type,
    cast(member_type as {{ dbt.type_string() }}) as member_type,
    start_station_id is null as is_dockless,
    cast(trip_date as date) as trip_date,
    cast(source_file as {{ dbt.type_string() }}) as source_file,
    cast(schema_version as {{ dbt.type_string() }}) as schema_version
from {{ source('raw', 'baywheels_trips') }}
