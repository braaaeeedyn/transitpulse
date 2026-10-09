"""SQL guardrails (api/agent/guardrails.py) and the warehouses' agent execution paths (api/warehouse.py)."""

import concurrent.futures
from types import SimpleNamespace

import duckdb
import pytest

from api.agent.guardrails import GuardrailError, check_sql
from api.warehouse import AgentQueryError, BigQueryWarehouse, DuckDBWarehouse, QueryTooExpensive


def _code(sql: str, **kw) -> str:
    with pytest.raises(GuardrailError) as e:
        check_sql(sql, **kw)
    return e.value.code


def test_rejects_non_select():
    for sql in [
        "insert into marts.dim_date (date_day) values (date '2020-01-01')",
        "update marts.dim_station set station_name = 'x' where true",
        "delete from marts.fct_station_daily where true",
        "drop table marts.dim_date",
        "create table marts.x as select 1 as a",
        "merge marts.dim_date t using marts.dim_date s on false when not matched then insert row",
        "select * into marts.copy from marts.dim_date",
        "truncate table marts.dim_date",
    ]:
        assert _code(sql) == "not_select", sql
    assert _code("") == "empty"
    assert _code("selec * frm") in ("parse_error", "not_select")


def test_rejects_multiple_statements():
    assert _code("select * from marts.dim_date; drop table marts.dim_date") == "multiple_statements"
    assert _code("select 1 from marts.dim_date; select 2 from marts.dim_date") == "multiple_statements"
    # a trailing semicolon alone is fine
    assert check_sql("select date_day from marts.dim_date;").sql.startswith("SELECT date_day")


def test_rejects_tables_outside_allowlist():
    for sql in [
        "select * from raw.bart_od",
        "select * from staging.stg_bart_od",
        "select * from marts.fct_trips_hourly",  # 68M rows: not published to the agent
        "select * from `other-project.marts.dim_date`",
        "select * from marts.INFORMATION_SCHEMA.TABLES",
        "select * from INFORMATION_SCHEMA.SCHEMATA",
        "select * from secrets",
        "with a as (select * from raw.bart_od) select * from a",
        "select * from marts.dim_date where date_day in (select trip_date from raw.bart_od)",
    ]:
        assert _code(sql) == "table_not_allowed", sql
    # allowlisted marts, ml.forecast_runs, unqualified mart names and CTE names pass
    ok = check_sql(
        "with recent as (select * from mart_kpis_daily) select r.trip_date, f.mae_lgbm from recent as r "
        "cross join ml.forecast_runs as f"
    )
    assert ok.tables == ("marts.mart_kpis_daily", "ml.forecast_runs")
    assert "marts.mart_kpis_daily" in ok.sql


def test_rejects_table_functions_and_file_access():
    for sql in [
        "select * from read_csv('/etc/passwd')",
        "select * from read_parquet('data/parquet/**/*.parquet')",
        "select * from read_json_auto('x.json')",
        "select * from glob('*')",
        "select * from external_query('conn', 'select 1')",
        "select * from 'data/transitpulse.duckdb'",
        "select getenv('HOME') as h from marts.dim_date",
    ]:
        assert _code(sql) in ("blocked_function", "table_function", "table_not_allowed", "parse_error"), sql


def test_adds_and_clamps_limit():
    assert check_sql("select * from marts.dim_date", row_limit=50).sql.endswith("LIMIT 50")
    assert check_sql("select * from marts.dim_date limit 10", row_limit=50).sql.endswith("LIMIT 10")
    assert check_sql("select * from marts.dim_date limit 100000", row_limit=50).sql.endswith("LIMIT 50")
    union = check_sql(
        "select date_day from marts.dim_date union all select trip_date from marts.mart_kpis_daily",
        row_limit=7,
    )
    assert union.sql.endswith("LIMIT 7")


def test_transpiles_and_qualifies_for_bigquery():
    sql = (
        "select format_date('%Y-%m', trip_date) as month, safe_divide(sum(entries), count(*)) as per_day "
        "from marts.fct_station_daily group by 1"
    )
    bq = check_sql(sql, dialect="bigquery", project="transitpulse-511002").sql
    assert "`transitpulse-511002.marts.fct_station_daily`" in bq
    assert "FORMAT_DATE" in bq
    duck = check_sql(sql, dialect="duckdb").sql
    assert "FROM marts.fct_station_daily" in duck
    assert "STRFTIME" in duck and "FORMAT_DATE" not in duck
    with pytest.raises(GuardrailError):
        check_sql(sql, dialect="bigquery", project=None)


class _FakeJob:
    def __init__(self, processed: int):
        self.total_bytes_processed = processed
        self.total_bytes_billed = processed

    def result(self, timeout=None):
        return SimpleNamespace(schema=[SimpleNamespace(name="n")], __iter__=None)


class _FakeClient:
    def __init__(self, estimate: int):
        self.estimate = estimate
        self.calls = []

    def query(self, sql, job_config=None, location=None):
        self.calls.append(job_config)
        return _FakeJob(self.estimate)


def test_bigquery_dry_run_rejects_over_cap():
    client = _FakeClient(estimate=2_000_000_000)
    wh = BigQueryWarehouse("p", client=client)
    with pytest.raises(QueryTooExpensive) as e:
        wh.agent_dry_run("SELECT 1 FROM `p.marts.dim_date`", max_bytes=1_000_000_000)
    assert e.value.bytes_processed == 2_000_000_000
    (config,) = client.calls  # only the dry run; nothing was executed
    assert config.dry_run is True
    assert config.use_query_cache is False

    client = _FakeClient(estimate=5_000)
    wh = BigQueryWarehouse("p", client=client)
    assert wh.agent_dry_run("SELECT 1 FROM `p.marts.dim_date`", max_bytes=1_000_000_000) == 5_000


class _SlowJob:
    """A BigQuery job that never finishes within the client-side timeout."""

    def __init__(self):
        self.cancelled = False

    def result(self, timeout=None):
        raise concurrent.futures.TimeoutError()

    def cancel(self):
        self.cancelled = True
        raise RuntimeError("cancel failed")  # cancel errors are ignored


class _SlowClient:
    def __init__(self):
        self.calls = []
        self.job = _SlowJob()

    def query(self, sql, job_config=None, location=None):
        self.calls.append(job_config)
        return self.job


def test_bigquery_agent_query_timeout_is_capped_and_reported():
    client = _SlowClient()
    wh = BigQueryWarehouse("p", client=client)
    with pytest.raises(AgentQueryError, match=r"took longer than 2.5 s"):
        wh.agent_query("SELECT 1 FROM `p.marts.dim_date`", max_bytes=1_000_000_000, timeout_s=2.5)
    (config,) = client.calls
    # BigQuery stops the job itself (the library stores the value as a string)
    assert int(config.job_timeout_ms) == 2500
    assert config.maximum_bytes_billed == 1_000_000_000
    assert client.job.cancelled is True


def test_duckdb_agent_connection_blocks_external_access(tmp_path):
    db = tmp_path / "wh.duckdb"
    outside = tmp_path / "outside.csv"
    outside.write_text("a\n1\n")
    con = duckdb.connect(str(db))
    con.execute("create schema marts; create table marts.t as select 1 as a")
    con.close()
    wh = DuckDBWarehouse(db)
    assert wh.agent_query("select a from marts.t", 0, 5).rows == [(1,)]
    # even SQL that slipped past the guardrails can't read files, attach databases or re-enable access
    for sql in [
        f"select * from read_csv('{outside.as_posix()}')",
        f"attach '{(tmp_path / 'other.duckdb').as_posix()}' as other",
        "set enable_external_access = true",
        "create table marts.x as select 1",  # read-only
    ]:
        with pytest.raises(AgentQueryError):
            wh.agent_query(sql, 0, 5)
    with pytest.raises(AgentQueryError):
        wh.agent_dry_run("select missing_column from marts.t", 0)
