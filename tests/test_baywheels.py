"""Bay Wheels discovery and cleaning (pipeline/baywheels.py) on small fixtures in tests/fixtures/baywheels/."""

import zipfile
from pathlib import Path

import duckdb

from pipeline import baywheels as bw

FIXTURES = Path(__file__).parent / "fixtures" / "baywheels"


def _zip(tmp_path: Path, csv_name: str, key: str) -> Path:
    """Zip a fixture CSV the way the bucket does (with a __MACOSX resource-fork entry)."""
    path = tmp_path / key
    with zipfile.ZipFile(path, "w") as z:
        z.write(FIXTURES / csv_name, key.split(".")[0] + ".csv")
        z.writestr("__MACOSX/._" + key.split(".")[0] + ".csv", b"\x00\x05\x16\x07junk")
    return path


def _read(out_root: Path, year: int, month: int) -> list[dict]:
    path = (out_root / f"year={year}" / f"month={month}" / "part-0.parquet").as_posix()
    rel = duckdb.sql(f"select * from read_parquet('{path}', hive_partitioning = false) order by started_at")
    return [dict(zip(rel.columns, row, strict=True)) for row in rel.fetchall()]


def test_bucket_listing_handles_irregular_names():
    objects, marker = bw.parse_listing((FIXTURES / "listing.xml").read_bytes())
    assert marker is None  # IsTruncated=false
    files = bw.monthly_files(objects)
    keys = {ym: o.key for ym, o in files.items()}
    assert keys[(2019, 1)] == "201901-fordgobike-tripdata.csv.zip"
    assert keys[(2022, 11)] == "202211-baywheeels-tripdata.csv.zip"  # the typo in the real bucket
    assert keys[(2025, 3)] == "202503-baywheels-tripdata.zip"  # no .csv in the name
    assert keys[(2026, 9)] == "202609-lyftbikes-tripdata.zip"
    assert (2020, 4) not in files and (2024, 12) not in files  # missing months stay missing
    assert all(ym[0] != 2017 for ym in files)  # the yearly 2017 file isn't a monthly file
    assert "index.html" not in keys.values()
    assert files[(2025, 3)].size == 13081611
    assert len(files[(2025, 3)].etag) == 32

    # pagination: a truncated page continues from its last key
    page1 = (
        (FIXTURES / "listing.xml")
        .read_text()
        .replace("<IsTruncated>false</IsTruncated>", "<IsTruncated>true</IsTruncated>")
    )
    empty = (
        '<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        "<IsTruncated>false</IsTruncated></ListBucketResult>"
    )
    urls = []

    def fetch(url):
        urls.append(url)
        return page1.encode() if len(urls) == 1 else empty.encode()

    assert len(bw.list_bucket("https://example.test/bucket", fetch=fetch)) == len(objects)
    assert urls[1] == "https://example.test/bucket?marker=index.html"


def test_clean_legacy_schema(tmp_path):
    z = _zip(tmp_path, "legacy.csv", "201901-fordgobike-tripdata.csv.zip")
    out = tmp_path / "parquet"
    audit = bw.clean_zip(z, 2019, 1, out)
    assert audit["schema_version"] == "legacy"
    assert audit["rows_in"] == 3 and audit["rows_out"] == 3
    assert sum(audit["dropped"].values()) == 0
    rows = _read(out, 2019, 1)
    assert list(rows[0]) == bw.OUTPUT_COLUMNS
    first, second, dockless = rows
    assert first["member_type"] == "member"  # Subscriber
    assert second["member_type"] == "casual"  # Customer
    assert first["rideable_type"] == "unknown"  # the legacy schema has no bike type
    assert first["start_station_id"] == "245" and first["end_station_name"] == "Fulton St at Bancroft Way"
    assert abs(first["duration_sec"] - 226.62) < 0.01
    assert str(first["trip_date"]) == "2019-01-01"
    assert first["source_file"] == "201901-fordgobike-tripdata.csv.zip"
    assert dockless["start_station_id"] is None and dockless["start_station_name"] is None  # "NULL" text
    assert len(first["ride_id"]) == 32  # deterministic hash of the source fields
    again = tmp_path / "again"
    bw.clean_zip(z, 2019, 1, again)
    assert [r["ride_id"] for r in _read(again, 2019, 1)] == [r["ride_id"] for r in rows]


def test_clean_lyft_schema(tmp_path):
    z = _zip(tmp_path, "lyft.csv", "202503-baywheels-tripdata.zip")
    out = tmp_path / "parquet"
    audit = bw.clean_zip(z, 2025, 3, out)
    assert audit["schema_version"] == "lyft"
    assert audit["rows_out"] == 3
    rows = {r["ride_id"]: r for r in _read(out, 2025, 3)}
    assert rows["FFCB0B7C5AAB3418"]["rideable_type"] == "electric_bike"
    assert rows["FFCB0B7C5AAB3418"]["start_station_id"] == "SJ-O10"
    assert rows["D76A01E90A788D05"]["member_type"] == "casual"
    dockless = rows["CA21CBB0978537B6"]
    assert dockless["start_station_id"] is None and dockless["end_station_name"] is None
    assert dockless["start_lat"] == 37.76
    assert {r["schema_version"] for r in rows.values()} == {"lyft"}

    # re-cleaning a month replaces only that month's partition
    (out / "year=2025" / "month=2").mkdir(parents=True)
    (out / "year=2025" / "month=2" / "part-0.parquet").write_bytes(b"keep me")
    bw.clean_zip(z, 2025, 3, out)
    assert (out / "year=2025" / "month=2" / "part-0.parquet").read_bytes() == b"keep me"
    assert len(_read(out, 2025, 3)) == 3


def test_drop_reasons_are_counted(tmp_path):
    z = _zip(tmp_path, "drops.csv", "202503-baywheels-tripdata.zip")
    audit = bw.clean_zip(z, 2025, 3, tmp_path / "parquet")
    assert audit["rows_in"] == 10
    assert audit["rows_out"] == 2
    assert audit["dropped"] == {
        "malformed_row": 1,
        "bad_timestamp": 1,
        "non_positive_duration": 1,
        "over_24h": 1,
        "missing_coordinates": 1,
        "outside_bay_area": 1,
        "outside_file_month": 1,
        "duplicate": 1,
    }
    assert audit["rows_in"] == audit["rows_out"] + sum(audit["dropped"].values())
    assert sorted(r["ride_id"] for r in _read(tmp_path / "parquet", 2025, 3)) == ["KEEP0001", "KEEP0002"]

    merged = bw.merge_audits({"2025-03": audit, "2025-04": audit})
    assert merged["rows_in"] == 20 and merged["dropped"]["duplicate"] == 2


def test_unknown_header_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        bw.detect_schema(["foo", "bar"])
    assert (
        bw.detect_schema(["Ride_ID", "started_at", "ended_at", "start_lat", "start_lng", "member_casual"])
        == "lyft"
    )
