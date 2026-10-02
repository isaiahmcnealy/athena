# Athena documentation

- [Architecture](architecture.md): application boundaries, storage, and planned capabilities.
- [Production and portfolio roadmap](production-roadmap.md): project review, prioritized features,
  recommendation evaluation, architecture, release gates, and interview evidence.
- [1.0 public release checklist](release-1.0-checklist.md): launch blockers, acceptance evidence,
  deployment, security, recovery, product, and release sign-off.
- [Local operations](operations.md): imports, inspection, backups, and recovery experiments.
- [Cloud deployment](deployment.md): branch workflow, server setup, DNS, secrets, releases,
  scheduled refresh and backup, and recovery.
- [ADR 001: release deployment](decisions/001-mac-mini-releases.md): original Mac mini design;
  its hosting parts are superseded by ADR 002.
- [ADR 002: public preview on a cloud host](decisions/002-public-preview-cloud-host.md): what
  the preview promises, hosting, the public boundary, and its availability limits.
- [Changelog](../CHANGELOG.md): changes grouped by release; upcoming changes stay under Unreleased.

Record significant architecture decisions as numbered files in `decisions/`. Include the
context, decision, alternatives, and consequences. Update the relevant guide and changelog
in the same change as the implementation.
