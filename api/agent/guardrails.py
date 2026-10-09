"""SQL guardrails for the agent: the LLM's SQL is parsed (BigQuery dialect), checked against an allowlist and only
then run. Anything that isn't one read-only SELECT over the published marts is rejected with a GuardrailError.

What passes:
  * exactly one statement: a SELECT, optionally with WITH, or a UNION/INTERSECT/EXCEPT of SELECTs
  * tables from ALLOWED_TABLES only (marts.<table>, plus ml.forecast_runs), unqualified or schema-qualified;
    CTE names are fine
What doesn't: DML/DDL, SELECT INTO, other projects/datasets (raw, staging), INFORMATION_SCHEMA, table functions and
anything that reads files or external sources (read_csv, read_parquet, glob, external_query, ...).

The query then gets a LIMIT (or has its LIMIT clamped), is transpiled to the warehouse's dialect and its tables are
qualified for that warehouse (`project.marts.x` on BigQuery, marts.x on DuckDB).
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

MARTS = (
    "dim_date",
    "dim_station",
    "fct_station_daily",
    "fct_bike_trips_daily",
    "mart_kpis_daily",
    "mart_recovery",
    "mart_peak_load",
    "mart_od_flows",
    "mart_ridership_monthly",
    "mart_bikes_vs_trains",
    "forecast_station_daily",
)
ALLOWED_TABLES = frozenset({("marts", t) for t in MARTS} | {("ml", "forecast_runs")})

# functions that read files, URLs, other databases or system state; any of them rejects the query
BLOCKED_FUNCTIONS = frozenset(
    {
        "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto", "read_ndjson", "read_text",
        "read_blob", "parquet_scan", "csv_scan", "glob", "external_query", "query_table", "sniff_csv",
        "iceberg_scan", "delta_scan", "sqlite_scan", "postgres_scan", "mysql_scan", "httpfs", "getenv",
        "current_setting", "duckdb_settings", "duckdb_tables", "duckdb_columns", "duckdb_databases", "pragma",
        "session_user", "ml.predict", "vector_search",
    }
)  # fmt: skip
BLOCKED_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter, exp.Command, exp.Into,
    exp.Copy, exp.Pragma, exp.Set, exp.Use, exp.Attach, exp.Detach, exp.Export, exp.TruncateTable, exp.Grant,
    exp.LoadData, exp.Transaction, exp.Commit, exp.Rollback,
)  # fmt: skip
FILE_READERS = (exp.ReadCSV, exp.ReadParquet)


class GuardrailError(Exception):
    """The SQL was rejected. `code` is machine-readable, `message` is safe to show (and to give the LLM)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CheckedSQL:
    sql: str  # what runs, in the target dialect, tables qualified, LIMIT applied
    tables: tuple[str, ...]  # schema.table names it reads


def _func_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return (node.sql_name() if isinstance(node, exp.Func) else node.key).lower()


def _parse(sql: str) -> exp.Expression:
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise GuardrailError("empty", "No SQL was written.")
    try:
        statements = [s for s in sqlglot.parse(text, read="bigquery") if s is not None]
    except (ParseError, TokenError) as e:
        raise GuardrailError(
            "parse_error", f"The SQL couldn't be parsed: {str(e).splitlines()[0][:200]}"
        ) from e
    if len(statements) != 1:
        raise GuardrailError("multiple_statements", "Only one SQL statement is allowed.")
    return statements[0]


def _check_shape(tree: exp.Expression) -> None:
    if not isinstance(tree, exp.Select | exp.SetOperation):
        raise GuardrailError("not_select", "Only SELECT queries are allowed.")
    for node in tree.walk():
        if isinstance(node, BLOCKED_NODES):
            raise GuardrailError("not_select", "Only read-only SELECT queries are allowed.")
        if isinstance(node, FILE_READERS):
            raise GuardrailError("blocked_function", "Reading files or external sources isn't allowed.")
        if isinstance(node, exp.Func | exp.Anonymous) and _func_name(node) in BLOCKED_FUNCTIONS:
            raise GuardrailError("blocked_function", f"The function {_func_name(node)} isn't allowed.")


def _check_tables(tree: exp.Expression) -> list[tuple[exp.Table, tuple[str, str]]]:
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    allowed_names = {name: schema for schema, name in ALLOWED_TABLES}
    found = []
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise GuardrailError("table_function", "Table functions aren't allowed; read the marts tables.")
        catalog, db, name = table.catalog.lower(), table.db.lower(), table.name.lower()
        if "information_schema" in (catalog, db) or name.startswith("information_schema"):
            raise GuardrailError("table_not_allowed", "INFORMATION_SCHEMA isn't available.")
        if catalog:
            raise GuardrailError("table_not_allowed", f"Use marts.{name}, without a project name.")
        if not db and name in ctes:
            continue
        key = (db or allowed_names.get(name, ""), name)
        if key not in ALLOWED_TABLES:
            shown = f"{db}.{name}" if db else name
            raise GuardrailError("table_not_allowed", f"The table {shown} isn't one of the published tables.")
        found.append((table, key))
    if not found:
        raise GuardrailError("no_tables", "The query must read at least one of the published tables.")
    return found


def _apply_limit(tree: exp.Expression, row_limit: int) -> exp.Expression:
    limit = tree.args.get("limit")
    if limit is None:
        return tree.limit(row_limit, copy=False)
    value = limit.expression
    if isinstance(value, exp.Literal) and value.is_int and int(value.this) <= row_limit:
        return tree
    return tree.limit(row_limit, copy=False)


def check_sql(
    sql: str, *, dialect: str = "duckdb", project: str | None = None, row_limit: int = 200
) -> CheckedSQL:
    """Validate the LLM's BigQuery-dialect SQL and return what to run on `dialect` (duckdb or bigquery)."""
    tree = _parse(sql)
    _check_shape(tree)
    tables = _check_tables(tree)
    tree = _apply_limit(tree, row_limit)
    for table, (schema, name) in tables:
        if dialect == "bigquery":
            if not project:
                raise GuardrailError("config", "No BigQuery project is configured.")
            # one backticked path, `project.marts.x`, as BigQuery's docs write it
            table.set("this", exp.to_identifier(f"{project}.{schema}.{name}", quoted=True))
            table.set("db", None)
            table.set("catalog", None)
        else:
            table.set("this", exp.to_identifier(name))
            table.set("db", exp.to_identifier(schema))
    return CheckedSQL(
        sql=tree.sql(dialect=dialect), tables=tuple(sorted({f"{s}.{n}" for _, (s, n) in tables}))
    )
