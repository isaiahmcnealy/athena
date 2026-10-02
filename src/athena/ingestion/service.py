from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from athena.ingestion.schemas import PaperRecord
from athena.models import Identifier, ImportRun, Paper, SourceRecord


class IdentityConflict(ValueError):
    pass


def upsert_paper(session: Session, record: PaperRecord) -> bool:
    # Serialize identity resolution across importers. The critical section is one
    # record, with no external I/O. Revisit at measured ingestion contention.
    session.execute(text("SELECT pg_advisory_xact_lock(734281)"))
    identifiers = {(record.source, record.source_id)}
    if record.doi:
        identifiers.add(("doi", record.doi))
    if record.arxiv:
        identifiers.add(("arxiv", record.arxiv))
    matches = session.scalars(
        select(Identifier).where(
            or_(
                *[
                    (Identifier.scheme == scheme) & (Identifier.value == value)
                    for scheme, value in identifiers
                ]
            )
        )
    ).all()
    paper_ids = {m.paper_id for m in matches}
    if len(paper_ids) > 1:
        raise IdentityConflict(
            "Identifiers resolve to different papers; manual reconciliation needed"
        )
    existing = session.get(SourceRecord, (record.source, record.source_id))
    if existing and record.source_updated_at and existing.source_updated_at:
        if record.source_updated_at < existing.source_updated_at:
            return False  # A replay of an old version must not roll metadata backward.

    now = datetime.now(UTC)
    created = not paper_ids
    paper = session.get(Paper, next(iter(paper_ids))) if paper_ids else Paper()
    # Canonical metadata is deterministic: arXiv owns its title/abstract/date;
    # OpenAlex owns papers without an arXiv record. Preserve both source records.
    if created or record.source == "arxiv" or paper.primary_source != "arxiv":
        for field in ("title", "authors", "publication_date", "landing_url", "work_type"):
            setattr(paper, field, getattr(record, field))
        paper.primary_source = record.source
        paper.abstract = record.abstract
    paper.topics = sorted(set((paper.topics or []) + record.topics))
    paper.venue = record.venue or paper.venue
    paper.doi = record.doi or paper.doi
    paper.updated_at = now
    session.add(paper)
    session.flush()
    known = {(m.scheme, m.value) for m in matches}
    for scheme, value in identifiers - known:
        session.add(Identifier(scheme=scheme, value=value, paper_id=paper.id))
    if existing is None:
        existing = SourceRecord(source=record.source, source_id=record.source_id, paper_id=paper.id)
    existing.payload = record.payload
    existing.fetched_at = now
    existing.source_updated_at = record.source_updated_at
    session.add(existing)
    return created


def run_import(engine, source: str, query: str, records: Iterable[PaperRecord]) -> dict:
    with Session(engine) as session, session.begin():
        run = ImportRun(source=source, query=query)
        session.add(run)
        session.flush()
        run_id = run.id
    try:
        for record in records:
            with Session(engine) as session, session.begin():
                run = session.get(ImportRun, run_id)
                try:
                    with session.begin_nested():
                        created = upsert_paper(session, record)
                    run.inserted += int(created)
                    run.updated += int(not created)
                except IdentityConflict as error:
                    run.rejected += 1
                    run.error = str(error)
                run.processed += 1
                run.last_source_id = record.source_id
    except BaseException as error:
        with Session(engine) as session, session.begin():
            run = session.get(ImportRun, run_id)
            run.status = "failed"
            # Exception text from HTTP/database libraries may contain credentials.
            run.error = f"{type(error).__name__}: import stopped; committed records are preserved"
            run.finished_at = datetime.now(UTC)
        raise
    with Session(engine) as session, session.begin():
        run = session.get(ImportRun, run_id)
        run.status = "partial" if run.rejected else "completed"
        run.finished_at = datetime.now(UTC)
        return {
            "run_id": str(run.id),
            "source": source,
            "status": run.status,
            "processed": run.processed,
            "inserted": run.inserted,
            "updated": run.updated,
            "rejected": run.rejected,
        }
