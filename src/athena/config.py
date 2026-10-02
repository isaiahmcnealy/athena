from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://athena:athena@localhost:5433/athena"
    openalex_api_key: SecretStr = SecretStr("")
    contact_email: str = ""
    # Comma-separated Host headers to accept; "*" accepts any (local development).
    allowed_hosts: str = "*"
    # Requests per client per minute for pages and the API; 0 disables the limit.
    rate_limit_per_minute: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
