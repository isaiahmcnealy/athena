# ADR 002: public preview on an always-on cloud host

Status: proposed. Date: 2026-10-02. The owner still has to confirm the provider, region,
instance size, backup bucket, and monthly budget marked "to confirm" below.

Supersedes the hosting parts of [ADR 001](001-mac-mini-releases.md). The branch model,
digest-based images, backup before migration, and serialized deployments are unchanged.

## Context

Athena should be reachable from the portfolio at `athena.isaiahmcnealy.com` whenever a
visitor follows the link. The Mac mini travels with its owner, so it cannot serve public
requests. Expected traffic is low. The [1.0 checklist](../release-1.0-checklist.md) ties
opening the site to shipping recommendations; this decision separates the two so a
search-only catalog can go live first.

## Decision

### What the public preview promises

- **Readers:** people exploring AI research and its applications; no account is needed.
- **Content:** preprints, articles, and reviews across the 21 seed topics, from arXiv and
  OpenAlex. Records are labeled by source and type. Inclusion never implies peer review.
- **Features:** search with "Most relevant" and "Newest" ordering, DOI and arXiv ID lookup,
  filters, paper details with provenance, a read-only JSON API, and an About page covering
  sources, ordering, data handling, and contact.
- **Not included:** recommendations, accounts, saved papers, and any per-visitor history.
  The service stores no personal data, sets no cookies, and keeps search terms and client
  addresses out of its logs.
- **Language:** English interface and English full-text search.
- **Version:** the application stays 0.x. It is not presented as 1.0 until that
  checklist's gates are met.

### Hosting

- One x86-64 Linux server runs the whole stack with Docker Compose: Caddy for HTTPS,
  the web application, and PostgreSQL. **To confirm:** AWS Lightsail in `us-east-1`,
  2 GB memory, Ubuntu LTS, with a static IP.
- DNS for `athena.isaiahmcnealy.com` is an `A` record in the existing Route 53 zone. No
  other record in the zone changes.
- Only ports 80 and 443 are public. SSH is reached over Tailscale, and the release
  pipeline keeps using an ephemeral Tailscale connection, a pinned host key, and a
  dedicated deploy key. PostgreSQL has no published port.
- Caddy terminates TLS, redirects HTTP to HTTPS, and answers 404 for `/metrics`. The
  interactive API documentation at `/docs` stays public because the API is read-only and
  the site links to it.
- The web application connects as a read-only PostgreSQL role, the importer as a role
  that can write rows but not change the schema, and only migrations use the owning role.
- The application limits each client to 120 requests per minute for pages and the API,
  and accepts only the configured host names. Client addresses are taken from forwarded
  headers only when they come from the proxy's address.
- The Mac mini remains a development machine. Nothing a live request needs runs on it.

### Operations

- **Catalog:** seeded on the server after the first release, then refreshed daily by cron
  with a small request per topic.
- **Backups:** a logical dump before every migration and a daily scheduled dump, kept on
  the server for 14 days. **To confirm:** a private, encrypted S3 bucket as the off-host
  copy. The catalog can also be rebuilt from the sources with `athena seed`.
- **Monitoring:** a scheduled GitHub Actions check of public readiness and catalog size
  every 15 minutes, which emails the owner on failure, plus the release pipeline's
  post-deploy HTTPS check.
- **Budget:** **to confirm**, about USD 12 per month for the server plus cents for DNS and
  backup storage, with a billing alert at USD 20.

### Availability statement

This is a single server. A host, disk, or provider-zone failure takes the site down until
it is restarted or rebuilt, and deployments cause a brief interruption. Initial targets
are a recovery point of 24 hours and a recovery time of 2 hours; neither is verified until
a restore drill is recorded on the real host. No uptime percentage is claimed.

## Alternatives

- **Managed platform (Render, Fly.io, Railway):** less server upkeep, but the existing
  SSH-and-Compose pipeline would be replaced, and always-on plans with a managed database
  cost about the same or more.
- **AWS managed services (App Runner or ECS with RDS):** the most hands-off and the best
  path to high availability, at several times the cost. Not justified at this traffic.
- **Rate limiting in the proxy:** stock Caddy has no rate limiter, and a custom Caddy build
  would add a second image to publish and patch. The in-application limiter is per process,
  which matches the single web container.
- **Opening SSH to the internet:** simpler setup, larger attack surface. Tailscale keeps
  the existing private path.

## Consequences

- The release image is now AMD64. Running on an ARM host again needs an ARM64 build.
- The server `.env` gains two role passwords and the public hostname. Deployment refuses
  to start without them.
- The rate limit is held in memory. It resets when the web container restarts and would
  need a shared store before running more than one web process.
- Certificates and the ACME account live in a Docker volume. Deleting it forces reissue,
  and repeated reissue can hit the certificate authority's rate limits.
- GitHub pauses scheduled workflows after 60 days without repository activity, so the
  uptime check is a baseline. A dedicated external monitor is still worth adding.
- Work still open before 1.0 is tracked in the [1.0 checklist](../release-1.0-checklist.md):
  recommendations and their evaluation, the retraction lifecycle, duplicate reconciliation,
  a recorded restore drill and load test on the real host, and accessibility review.
