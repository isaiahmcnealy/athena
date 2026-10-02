import re
from datetime import date, datetime
from typing import Literal
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, Field, field_validator


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = unquote(value.strip()).lower()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def arxiv_id(value: str) -> str:
    value = re.sub(r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/", "", value.strip())
    value = re.sub(r"\.pdf$", "", value)
    value = re.sub(r"v\d+$", "", value)
    if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})", value):
        raise ValueError("Invalid arXiv identifier")
    return value


class PaperRecord(BaseModel):
    source: Literal["arxiv", "openalex"]
    source_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=5000)
    abstract: str | None = Field(default=None, max_length=100000)
    authors: list[str] = Field(max_length=5000)
    topics: list[str] = Field(default_factory=list, max_length=100)
    venue: str | None = None
    publication_date: date
    landing_url: str
    doi: str | None = None
    arxiv: str | None = None
    work_type: str = Field(default="article", max_length=60)
    source_updated_at: datetime | None = None
    payload: dict

    @field_validator("title", "abstract", mode="before")
    @classmethod
    def clean_text(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("landing_url")
    @classmethod
    def safe_url(cls, value):
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise ValueError("Expected a public HTTPS source link")
        return value

    @field_validator("doi", mode="before")
    @classmethod
    def clean_doi(cls, value):
        return normalize_doi(value)
