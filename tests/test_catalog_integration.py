from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from athena.ingestion.providers import ProviderError
from athena.ingestion.service import IdentityConflict, run_import, upsert_paper
from athena.models import Identifier, ImportRun, Paper, SourceRecord

pytestmark = pytest.mark.integration


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
