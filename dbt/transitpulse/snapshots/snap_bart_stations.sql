{#-
  SCD type 2 history of the station list. Each `dbt snapshot` run compares the latest GTFS observation with the
  current snapshot rows; a changed name or position closes the old row (dbt_valid_to) and opens a new one.
-#}
{% snapshot snap_bart_stations %}
    {{
        config(
            unique_key='station_code',
            strategy='check',
            check_cols=['station_name', 'lat', 'lon'],
            invalidate_hard_deletes=True,
        )
    }}
    select * from {{ ref('stg_bart_stations') }}
{% endsnapshot %}
