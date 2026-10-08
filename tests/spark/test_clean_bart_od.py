"""PySpark job unit tests on a tiny fixture (marked `spark`: needs Java + pyspark)."""

import json

import pytest

pyspark = pytest.importorskip("pyspark")
pytestmark = pytest.mark.spark

from pyspark.sql import SparkSession  # noqa: E402

from pipeline.spark.clean_bart_od import run  # noqa: E402

FIXTURE_A = """\
2025-07-03,8,EMBR,MONT,40
2025-07-03,8,EMBR,MONT,40
2025-07-04,9, embr ,POWL,12
2025-07-04,25,EMBR,POWL,3
2025-07-04,9,EMBR,XX,3
2025-07-04,9,EMBR,POWL,0
not-a-date,9,EMBR,POWL,5
2025-07-04,9,EMBR,POWL
2025-07-05,7,DALY,BALB,abc
"""
# a re-published file with a corrected count for one key
FIXTURE_B = """\
2025-07-03,8,EMBR,MONT,41
"""


@pytest.fixture(scope="module")
def spark():
    s = SparkSession.builder.master("local[1]").config("spark.sql.shuffle.partitions", "2").getOrCreate()
    yield s
    s.stop()


def test_clean_job(spark, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "a-2025.csv").write_text(FIXTURE_A)
    (raw / "b-2025.csv").write_text(FIXTURE_B)
    out = tmp_path / "parquet"
    audit = run(spark, str(raw / "*.csv"), str(out), str(tmp_path / "audit"))

    assert audit["rows_in"] == 10
    assert audit["dropped"] == {
        "bad_date": 1,
        "bad_destination": 1,
        "bad_hour": 1,
        "bad_trips": 1,  # non-numeric count
        "duplicate": 2,  # exact repeat + superseded count
        "malformed_row": 1,  # missing column -> Spark's corrupt-record column
        "non_positive_trips": 1,
    }
    assert audit["rows_out"] == 2
    assert json.loads((tmp_path / "audit" / "audit.json").read_text())["rows_out"] == 2

    rows = {(r.origin, r.destination): r for r in spark.read.parquet(str(out)).collect()}
    assert rows[("EMBR", "MONT")].trips == 41  # the latest file wins
    july4 = rows[("EMBR", "POWL")]  # " embr " was trimmed + upper-cased
    assert july4.is_holiday and july4.holiday == "Independence Day"
    assert july4.weekday == 6  # Friday (1 = Sunday)
    assert not rows[("EMBR", "MONT")].is_holiday
    assert (out / "year=2025" / "month=7").is_dir()
