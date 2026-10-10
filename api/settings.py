from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]

WarehouseKind = Literal["none", "duckdb", "bigquery"]
AgentLLM = Literal["fake", "ollama", "gemini"]


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (prefix TP_) or a local .env file."""

    model_config = SettingsConfigDict(env_prefix="TP_", env_file=".env", extra="ignore")

    web_dir: Path = ROOT / "web"
    # Where the data endpoints read the dbt marts from. Explicit opt-in: with `none` (the default) every data
    # endpoint answers 503, whatever files exist on disk. Unset + TP_GCP_PROJECT set means `bigquery`.
    warehouse: WarehouseKind | None = None
    gcp_project: str | None = None
    duckdb_path: Path = Path("data/transitpulse.duckdb")  # relative paths are resolved from the repo root
    # Ask TransitPulse (POST /api/ask). Off unless TP_AGENT_ENABLED=true; the agent packages are imported only then.
    agent_enabled: bool = False
    agent_llm: AgentLLM = "fake"  # fake = deterministic test double; ollama (local) and gemini are opt-in
    ollama_model: str = "llama3.1:8b"
    ollama_url: str = "http://localhost:11434"
    gemini_model: str = (
        "gemini-2.5-flash"  # check the current model name; the key is read from GOOGLE_API_KEY
    )
    agent_max_bytes: int = (
        1_000_000_000  # per agent query: BigQuery dry run must be under this, then it's the cap
    )
    agent_row_limit: int = 200  # LIMIT added to (or clamped on) every agent query
    agent_rate_per_min: int = 10  # questions per client IP per minute
    agent_daily_bytes: int = 10_000_000_000  # per-process daily budget of BigQuery bytes for agent queries
    agent_timeout_s: float = 20.0  # DuckDB agent queries are interrupted after this
    # Behind Cloud Run's front end the client IP is the right-most X-Forwarded-For entry; elsewhere the header is
    # client-controlled, so it is only read when this is set.
    trust_proxy: bool = False
    # Origins allowed to call the API from a browser on another domain (comma-separated), e.g. the pages served at
    # https://braedynthompson.com/transitpulse/ calling the API on Cloud Run. Empty = same-origin only.
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

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
