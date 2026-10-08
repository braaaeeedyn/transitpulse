from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]

WarehouseKind = Literal["none", "duckdb", "bigquery"]


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (prefix TP_) or a local .env file."""

    model_config = SettingsConfigDict(env_prefix="TP_", env_file=".env", extra="ignore")

    web_dir: Path = ROOT / "web"
    # Where the data endpoints read the dbt marts from. Explicit opt-in: with `none` (the default) every data
    # endpoint answers 503, whatever files exist on disk. Unset + TP_GCP_PROJECT set means `bigquery`.
    warehouse: WarehouseKind | None = None
    gcp_project: str | None = None
    duckdb_path: Path = Path("data/transitpulse.duckdb")  # relative paths are resolved from the repo root
    agent_enabled: bool = False

    @property
    def warehouse_kind(self) -> WarehouseKind:
        if self.warehouse is not None:
            return self.warehouse
        return "bigquery" if self.gcp_project else "none"

    @property
    def duckdb_file(self) -> Path:
        return self.duckdb_path if self.duckdb_path.is_absolute() else ROOT / self.duckdb_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
