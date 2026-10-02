import base64
import hashlib
import json
import math
import uuid
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import REAL, cast, column, exists, func, null, select, tuple_
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Session, selectinload

from athena.ingestion.schemas import arxiv_id, normalize_doi
from athena.models import Identifier, Paper, SourceRecord

Ordering = Literal["relevance", "newest"]


def identifier_lookup(terms: str) -> tuple[str, str] | None:
    """A DOI or arXiv ID names one work; match the identifier instead of searching text."""
    doi = normalize_doi(terms)
    if doi:
        return "doi", doi
    try:
        return "arxiv", arxiv_id(terms.removeprefix("arXiv:").removeprefix("arxiv:"))
    except ValueError:
        return None


class CatalogQuery(BaseModel):
    q: str = Field(default="", max_length=300)
    sort: Literal["", "relevance", "newest"] = ""
    source: Literal["", "arxiv", "openalex"] = ""
    year: int | None = Field(default=None, ge=1900, le=2100)
    venue: str = Field(default="", max_length=200)
    limit: int = Field(default=12, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1024)

    @field_validator("year", mode="before")
    @classmethod
    def blank_year(cls, value):
        return None if value == "" else value

    @field_validator("q", "venue", mode="before")
    @classmethod
    def drop_nul(cls, value):
        # PostgreSQL text cannot hold NUL; passing one through would fail the whole query.
        return value.replace("\x00", "") if isinstance(value, str) else value

    @property
    def rankable(self) -> bool:
        terms = self.q.strip()
        return bool(terms) and identifier_lookup(terms) is None

    @property
    def ordering(self) -> Ordering:
        # A lexical score needs search terms; browsing and identifier lookups sort by date.
        return "relevance" if self.rankable and self.sort != "newest" else "newest"


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
    sort: Ordering


def fingerprint(query: CatalogQuery) -> str:
    fields = query.model_dump(exclude={"cursor", "limit"}) | {"sort": query.ordering}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]


def decode_cursor(
    cursor: str, query: CatalogQuery
) -> tuple[float | None, date, uuid.UUID, datetime]:
    try:
        data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if data["v"] != 1 or data["filter"] != fingerprint(query):
            raise ValueError
        snapshot = datetime.fromisoformat(data["snapshot"])
        if snapshot.tzinfo is None:
            raise ValueError
        score = float(data["score"]) if query.ordering == "relevance" else None
        if score is not None and not math.isfinite(score):
            raise ValueError
        return score, date.fromisoformat(data["date"]), uuid.UUID(data["id"]), snapshot
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError) as error:
        raise ValueError("Invalid cursor or cursor does not match the current filters") from error


def list_papers(session: Session, query: CatalogQuery) -> PaperPage:
    conditions = []
    terms = query.q.strip()
    lookup = identifier_lookup(terms)
    document = column("search_document", TSVECTOR)
    tsquery = func.websearch_to_tsquery("english", terms)
    if lookup:
        conditions.append(
            exists(
                select(Identifier.paper_id).where(
                    Identifier.paper_id == Paper.id,
                    Identifier.scheme == lookup[0],
                    Identifier.value == lookup[1],
                )
            )
        )
    elif terms:
        conditions.append(document.op("@@")(tsquery))
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
    # Relevance is PostgreSQL ts_rank: term frequency with title matches (weight A) counting
    # more than abstract matches (weight B). It is a lexical score, not a learned ranking.
    # Ties, and the "newest" ordering, fall back to publication date and then ID.
    by_relevance = query.ordering == "relevance"
    score = func.ts_rank(document, tsquery) if by_relevance else None
    keys = [Paper.publication_date, Paper.id]
    if by_relevance:
        keys.insert(0, score)
    snapshot = datetime.now(UTC)
    position = None
    if query.cursor:
        last_score, published, paper_id, snapshot = decode_cursor(query.cursor, query)
        after = [published, paper_id]
        if by_relevance:
            after.insert(0, cast(last_score, REAL))  # ts_rank returns REAL; compare exactly.
        position = tuple_(*keys) < tuple_(*after)
    conditions.append(Paper.created_at <= snapshot)
    total = session.scalar(select(func.count()).select_from(Paper).where(*conditions))
    statement = select(Paper, score if by_relevance else null()).where(*conditions)
    if position is not None:
        statement = statement.where(position)
    rows = session.execute(
        statement.options(selectinload(Paper.records))
        .order_by(*[key.desc() for key in keys])
        .limit(query.limit + 1)
    ).all()
    next_cursor = None
    if len(rows) > query.limit:
        last, last_score = rows[query.limit - 1]
        position_fields = {"score": last_score} if by_relevance else {}
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "v": 1,
                    **position_fields,
                    "date": last.publication_date.isoformat(),
                    "id": str(last.id),
                    "snapshot": snapshot.isoformat(),
                    "filter": fingerprint(query),
                }
            ).encode()
        ).decode()
    return PaperPage(
        items=[PaperView.from_paper(paper) for paper, _ in rows[: query.limit]],
        total=total,
        next_cursor=next_cursor,
        sort=query.ordering,
    )
