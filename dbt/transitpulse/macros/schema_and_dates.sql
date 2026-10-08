{#- Use the custom schema name as-is (staging / marts), except in CI where everything goes to the ci dataset. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if target.name == 'ci' or custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}


{#- Cross-database date helpers: BigQuery and DuckDB spell these differently. -#}

{#- ISO week number (1-53) -#}
{% macro iso_week(d) %}{{ return(adapter.dispatch('iso_week', 'transitpulse')(d)) }}{% endmacro %}
{% macro bigquery__iso_week(d) %}extract(isoweek from {{ d }}){% endmacro %}
{% macro default__iso_week(d) %}cast(strftime({{ d }}, '%V') as integer){% endmacro %}

{#- Day of week, 1 = Sunday ... 7 = Saturday (BigQuery convention, matches the Spark output) -#}
{% macro day_of_week(d) %}{{ return(adapter.dispatch('day_of_week', 'transitpulse')(d)) }}{% endmacro %}
{% macro bigquery__day_of_week(d) %}extract(dayofweek from {{ d }}){% endmacro %}
{% macro default__day_of_week(d) %}(dayofweek({{ d }}) + 1){% endmacro %}

{#- One row per day between two dates (inclusive), column date_day -#}
{% macro date_spine(start_date, end_date) %}{{ return(adapter.dispatch('date_spine', 'transitpulse')(start_date, end_date)) }}{% endmacro %}
{% macro bigquery__date_spine(start_date, end_date) %}
    select d as date_day from unnest(generate_date_array({{ start_date }}, {{ end_date }})) as d
{% endmacro %}
{% macro default__date_spine(start_date, end_date) %}
    select cast(range as date) as date_day
    from range(cast({{ start_date }} as timestamp), cast({{ end_date }} as timestamp) + interval 1 day, interval 1 day)
{% endmacro %}

{#- Incremental strategy that rewrites whole date partitions on each adapter -#}
{% macro partition_overwrite_strategy() %}{{ return('insert_overwrite' if target.type == 'bigquery' else 'delete+insert') }}{% endmacro %}
