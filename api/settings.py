from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (prefix TP_) or a local .env file."""

    model_config = SettingsConfigDict(env_prefix="TP_", env_file=".env", extra="ignore")

    web_dir: Path = ROOT / "web"
    # Set once the warehouse (M1/M2) and the agent (M5) exist. While unset, those endpoints answer 503.
    gcp_project: str | None = None
    agent_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
