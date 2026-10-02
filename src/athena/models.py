import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list[str]] = mapped_column(JSONB)
    topics: Mapped[list[str]] = mapped_column(JSONB)
    venue: Mapped[str | None] = mapped_column(Text)
    publication_date: Mapped[date] = mapped_column()
    primary_source: Mapped[str] = mapped_column(String(20))
    landing_url: Mapped[str] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(Text)
    work_type: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    records: Mapped[list["SourceRecord"]] = relationship(back_populates="paper")
    __table_args__ = (Index("ix_papers_date_id", publication_date.desc(), id.desc()),)


class Identifier(Base):
    __tablename__ = "identifiers"
    scheme: Mapped[str] = mapped_column(String(20), primary_key=True)
    value: Mapped[str] = mapped_column(Text, primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id"), index=True)


class SourceRecord(Base):
    __tablename__ = "source_records"
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paper: Mapped[Paper] = relationship(back_populates="records")


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(20))
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="running")
    processed: Mapped[int] = mapped_column(default=0)
    inserted: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    rejected: Mapped[int] = mapped_column(default=0)
    last_source_id: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
