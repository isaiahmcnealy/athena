import base64
import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import column, exists, func, select, tuple_
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Session, selectinload

from athena.models import Paper, SourceRecord


class CatalogQuery(BaseModel):
    q: str = Field(default="", max_length=300)
    source: Literal["", "arxiv", "openalex"] = ""
    year: int | None = Field(default=None, ge=1900, le=2100)
    venue: str = Field(default="", max_length=200)
    limit: int = Field(default=12, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1024)

    @field_validator("year", mode="before")
    @classmethod
    def blank_year(cls, value):
        return None if value == "" else value


class SourceInfo(BaseModel):
    source: str
    source_id: str
    fetched_at: datetime


class PaperView(BaseModel):
    id: uuid.UUID
    title: str
    abstract: str | None
    authors: list[str]
    topics: list[str]
    venue: str | None
    publication_date: date
    primary_source: str
    landing_url: str
    doi: str | None
    work_type: str
    updated_at: datetime
    sources: list[SourceInfo]

    @classmethod
    def from_paper(cls, paper: Paper):
        data = {field: getattr(paper, field) for field in cls.model_fields if field != "sources"}
        data["sources"] = [
            SourceInfo(source=r.source, source_id=r.source_id, fetched_at=r.fetched_at)
            for r in sorted(paper.records, key=lambda r: r.source)
        ]
        return cls(**data)


class PaperPage(BaseModel):
    items: list[PaperView]
    total: int
    next_cursor: str | None


def fingerprint(query: CatalogQuery) -> str:
    fields = query.model_dump(exclude={"cursor", "limit"})
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]


def decode_cursor(cursor: str, query: CatalogQuery) -> tuple[date, uuid.UUID, datetime]:
    try:
        data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if data["v"] != 1 or data["filter"] != fingerprint(query):
            raise ValueError
        snapshot = datetime.fromisoformat(data["snapshot"])
        if snapshot.tzinfo is None:
            raise ValueError
        return date.fromisoformat(data["date"]), uuid.UUID(data["id"]), snapshot
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as error:
        raise ValueError("Invalid cursor or cursor does not match the current filters") from error


def list_papers(session: Session, query: CatalogQuery) -> PaperPage:
    conditions = []
    if query.q.strip():
        conditions.append(
            column("search_document", TSVECTOR).op("@@")(
                func.websearch_to_tsquery("english", query.q.strip())
            )
        )
    if query.source:
        conditions.append(
            exists(
                select(SourceRecord.paper_id).where(
                    SourceRecord.paper_id == Paper.id, SourceRecord.source == query.source
                )
            )
        )
    if query.year:
        conditions.extend(
            [
                Paper.publication_date >= date(query.year, 1, 1),
                Paper.publication_date < date(query.year + 1, 1, 1),
            ]
        )
    if query.venue.strip():
        conditions.append(Paper.venue.icontains(query.venue.strip(), autoescape=True))
    snapshot = datetime.now(UTC)
    position = None
    if query.cursor:
        published, paper_id, snapshot = decode_cursor(query.cursor, query)
        position = tuple_(Paper.publication_date, Paper.id) < tuple_(published, paper_id)
    conditions.append(Paper.created_at <= snapshot)
    total = session.scalar(select(func.count()).select_from(Paper).where(*conditions))
    statement = select(Paper).options(selectinload(Paper.records)).where(*conditions)
    if position is not None:
        statement = statement.where(position)
    rows = session.scalars(
        statement.order_by(Paper.publication_date.desc(), Paper.id.desc()).limit(query.limit + 1)
    ).all()
    next_cursor = None
    if len(rows) > query.limit:
        last = rows[query.limit - 1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "v": 1,
                    "date": last.publication_date.isoformat(),
                    "id": str(last.id),
                    "snapshot": snapshot.isoformat(),
                    "filter": fingerprint(query),
                }
            ).encode()
        ).decode()
    return PaperPage(
        items=[PaperView.from_paper(p) for p in rows[: query.limit]],
        total=total,
        next_cursor=next_cursor,
    )
