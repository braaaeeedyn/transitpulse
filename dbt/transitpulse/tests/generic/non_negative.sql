{#- Custom generic test (TRANSITPULSE_PLAN §5 Phase 1): ridership counts are never negative. -#}
{% test non_negative(model, column_name) %}
    select {{ column_name }} from {{ model }} where {{ column_name }} < 0
{% endtest %}
