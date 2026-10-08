"""Read station history from the warehouse and write the forecast outputs back.

Outputs:
  marts.forecast_station_daily  the latest run only (replaced each run): one row per station × forecast day
  ml.forecast_runs              one row per run, appended: data window, validation metrics with CIs, params
Local mode writes both into the DuckDB file dbt builds; `bigquery` mode loads them into BigQuery.
"""

from pathlib import Path

import pandas as pd

HISTORY_SQL = "select trip_date, station_code, entries from {table} order by trip_date, station_code"


def read_history(warehouse: str, duckdb_path: Path | None = None, project: str | None = None) -> pd.DataFrame:
    if warehouse == "duckdb":
        import duckdb

        con = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            return con.execute(HISTORY_SQL.format(table="marts.fct_station_daily")).df()
        finally:
            con.close()
    if warehouse == "bigquery":
        from google.cloud import bigquery

        client = bigquery.Client(project=project, location="us-west1")
        sql = HISTORY_SQL.format(table=f"`{project}.marts.fct_station_daily`")
        config = bigquery.QueryJobConfig(maximum_bytes_billed=200_000_000)
        return client.query(sql, job_config=config).to_dataframe()
    raise ValueError(f"unknown warehouse {warehouse!r}")


def write_outputs(
    warehouse: str,
    forecast: pd.DataFrame,
    run: pd.DataFrame,
    duckdb_path: Path | None = None,
    project: str | None = None,
) -> None:
    if warehouse == "duckdb":
        import duckdb

        con = duckdb.connect(str(duckdb_path))
        try:
            con.execute("create schema if not exists marts")
            con.execute("create schema if not exists ml")
            con.register("forecast_df", forecast)
            con.register("run_df", run)
            con.execute("begin")
            con.execute("create or replace table marts.forecast_station_daily as select * from forecast_df")
            con.execute("create table if not exists ml.forecast_runs as select * from run_df where false")
            con.execute("insert into ml.forecast_runs by name select * from run_df")
            con.execute("commit")
        finally:
            con.close()
        return
    if warehouse == "bigquery":
        from google.cloud import bigquery

        client = bigquery.Client(project=project, location="us-west1")
        client.load_table_from_dataframe(
            forecast,
            f"{project}.marts.forecast_station_daily",
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
        ).result()
        client.load_table_from_dataframe(
            run,
            f"{project}.ml.forecast_runs",
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"),
        ).result()
        return
    raise ValueError(f"unknown warehouse {warehouse!r}")
