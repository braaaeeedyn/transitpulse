# Thin wrapper: every target forwards to tasks.py so Windows (no make) and Linux/CI run the same commands.
T = uv run python tasks.py

.PHONY: lint fmt test web-data api web-test spark dbt dagster
lint: ; $(T) lint
fmt: ; $(T) fmt
test: ; $(T) test
web-data: ; $(T) web-data
api: ; $(T) api
web-test: ; $(T) web-test
spark: ; $(T) spark
dbt: ; $(T) dbt
dagster: ; $(T) dagster
