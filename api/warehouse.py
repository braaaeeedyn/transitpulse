"""Read-only access to the dbt marts, in DuckDB (local build) or BigQuery (the real warehouse).

Endpoint SQL is dialect-neutral (plain SELECT ... WHERE ... ORDER BY ... LIMIT) and uses named parameters written
`@name`; anything dialect-specific lives in the dbt models. Tables are referenced through `table()`, which adds the
right qualifier for the backend.
"""

import datetime as dt
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from api.settings import get_settings

BQ_LOCATION = "us-west1"
BQ_MAX_BYTES_BILLED = 100_000_000  # 100 MB per API query; the marts the site reads are a few MB

_PARAM = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")


def _plain(value: Any) -> Any:
    # NUMERIC/DECIMAL columns come back as Decimal, which JSON would turn into a string
    return float(value) if isinstance(value, Decimal) else value


class TableNotFound(Exception):
    """The query referenced a table that doesn't exist (yet), e.g. forecasts before the first model run."""


class Warehouse(Protocol):
    # identifies the data source, so cached results from one warehouse are never served for another
    cache_key: str

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def table(self, name: str, schema: str = "marts") -> str: ...


class DuckDBWarehouse:
    """The local DuckDB file dbt builds. A read-only connection is opened per query and closed straight away,
    so the API holds the file lock only briefly (on Windows a held lock blocks dbt and the forecast writer)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.cache_key = f"duckdb:{self.path}"

    def table(self, name: str, schema: str = "marts") -> str:
        return f"{schema}.{name}"

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        import duckdb

        con = duckdb.connect(str(self.path), read_only=True)
        try:
            cur = con.execute(_PARAM.sub(r"$\1", sql), params or {})
            cols = [d[0] for d in cur.description]
            return [{c: _plain(v) for c, v in zip(cols, row, strict=True)} for row in cur.fetchall()]
        except duckdb.CatalogException as e:
            raise TableNotFound(str(e)) from e
        finally:
            con.close()


def _bq_type(value: Any) -> str:
    # bool before int: bool is a subclass of int
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT64"
    if isinstance(value, float):
        return "FLOAT64"
    if isinstance(value, dt.datetime):
        return "TIMESTAMP"
    if isinstance(value, dt.date):
        return "DATE"
    return "STRING"


class BigQueryWarehouse:
    """BigQuery marts. Parameters are typed (BigQuery won't compare INT64 with a quoted string) and every query
    has a bytes-billed cap, so a mistake fails instead of costing money."""

    def __init__(self, project: str, client: Any = None):
        self.project = project
        self.cache_key = f"bigquery:{project}"
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from google.cloud import bigquery

            self._client = bigquery.Client(project=self.project, location=BQ_LOCATION)
        return self._client

    def table(self, name: str, schema: str = "marts") -> str:
        return f"`{self.project}.{schema}.{name}`"

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from google.api_core.exceptions import NotFound
        from google.cloud import bigquery

        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(name, _bq_type(value), value)
                for name, value in (params or {}).items()
            ],
            maximum_bytes_billed=BQ_MAX_BYTES_BILLED,
            use_legacy_sql=False,
        )
        try:
            rows = self.client.query(sql, job_config=config, location=BQ_LOCATION).result()
        except NotFound as e:
            raise TableNotFound(str(e)) from e
        return [{k: _plain(v) for k, v in row.items()} for row in rows]


@lru_cache
def _make(kind: str, duckdb_file: str, project: str | None) -> Warehouse | None:
    if kind == "duckdb":
        return DuckDBWarehouse(Path(duckdb_file))
    if kind == "bigquery" and project:
        return BigQueryWarehouse(project)
    return None


def get_warehouse() -> Warehouse | None:
    """The configured warehouse, or None when the site isn't connected to one (TP_WAREHOUSE=none)."""
    s = get_settings()
    return _make(s.warehouse_kind, str(s.duckdb_file), s.gcp_project)
