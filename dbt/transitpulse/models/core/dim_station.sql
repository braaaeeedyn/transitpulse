-- Station dimension, SCD type 2 (one row per version of a station).
-- The first version of every station is back-dated to 1900 so trips from before the first snapshot still join.
with versions as (
    select
        *,
        row_number() over (partition by station_code order by dbt_valid_from) as version_number
    from {{ ref('snap_bart_stations') }}
)

select
    {{ dbt.hash(dbt.concat(["station_code", "'|'", dbt.cast("dbt_valid_from", dbt.type_string())])) }} as station_sk,
    station_code,
    station_name,
    lat,
    lon,
    version_number,
    case
        when version_number = 1 then cast('1900-01-01 00:00:00' as {{ dbt.type_timestamp() }})
        else dbt_valid_from
    end as valid_from,
    coalesce(dbt_valid_to, cast('9999-12-31 00:00:00' as {{ dbt.type_timestamp() }})) as valid_to,
    dbt_valid_to is null as is_current
from versions
