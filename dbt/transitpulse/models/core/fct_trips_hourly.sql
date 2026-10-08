{{
    config(
        materialized='incremental',
        incremental_strategy=partition_overwrite_strategy(),
        unique_key=['trip_date'] if target.type != 'bigquery' else none,
        partition_by={'field': 'trip_date', 'data_type': 'date', 'granularity': 'day'} if target.type == 'bigquery' else none,
        cluster_by=['origin_code'] if target.type == 'bigquery' else none,
        on_schema_change='fail',
    )
}}
-- Fact: trips per hour per origin-destination pair, keyed to the station version valid on that day (SCD2 join).
-- Incremental: each run rewrites only the last 35 days of partitions (late corrections) plus anything new.
with od as (
    select * from {{ ref('stg_bart_od') }}
    {% if is_incremental() %}
    where trip_date >= (select cast({{ dbt.dateadd('day', -35, 'max(trip_date)') }} as date) from {{ this }})
    {% endif %}
),

stations as (
    select station_sk, station_code, valid_from, valid_to from {{ ref('dim_station') }}
)

select
    od.trip_date,
    od.trip_hour,
    od.origin_code,
    od.destination_code,
    o.station_sk as origin_sk,
    d.station_sk as destination_sk,
    od.trips
from od
left join stations as o
    on od.origin_code = o.station_code
    and cast(od.trip_date as {{ dbt.type_timestamp() }}) >= o.valid_from
    and cast(od.trip_date as {{ dbt.type_timestamp() }}) < o.valid_to
left join stations as d
    on od.destination_code = d.station_code
    and cast(od.trip_date as {{ dbt.type_timestamp() }}) >= d.valid_from
    and cast(od.trip_date as {{ dbt.type_timestamp() }}) < d.valid_to
