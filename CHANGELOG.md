# Changelog

## Unreleased

### Added

- Connection and resource bounds for the release stack: the web server answers 503 beyond 64
  requests in flight, gives in-flight requests 20 seconds on shutdown, and every container
  has a CPU limit. PostgreSQL gets 60 seconds to shut down cleanly.
- Request-boundary tests for oversized and malformed filters, hostile search terms, literal
  venue wildcards, forged cursors, markup injection through stored and reflected values, and
  security headers on pages, errors, and the API.
- Content tracking for papers: a PostgreSQL-generated hash of the title and abstract, a
  revision that advances only when that text changes, and the time of the last change.
  Replays and metadata from a second source leave the revision untouched. Migration `0002`
  backfills existing papers and stays compatible with the previous application.
- `athena audit`: a read-only report of catalog coverage by source, year, and type, missing
  fields, and records that need review, with the first recorded audit of the development
  catalog.
- Relevance ordering for searches (`sort=relevance`, the default when a query has terms) using
  PostgreSQL `ts_rank`, with "Newest" kept as a separate ordering, a `sort` field in API
  responses, and a sort control on the results page.
- Exact lookup when the search box or `q` holds a DOI or an arXiv identifier.
- About page covering sources and attribution, how results are ordered, data handling, and
  contact, linked from the navigation and footer.
- Public release stack: Caddy for HTTPS with automatic certificates and an HTTP redirect,
  `/metrics` blocked at the proxy, a read-only database role for the web app, an importer
  role that can write rows but not change the schema, memory limits, and log rotation.
- Per-client request limit (`RATE_LIMIT_PER_MINUTE`) returning `429` with `Retry-After`, and a
  host allow-list (`ALLOWED_HOSTS`). Client addresses come from forwarded headers only when
  sent by the proxy.
- Scheduled jobs for the server: `refresh.sh` imports the newest records for every seed topic,
  and `backup.sh` writes a dated dump, prunes old scheduled dumps, and can copy to S3.
- Uptime workflow that checks public readiness and catalog size every 15 minutes, a post-deploy
  HTTPS check in the release pipeline, and weekly Dependabot updates.
- ADR 002: public preview scope, cloud hosting, the public boundary, and availability limits.
- Version 1.0 public release checklist with implementation gates and verification evidence.
- Production and portfolio roadmap with a repository review, prioritized recommendation features,
  evaluation plan, deployment gates, and learning/interview milestones.
- `master` release workflow: tests, ARM64 image build, container smoke checks, GHCR publishing,
  and optional Mac mini deployment over Tailscale and SSH.
- Separate release Compose stack, database backup before migrations, deployment locking,
  digest-based image selection, readiness verification, and release history pointers.
- Server setup and recovery guide, documentation index, and deployment architecture decision.
- `athena seed`: curated arXiv and OpenAlex queries across 21 AI and industry topics, with
  `--per-query`, `--source`, `--dry-run`, and `--start-at`; sequential, paced, and stops on failure.
- `athena stats`: canonical paper, source record, and identifier counts, papers shared across
  sources, and PostgreSQL storage sizes.
- Cross-source deduplication: OpenAlex works that point to exactly one arXiv identifier, through
  an arxiv.org link or an arXiv DOI (`10.48550/arXiv.<id>`), resolve to the same paper as the
  arXiv record.
- Energy and Oil and gas links under "Explore an idea" on the catalog page.
- Measured 10,000-record import trial and recovery steps in the operations guide.

### Changed

- Searches with terms now return the most relevant results first instead of the newest. Pass
  `sort=newest` for the previous order. Pagination cursors include the ordering.
- The release image is built for AMD64 and deploys to a cloud server instead of the Mac mini.
  GitHub settings are renamed: environment `production`, `DEPLOY_HOST`, `DEPLOY_USER`,
  `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`, `DEPLOY_ENABLED`, and the new `PUBLIC_URL`.
- The server `.env` now requires `ATHENA_WEB_DB_PASSWORD`, `ATHENA_INGEST_DB_PASSWORD`, and
  `ATHENA_DOMAIN`; deployment refuses to start without them.
- The container no longer writes uvicorn access logs, which included client addresses and
  search terms. Structured request logs are unchanged.
- OpenAlex imports exclude future publication dates, retracted works, and types other than
  articles, reviews, and preprints.
- Provider requests retry up to five times with 3–24 second backoff, up from three attempts,
  after a brief arXiv outage stopped a bulk import. Failure output names the safe provider error.

### Fixed

- A search or venue filter containing a NUL byte returned 503; the byte is now dropped.
- A forged pagination cursor with a non-text ID returned 500, and one with a non-finite
  score was accepted; both now return 400.
- The arXiv option was missing from the source filter on the catalog page.
- A short arXiv page inside the reported result window is refetched and then fails the run,
  instead of ending the query early and reporting it as completed.

- CI can be reused by the release workflow. Branches other than `master` and pull requests
  run checks without deploying; `master` runs checks as part of the release pipeline.

## 0.1.0 — Initial working version

- arXiv and OpenAlex ingestion, source identity reconciliation, and import tracking.
- PostgreSQL catalog with full-text search, filters, pagination, and paper detail pages.
- Health checks, request metrics, structured logs, migrations, local Docker setup, and tests.
