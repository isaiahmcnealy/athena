from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://athena:athena@localhost:5433/athena"
    openalex_api_key: SecretStr = SecretStr("")
    contact_email: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
