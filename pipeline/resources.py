"""Where the pipeline reads and writes, and how it runs Spark.

`mode=local` keeps everything under data/ and lets dbt's DuckDB target read the Parquet directly — the whole
pipeline runs on a laptop with no cloud account. `mode=gcp` uploads to the raw GCS bucket and loads BigQuery.
"""

import subprocess
from pathlib import Path

from dagster import ConfigurableResource, EnvVar

ROOT = Path(__file__).resolve().parents[1]


class Storage(ConfigurableResource):
    mode: str = "local"  # "local" | "gcp"
    data_root: str = str(ROOT / "data")
    gcp_project: str | None = None
    raw_bucket: str | None = None

    @property
    def root(self) -> Path:
        return Path(self.data_root)

    def path(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def upload(self, local: Path, blob: str) -> str | None:
        """Copy a local file to gs://raw_bucket/blob in gcp mode; no-op locally. Returns the gs:// URI."""
        if self.mode != "gcp":
            return None
        from google.cloud import storage

        bucket = storage.Client(project=self.gcp_project).bucket(self.raw_bucket)
        bucket.blob(blob).upload_from_filename(str(local))
        return f"gs://{self.raw_bucket}/{blob}"


class SparkRunner(ConfigurableResource):
    """Runs pipeline/spark jobs. `docker` uses pipeline/spark/Dockerfile (needed on Windows); `python` runs in-process
    on a machine with Java 17 (the Oracle VM)."""

    runner: str = "python"  # "python" | "docker"
    image: str = "transitpulse-spark"
    driver_memory: str = "4g"

    def run_module(self, module: str, *args: str) -> None:
        if self.runner == "docker":
            cmd = ["docker", "run", "--rm", "-v", f"{ROOT}:/app", self.image, "python", "-m", module, *args]
        else:
            cmd = ["python", "-m", module, *args]
        subprocess.run([*cmd, "--driver-memory", self.driver_memory], cwd=ROOT, check=True)


def default_resources() -> dict:
    return {
        "storage": Storage(
            mode=EnvVar("TP_PIPELINE_MODE").get_value("local") or "local",
            gcp_project=EnvVar("TP_GCP_PROJECT").get_value(),
            raw_bucket=EnvVar("TP_RAW_BUCKET").get_value(),
        ),
        "spark": SparkRunner(runner=EnvVar("TP_SPARK_RUNNER").get_value("python") or "python"),
    }
