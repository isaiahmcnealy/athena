# Changelog

## Unreleased

### Added

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

- OpenAlex imports exclude future publication dates, retracted works, and types other than
  articles, reviews, and preprints.
- Provider requests retry up to five times with 3–24 second backoff, up from three attempts,
  after a brief arXiv outage stopped a bulk import. Failure output names the safe provider error.

### Fixed

- A short arXiv page inside the reported result window is refetched and then fails the run,
  instead of ending the query early and reporting it as completed.

- CI can be reused by the release workflow. Branches other than `master` and pull requests
  run checks without deploying; `master` runs checks as part of the release pipeline.

## 0.1.0 — Initial working version

- arXiv and OpenAlex ingestion, source identity reconciliation, and import tracking.
- PostgreSQL catalog with full-text search, filters, pagination, and paper detail pages.
- Health checks, request metrics, structured logs, migrations, local Docker setup, and tests.
