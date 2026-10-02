# ADR 001: master releases to a Mac mini

Status: accepted. Date: 2026-10-02.

## Context

Athena needs an inexpensive persistent deployment while its owner develops and tests locally.
The owner has chosen an Apple Silicon Mac mini and the branch names `develop` and `master`.

## Decision

- `develop` is the integration branch for local work. `master` contains releases.
- GitHub-hosted runners execute tests and build Linux ARM64 images. A separate ARM64
  container smoke test exercises migrations and readiness before publication to GHCR.
- The deployment job uses an ephemeral Tailscale connection and ordinary macOS SSH.
  There is no GitHub Actions runner installed on the server.
- Deploy images by digest. Keep application secrets on the server; configure SSH and
  Tailscale credentials in the GitHub `mac-mini` environment.
- Docker Compose runs web and PostgreSQL under project `athena-release`. Server volumes,
  credentials, and port bindings are separate from local development.
- Back up before migrations, serialize deployments, and verify readiness before recording
  success. Start with a single web container and explicit recovery procedures.

## Alternatives

AWS from the start would provide a more suitable foundation for availability and managed
databases, with additional infrastructure and ongoing cost. A persistent self-hosted GitHub
runner would simplify connectivity but give workflow jobs ongoing access to the server.
Direct public SSH would require an exposed endpoint; Tailscale provides private connectivity.

## Consequences

The Mac mini, Docker Desktop, home power, and network are single points of failure. App
replacement can cause brief downtime. Docker Desktop and Tailscale must be operational after
reboots. PostgreSQL upgrades, scheduled off-machine backups, public ingress, and zero-downtime
rollouts are future work. Migrations must remain compatible with the old app during rollout;
automatic database downgrade is deliberately excluded.

Containers make a future Linux host migration practical, but the initial image is ARM64-only.
An x86 server requires an additional image architecture. Hosting changes do not require changing
the research catalog or ingestion architecture.
