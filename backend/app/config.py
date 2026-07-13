"""Application settings, loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MINILP_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://minilp:minilp@localhost:5432/minilp"
    debug: bool = False


settings = Settings()
