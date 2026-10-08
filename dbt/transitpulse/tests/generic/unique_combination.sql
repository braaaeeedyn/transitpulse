{#- Generic test: no two rows share the same values in `columns` (same idea as dbt_utils, without adding a package). -#}
{% test unique_combination_of_columns(model, columns) %}
    select {{ columns | join(', ') }}, count(*) as n
    from {{ model }}
    group by {{ columns | join(', ') }}
    having count(*) > 1
{% endtest %}
