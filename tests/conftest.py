import os
from datetime import UTC, date, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from athena.ingestion.schemas import PaperRecord


@pytest.fixture
def record():
    return PaperRecord(
        source="arxiv",
        source_id="2401.00001",
        arxiv="2401.00001",
        title="Graph neural networks for drug discovery",
        abstract="A controlled evaluation of molecular graph learning.",
        authors=["Test Researcher"],
        topics=["cs.LG"],
        publication_date=date(2024, 1, 1),
        source_updated_at=datetime(2024, 1, 2, tzinfo=UTC),
        landing_url="https://arxiv.org/abs/2401.00001",
        doi="10.1234/test",
        work_type="preprint",
        payload={"fixture": True},
    )


@pytest.fixture(scope="session")
def database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for real PostgreSQL integration tests")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Refusing to reset a database whose name does not end in _test")
    from athena.config import get_settings
    from athena.db import get_engine

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous


@pytest.fixture
def db(database):
    with database.begin() as connection:
        connection.execute(
            text("TRUNCATE import_runs, source_records, identifiers, papers CASCADE")
        )
    return database


@pytest.fixture
def session(db):
    with Session(db) as session:
        yield session


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from athena.db import get_session
    from athena.main import app

    def override():
        with Session(db) as session:
            yield session

    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
