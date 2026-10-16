# Thin wrapper: every target forwards to tasks.py so Windows (no make) and Linux/CI run the same commands.
T = uv run python tasks.py

.PHONY: lint fmt test web-data api up web-test screenshots lighthouse spark dbt dagster
lint: ; $(T) lint
fmt: ; $(T) fmt
test: ; $(T) test
web-data: ; $(T) web-data
api: ; $(T) api
up: ; $(T) up
web-test: ; $(T) web-test
screenshots: ; $(T) screenshots
lighthouse: ; $(T) lighthouse --runs 3 --assert
spark: ; $(T) spark
dbt: ; $(T) dbt
dagster: ; $(T) dagster
