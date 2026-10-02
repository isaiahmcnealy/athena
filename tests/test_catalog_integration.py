import hashlib
from datetime import date, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from athena.ingestion.audit import catalog_audit
from athena.ingestion.providers import ProviderError, parse_openalex
from athena.ingestion.service import IdentityConflict, run_import, upsert_paper
from athena.ingestion.stats import catalog_stats
from athena.models import Identifier, ImportRun, Paper, SourceRecord

pytestmark = pytest.mark.integration


def test_stats_counts_canonical_papers_and_reports_storage(db, record):
    run_import(db, "arxiv", "stats", [record])
    run_import(db, "arxiv", "stats replay", [record])
    stats = catalog_stats(db)
    assert stats["papers"] == 1
    assert stats["source_records"] == 1
    assert stats["identifier_keys"] == 2
    assert stats["database_bytes"] >= stats["catalog_bytes"] > 0
    assert any(row["index_bytes"] > 0 for row in stats["relations"])


def test_audit_reports_coverage_and_flags_records_for_review(db, record):
    def paper(number, **fields):
        identity = {"source_id": f"2401.{number:05}", "arxiv": f"2401.{number:05}", "doi": None}
        return record.model_copy(update={**identity, **fields})

    openalex = record.model_copy(
        update={
            "source": "openalex",
            "source_id": "W9",
            "arxiv": None,
            "doi": "10.48550/arxiv.2401.00002",
            "title": "A title-only record",
            "abstract": None,
            "venue": None,
            "landing_url": "https://openalex.org/W9",
            "work_type": "article",
        }
    )
    run_import(db, "arxiv", "audit", [paper(1), paper(2, title=record.title.upper())])
    # Written directly: the importer would merge this record through its arXiv DOI.
    with Session(db) as session, session.begin():
        stray = Paper(
            **openalex.model_dump(include={"title", "authors", "topics", "publication_date"}),
            doi=openalex.doi,
            primary_source="openalex",
            landing_url=openalex.landing_url,
            work_type="article",
        )
        session.add(stray)
    before = catalog_stats(db)
    report = catalog_audit(db)
    assert report["totals"]["papers"] == 3
    assert report["totals"]["latest_publication"] == record.publication_date
    assert report["source_coverage"] == [{"sources": "arxiv", "papers": 2}]
    assert report["by_year"] == [{"year": 2024, "papers": 3}]
    text_rows = {row["primary_source"]: row for row in report["text_availability"]}
    assert text_rows["openalex"]["without_abstract"] == 1
    assert text_rows["arxiv"]["without_abstract"] == 0
    assert report["top_topics"][0] == {"topic": "cs.LG", "papers": 3}
    assert report["checks"] == {
        "future_publication_dates": 0,
        "papers_sharing_a_title": 2,
        "titles_shared_by_several_papers": 1,
        "unmerged_arxiv_doi_pairs": 1,
        "papers_without_a_source_record": 1,
        "papers_without_an_identifier": 1,
        "imports_left_running": 0,
        "records_rejected_for_identity_conflicts": 0,
    }
    assert catalog_stats(db)["papers"] == before["papers"]


def test_audit_of_an_empty_catalog_reports_zeroes(db):
    report = catalog_audit(db)
    assert report["totals"]["papers"] == 0
    assert report["by_year"] == []
    assert set(report["checks"].values()) == {0}


def test_replay_is_idempotent(session, record):
    assert upsert_paper(session, record)
    session.commit()
    assert not upsert_paper(session, record)
    session.commit()
    assert session.scalar(select(func.count()).select_from(Paper)) == 1
    assert session.scalar(select(func.count()).select_from(Identifier)) == 2


def test_cross_source_doi_dedup_keeps_arxiv_abstract(session, record):
    upsert_paper(session, record)
    session.commit()
    openalex = record.model_copy(
        update={
            "source": "openalex",
            "source_id": "W1",
            "arxiv": None,
            "title": "Other title",
            "abstract": None,
            "venue": "Journal of Tests",
            "landing_url": "https://openalex.org/W1",
        }
    )
    upsert_paper(session, openalex)
    session.commit()
    paper = session.scalar(select(Paper))
    assert paper.title == record.title
    assert paper.abstract == record.abstract
    assert paper.venue == "Journal of Tests"
    assert session.scalar(select(func.count()).select_from(Paper)) == 1
    assert session.scalar(select(func.count()).select_from(SourceRecord)) == 2


@pytest.mark.parametrize("openalex_first", [False, True])
def test_cross_source_arxiv_link_deduplicates_without_doi(session, record, openalex_first):
    arxiv = record.model_copy(update={"doi": None})
    openalex = parse_openalex(
        {
            "id": "https://openalex.org/W123",
            "title": "Alternate metadata title",
            "publication_date": "2024-01-01",
            "locations": [{"landing_page_url": "https://arxiv.org/abs/2401.00001v2"}],
        }
    )
    records = [openalex, arxiv] if openalex_first else [arxiv, openalex]
    for item in records:
        upsert_paper(session, item)
        session.commit()
    assert session.scalar(select(func.count()).select_from(Paper)) == 1
    assert session.scalar(select(func.count()).select_from(SourceRecord)) == 2
    assert session.scalar(select(Paper.title)) == record.title
    assert session.scalar(select(Paper.abstract)) == record.abstract


def test_replay_keeps_the_content_revision_and_a_text_change_advances_it(session, record):
    upsert_paper(session, record)
    session.commit()
    first = session.scalar(select(Paper))
    original = (first.content_hash, first.content_changed_at, first.updated_at)
    assert first.content_revision == 1
    expected = hashlib.md5(f"{record.title}\n{record.abstract}".encode()).hexdigest()
    assert first.content_hash == expected

    upsert_paper(session, record)
    session.commit()
    session.refresh(first)
    assert (first.content_revision, first.content_hash) == (1, original[0])
    assert first.content_changed_at == original[1]
    assert first.updated_at > original[2]

    revised = record.model_copy(
        update={
            "abstract": "A corrected abstract.",
            "source_updated_at": record.source_updated_at + timedelta(days=1),
        }
    )
    upsert_paper(session, revised)
    session.commit()
    session.refresh(first)
    assert first.content_revision == 2
    assert first.content_hash != original[0]
    assert first.content_changed_at > original[1]


def test_metadata_from_a_second_source_does_not_advance_the_content_revision(session, record):
    upsert_paper(session, record)
    session.commit()
    openalex = record.model_copy(
        update={
            "source": "openalex",
            "source_id": "W1",
            "arxiv": None,
            "title": "Other title",
            "abstract": None,
            "venue": "Journal of Tests",
            "landing_url": "https://openalex.org/W1",
        }
    )
    upsert_paper(session, openalex)
    session.commit()
    paper = session.scalar(select(Paper))
    assert paper.venue == "Journal of Tests"
    assert paper.content_revision == 1


def test_content_migration_backfills_existing_papers(db):
    config = Config("alembic.ini")
    command.downgrade(config, "0001")
    try:
        with db.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO papers (id, title, abstract, authors, topics, publication_date,
                        primary_source, landing_url, work_type, updated_at)
                    VALUES (gen_random_uuid(), 'Title only', NULL, '[]', '[]', '2024-01-01',
                        'openalex', 'https://openalex.org/W1', 'article', '2024-02-03T00:00:00Z')
                """)
            )
    finally:
        command.upgrade(config, "head")
    with db.connect() as connection:
        row = connection.execute(
            text(
                "SELECT content_hash, content_revision, content_changed_at = updated_at FROM papers"
            )
        ).one()
    assert tuple(row) == (hashlib.md5(b"Title only\n").hexdigest(), 1, True)


def test_older_version_does_not_overwrite(session, record):
    upsert_paper(session, record)
    session.commit()
    old = record.model_copy(
        update={
            "title": "Old title",
            "source_updated_at": record.source_updated_at - timedelta(days=1),
        }
    )
    upsert_paper(session, old)
    session.commit()
    assert session.scalar(select(Paper.title)) == record.title


def test_identity_conflict_preserves_both_papers(session, record):
    upsert_paper(session, record)
    other = record.model_copy(
        update={"source_id": "2401.00002", "arxiv": "2401.00002", "doi": "10.1234/other"}
    )
    upsert_paper(session, other)
    session.commit()
    with pytest.raises(IdentityConflict):
        upsert_paper(session, other.model_copy(update={"doi": record.doi}))
    session.rollback()
    assert session.scalar(select(func.count()).select_from(Paper)) == 2


def test_concurrent_duplicate_imports_create_one_paper(db, record):
    from concurrent.futures import ThreadPoolExecutor

    def ingest_once(_):
        with Session(db) as session, session.begin():
            return upsert_paper(session, record)

    with ThreadPoolExecutor(max_workers=4) as pool:
        created = list(pool.map(ingest_once, range(4)))
    assert sum(created) == 1
    with Session(db) as session:
        assert session.scalar(select(func.count()).select_from(Paper)) == 1


def test_identity_conflict_marks_import_partial(db, record):
    other = record.model_copy(
        update={"source_id": "2401.00002", "arxiv": "2401.00002", "doi": "10.1234/other"}
    )
    run_import(db, "arxiv", "test", [record, other])
    result = run_import(db, "arxiv", "test", [other.model_copy(update={"doi": record.doi})])
    assert result["status"] == "partial"
    assert result["rejected"] == 1


def test_failed_import_keeps_committed_progress(db, record):
    def broken():
        yield record
        raise ProviderError("Provider unavailable")

    with pytest.raises(ProviderError):
        run_import(db, "arxiv", "test", broken())
    with Session(db) as session:
        run = session.scalar(select(ImportRun))
        assert run.status == "failed"
        assert run.processed == 1
        assert session.scalar(select(func.count()).select_from(Paper)) == 1
    result = run_import(db, "arxiv", "test", [record])
    assert result["inserted"] == 0
    assert result["updated"] == 1


def test_search_filters_and_safe_html(client, db, record):
    run_import(db, "arxiv", "test", [record])
    response = client.get("/api/papers", params={"q": "molecular", "year": 2024})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert client.get("/api/papers?q=unrelated").json()["total"] == 0
    assert client.get("/api/papers?source=openalex").json()["total"] == 0
    assert client.get("/api/papers?year=2023").json()["total"] == 0
    assert client.get("/?q=graph&year=&source=&venue=").status_code == 200
    assert client.get("/api/papers?limit=1001").status_code == 422
    assert client.get("/api/papers?cursor=invalid").status_code == 400
    paper_id = response.json()["items"][0]["id"]
    assert client.get(f"/papers/{paper_id}").status_code == 200
    assert client.get("/docs").status_code == 200
    assert "Content-Security-Policy" in client.get("/").headers


def test_pagination_ties_and_new_imports(client, db, record):
    records = [
        record.model_copy(
            update={"source_id": f"2401.{i:05}", "arxiv": f"2401.{i:05}", "doi": None}
        )
        for i in range(5)
    ]
    run_import(db, "arxiv", "test", records)
    first = client.get("/api/papers?limit=2").json()
    run_import(
        db,
        "arxiv",
        "test",
        [
            record.model_copy(
                update={
                    "source_id": "2501.00001",
                    "arxiv": "2501.00001",
                    "doi": None,
                    "publication_date": date(2025, 1, 1),
                }
            )
        ],
    )
    ids = [paper["id"] for paper in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = client.get("/api/papers", params={"limit": 2, "cursor": cursor}).json()
        assert page["total"] == 5
        ids.extend(paper["id"] for paper in page["items"])
        cursor = page["next_cursor"]
    assert len(ids) == len(set(ids)) == 5
    assert (
        client.get(
            "/api/papers", params={"q": "different", "cursor": first["next_cursor"]}
        ).status_code
        == 400
    )


def test_relevance_ranks_title_matches_first_and_newest_is_separate(client, db, record):
    def paper(number, **fields):
        identity = {"source_id": f"2401.{number:05}", "arxiv": f"2401.{number:05}", "doi": None}
        return record.model_copy(update={**identity, **fields})

    run_import(
        db,
        "arxiv",
        "test",
        [
            paper(1, title="Protein folding", abstract="Nothing else.", doi="10.1234/fold"),
            paper(
                2,
                title="A survey of methods",
                abstract="Protein folding is mentioned once.",
                publication_date=date(2025, 6, 1),
            ),
            paper(3, title="Unrelated work", abstract="Crop yields."),
        ],
    )
    ranked = client.get("/api/papers", params={"q": "protein folding"}).json()
    assert ranked["sort"] == "relevance"
    assert [item["title"] for item in ranked["items"]] == ["Protein folding", "A survey of methods"]
    newest = client.get("/api/papers", params={"q": "protein folding", "sort": "newest"}).json()
    assert newest["sort"] == "newest"
    assert [item["title"] for item in newest["items"]] == ["A survey of methods", "Protein folding"]
    assert client.get("/api/papers").json()["sort"] == "newest"
    by_doi = client.get("/api/papers", params={"q": "https://doi.org/10.1234/FOLD"}).json()
    assert [item["title"] for item in by_doi["items"]] == ["Protein folding"]
    by_arxiv = client.get("/api/papers", params={"q": "arXiv:2401.00003v2"}).json()
    assert [item["title"] for item in by_arxiv["items"]] == ["Unrelated work"]
    html = client.get("/", params={"q": "protein folding"}).text
    assert "Most relevant" in html and "sort=newest" in html
    assert "Most relevant" not in client.get("/").text


def test_relevance_pagination_is_complete_with_tied_scores(client, db, record):
    records = [
        record.model_copy(
            update={
                "source_id": f"2401.{i:05}",
                "arxiv": f"2401.{i:05}",
                "doi": None,
                # Two score groups with ties inside each, on the same date.
                "title": "Graph learning" if i % 2 else "Something different",
                "abstract": "A graph learning study.",
            }
        )
        for i in range(7)
    ]
    run_import(db, "arxiv", "test", records)
    params = {"q": "graph learning", "limit": 2}
    page = client.get("/api/papers", params=params).json()
    titles = [item["title"] for item in page["items"]]
    ids = [item["id"] for item in page["items"]]
    while page["next_cursor"]:
        page = client.get("/api/papers", params={**params, "cursor": page["next_cursor"]}).json()
        titles.extend(item["title"] for item in page["items"])
        ids.extend(item["id"] for item in page["items"])
    assert len(ids) == len(set(ids)) == 7
    assert titles == ["Graph learning"] * 3 + ["Something different"] * 4
    first = client.get("/api/papers", params=params).json()["next_cursor"]
    mismatched = client.get("/api/papers", params={**params, "sort": "newest", "cursor": first})
    assert mismatched.status_code == 400


def test_stored_html_is_escaped(client, db, record):
    unsafe = record.model_copy(update={"title": "<script>alert('x')</script>"})
    run_import(db, "arxiv", "test", [unsafe])
    html = client.get("/").text
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_health_metrics_and_missing_paper(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/papers/00000000-0000-0000-0000-000000000000").status_code == 404
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert 'route="/api/papers/{paper_id}"' in metrics.text
    assert "00000000-0000" not in metrics.text


def test_database_failure_returns_503_and_liveness_survives(client):
    from sqlalchemy.exc import OperationalError

    from athena.db import get_session
    from athena.main import app

    def broken_session():
        raise OperationalError("query", {}, Exception("sensitive connection details"))
        yield

    app.dependency_overrides[get_session] = broken_session
    assert client.get("/health/live").status_code == 200
    response = client.get("/api/papers")
    assert response.status_code == 503
    assert "sensitive" not in response.text
    assert client.get("/health/ready").status_code == 503
    assert client.get("/").status_code == 503
