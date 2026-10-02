# Athena

A research paper discovery and recommendation platform built on arXiv and OpenAlex.
Athena starts with a searchable, populated catalog and evolves toward semantic retrieval
and personalized recommendations with production-oriented ML infrastructure.

**Release 0.1:** catalog ingestion, PostgreSQL full-text search, filtering, paper details,
source provenance, import run tracking, health checks, request metrics, and a responsive UI.
Recommendations, accounts, and reading collections are planned; they are not implemented yet.

## Quick start

Requires Docker Desktop (running) and Docker Compose. Ports 8000 and 5433 must be available.

```sh
cp .env.example .env
docker compose up --build -d web
docker compose run --rm ingest ingest arxiv --limit 50
docker compose run --rm ingest ingest openalex --query 'machine learning healthcare' --limit 50
```

Open <http://localhost:8000>. API documentation: <http://localhost:8000/docs>.
The database starts first, migrations run once, then the web application starts.
Imports are explicit and do not run at web startup. No fabricated/demo papers are inserted.

Set `OPENALEX_API_KEY` in `.env` for an authenticated OpenAlex budget and `CONTACT_EMAIL`
to identify your importer. A small keyless import may work within the provider's current
allowance. A provider failure never prevents browsing records already imported.

Default database credentials and loopback port bindings are **local development only**.
This release is not a hardened public deployment. Do not expose the database or metrics
endpoint publicly. See [operations](docs/operations.md) before deployment.

## Local Python development

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --frozen
docker compose up -d db
uv run alembic upgrade head
uv run athena ingest arxiv --query 'cat:cs.LG OR cat:cs.AI' --limit 100
uv run athena ingest openalex --query 'artificial intelligence finance' --limit 100
uv run uvicorn athena.main:app --reload
```

Use either the containerized web server or the local Python server on port 8000, not both.
The `.env` database URL uses PostgreSQL on host port **5433** to avoid common local conflicts.

## Tests

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -m 'not integration'
docker compose exec db createdb -U athena athena_test
TEST_DATABASE_URL=postgresql+psycopg://athena:athena@localhost:5433/athena_test uv run pytest
```

Integration tests **reset tables in the supplied test database**, which must have a name
ending in `_test`. They use PostgreSQL and Alembic, not SQLite. Do not pass a valuable database.
Tests without `TEST_DATABASE_URL` explicitly skip database integration tests.

## API

- `GET /api/papers?q=graph+neural&source=arxiv&year=2025&limit=12`
- `GET /api/papers/{id}`
- `GET /health/live`: process liveness, independent of database availability
- `GET /health/ready`: database connectivity and catalog schema availability
- `GET /metrics`: Prometheus HTTP counts and latency histograms

Search matches title and available abstract using PostgreSQL English full-text search.
Results sort by publication date, then stable internal ID; they do not claim learned relevance.
Follow the returned `next_cursor` with the same filters. New imports are excluded from an
existing pagination session. Concurrent metadata edits are not snapshot-isolated across requests.
The venue filter searches source-provided journal/venue text; author search is not yet implemented.

## Ingestion guarantees and limits

- Bounded queries, 1–1,000 records per run; provider pagination, timeouts, limited retries,
  and backoff. arXiv calls are sequential with at least 3 seconds between pages/retries.
- Each accepted record and its import progress commit in one database transaction.
- Identifiers, including normalized DOI, deduplicate records. Titles never drive automatic merges.
- Older source versions cannot overwrite newer source records. Conflicting identifiers fail
  reconciliation safely instead of silently merging two existing works.
- Latest accepted source payloads and fetch times are stored. This is provenance, **not yet a
  complete version history or immutable raw archive**.
- Rerun an interrupted query from the beginning; committed records upsert safely. The last source
  ID is an audit checkpoint, not an upstream cursor guarantee. A moving provider result window can
  omit older records; exhaustive historical backfill and scheduled delta synchronization are future work.
- A malformed page/record fails the run visibly; identity conflicts mark it partial and produce a
  nonzero CLI exit. A force-killed process may leave a run marked `running`; inspect before retrying.
- arXiv abstracts are ingested as source metadata. OpenAlex abstracts are deliberately omitted until
  a field-level reuse policy is implemented; full papers/PDFs are never downloaded or rehosted.
- Ordered author names are stored per paper. Global author disambiguation, venue normalization,
  upstream entity merges, and preprint/publication family resolution are intentionally deferred.

## Development and releases

Work on `develop` and run the quick start above for local testing. Release by merging
`develop` into `master`. A push to `master` runs tests, builds and smoke-tests an ARM64
container, and publishes it to GitHub Container Registry. Once server setup is enabled,
the pipeline deploys that exact image to the Mac mini over Tailscale and SSH.

The Mac mini uses its own database and port 8001; local development stays on port 8000.
Deployment starts disabled until the server and GitHub secrets are configured.
Follow the [Mac mini setup and release guide](docs/deployment.md).

See the [documentation index](docs/README.md) for architecture, operations, decisions,
and the changelog.

## Data sources

- [arXiv API](https://info.arxiv.org/help/api/index.html)
- [arXiv metadata and article licenses](https://info.arxiv.org/help/license/index.html)
- [OpenAlex data](https://help.openalex.org/data/)
- [OpenAlex API access](https://help.openalex.org/api/authentication/)

Thank you to arXiv for use of its open access interoperability.
Athena is an independent project; indexing does not establish peer-review status or endorsement.
