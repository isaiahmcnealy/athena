# Changelog

## Unreleased

### Added

- `master` release workflow: tests, ARM64 image build, container smoke checks, GHCR publishing,
  and optional Mac mini deployment over Tailscale and SSH.
- Separate release Compose stack, database backup before migrations, deployment locking,
  digest-based image selection, readiness verification, and release history pointers.
- Server setup and recovery guide, documentation index, and deployment architecture decision.

### Changed

- CI can be reused by the release workflow. Branches other than `master` and pull requests
  run checks without deploying; `master` runs checks as part of the release pipeline.

## 0.1.0 — Initial working version

- arXiv and OpenAlex ingestion, source identity reconciliation, and import tracking.
- PostgreSQL catalog with full-text search, filters, pagination, and paper detail pages.
- Health checks, request metrics, structured logs, migrations, local Docker setup, and tests.
