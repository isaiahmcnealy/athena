# Athena 1.0 public release checklist

**Purpose:** bring the current Athena catalog to a safe, useful, always-on public research discovery and recommendation service at `athena.isaiahmcnealy.com`.

**Release policy:** do not advertise version 1.0 as ready until the P0 release gates below have an owner, implementation, and recorded evidence. “Works on my machine,” green CI, a running container, and a DNS record by themselves are not release evidence.

## Release definition

Athena 1.0 should let a first-time visitor search real technical papers, get useful recommendations from chosen interests or a paper they like, understand why items were suggested, and open the original scholarly record. The service must stay usable without an account. A visitor’s session may hold temporary interests; retain personal library/history only after implementing account access controls, disclosure, retention, export and deletion.

Host the application and database on an always-on cloud instance because the owner travels with the Mac mini. Keep the Mac mini for development and optional background embedding work. All components required to answer a live request must remain available when the mini is offline. A small single-host deployment is acceptable for an early portfolio release when its single-host availability limit, monitoring, backup and restore have been disclosed and verified.

## Current state and the release gap

The repository currently identifies itself as release **0.1.0**. It has a FastAPI/Jinja app, PostgreSQL schema and full-text search with relevance and newest ordering, arXiv/OpenAlex importers, provenance, request logs/metrics, database migrations, CI, and a digest-based Compose release path for a cloud server: HTTPS through Caddy, limited database roles, request limits, scheduled refresh and backup scripts, and an uptime check. The app is not yet a recommender. The README explicitly says accounts and recommendations are planned. There is no embedding/index pipeline, feedback/profile store, recommendation API, authentication, or verified live host. No server, DNS record, backup bucket, or GitHub deployment setting exists yet.

Search ranks by a lexical score, not a learned one, and titles containing every query term tie. OpenAlex abstracts are excluded, so those records are matched and scored on their title alone. Ingestion requests exclude retracted OpenAlex works, but existing records have no retraction/tombstone lifecycle. These are release work items, not hypothetical future scale problems.

Local verification on 2026-10-02: 81 tests passed, including the PostgreSQL integration tests against a disposable database, and lint/format checks passed. The release stack was also run locally in throwaway containers to check HTTPS, the blocked metrics path, the host check, the request limit, the database roles, and a backup restore. This does not verify the cloud host, public behavior, the GitHub Actions workflows, or recovery on real data. Run the full applicable release checks on the actual deployment candidate before launch.

**Reading the status notes:** a box is ticked only when the item is complete without a live host. Items that are implemented but still need the real server stay open, with a dated note saying what remains. The hosting decision and the scope of the search-only public preview are in [ADR 002](decisions/002-public-preview-cloud-host.md).

## P0: required before opening the site to the public

### 1. Decide and freeze what 1.0 promises

- [ ] Write a short product contract: target readers, supported topics, publication types, recommendation surfaces, and supported locale.
  - _Status 2026-10-02:_ The preview's contract is in ADR 002. Recommendation surfaces for 1.0 are not defined yet.
- [ ] Keep the first public release focused on AI/ML and adjacent technical scholarship. Label preprints, journal articles, conference papers and reviews accurately. Do not imply that all catalog entries are peer-reviewed.
  - _Status 2026-10-02:_ The About page and paper pages say inclusion does not imply peer review. Type labels come from the sources and have not been audited (see section 3).
- [ ] Decide whether recommendations use an anonymous, temporary profile or account-backed profile. Anonymous discovery must work without login. If any per-user interests, events, saves, notes, or history are retained, complete P1 identity/privacy items before enabling that storage.
  - _Status 2026-10-02:_ The preview keeps no profile of any kind. The 1.0 choice is still open.
- [x] Define the sources and permitted fields used by the system. Keep source URLs, identifiers and provenance visible. Do not download or redistribute full papers without checking rights for the particular work.
  - _Status 2026-10-02:_ Documented in the README, ADR 002, and the About page: arXiv and OpenAlex metadata, arXiv abstracts only, source links and identifiers shown, no full papers stored.
- [ ] Pick an explicit initial serving and availability target. A single VPS cannot provide host-level high availability. State the measured limits instead of promising enterprise uptime.
  - _Status 2026-10-02:_ ADR 002 states the single-server limit and targets (recovery point 24 hours, recovery time 2 hours). Nothing is measured yet.
- [ ] Add 1.0 acceptance criteria and the target deployment region, provider, instance size, backup target and monthly budget to an ADR.
  - _Status 2026-10-02:_ ADR 002 records the accepted choice: AWS Lightsail in us-east-1, 2 GB, about USD 12 per month. The S3 backup bucket and billing alert are not confirmed, and 1.0 acceptance criteria are not written.

**Exit evidence:** a reviewed product/release note and one scope that can be completed without unresolved policy or cost decisions.

### 2. Make the recommender real and measurable

- [x] Fix the search contract: add a relevance sort using a documented lexical score and preserve “Newest” as a separate sort. Exact title/DOI searches should behave predictably.
  - _Status 2026-10-02:_ Searches with terms default to relevance (PostgreSQL ts_rank, title weighted above abstract) with Newest as a separate sort; a DOI or arXiv ID looks up the exact work. Documented in the README and About page; covered by `test_relevance_ranks_title_matches_first_and_newest_is_separate` and `test_relevance_pagination_is_complete_with_tied_scores`. Known limit: titles containing every term tie, so those fall back to newest first.
- [ ] Add a curated, versioned evaluation set with a written 0–3 relevance rubric. Begin with at least 30 queries across exact technical phrases, conceptual searches, application areas, foundational work, recent work, rare topics, missing abstracts and restrictive filters. Keep a held-out subset out of tuning.
- [x] Record catalog coverage and bias by year, source, topic, publication type and abstract availability. Audit documented duplicates and historical data skew before using offline metrics.
  - _Status 2026-10-02:_ Recorded in the [2026-10-02 catalog audit](reports/catalog-audit-2026-10-02.md) for the development catalog, which is where offline metrics will be computed. Main findings: 98% of papers are from 2026, 43% have no abstract, and 204 titles are shared within OpenAlex records.
- [ ] Choose and pin a compact, suitable text encoder. Record its exact model revision, license, text recipe, dimension, normalization, runtime, and expected memory. Be explicit about title-only records and excluded text.
- [ ] Generate paper embeddings asynchronously and idempotently. Key them by paper content revision and model revision. A replay of unchanged data should not cause an embedding job.
- [ ] Start with exact vector similarity and add pgvector to the actual PostgreSQL image, migrations, CI and local Compose. Do not use ANN/HNSW until measurements show it is needed. Compare ANN recall to exact neighbors if it is introduced.
- [ ] Implement “similar papers” and an anonymous interest-based “For you” feed. Use available interests/seed papers as input, filter out the seed paper and known publication-family duplicates, and provide a useful cold-start fallback.
- [ ] Keep serving independent of the Mac mini. Query-time inference must run on the cloud host, or be an explicitly budgeted hosted inference dependency with timeout, quota and fallback. Batch document embeddings may run later; publish a validated compatible embedding version before activating it.
- [ ] Provide a lexical/topic fallback if embeddings or the encoder are unavailable. Identify the fallback honestly in the response/UI.
- [ ] Give concise explanations based on actual evidence, such as “matches your selected interest in graph learning” or “similar abstract.” Do not present cosine similarity as probability or quality.
- [ ] Report at minimum: nDCG@10, judged Recall@50, latency, duplicate-family rate, coverage, freshness mix, and results sliced by source/topic/year/text availability. Include the baseline and model/data revisions.
- [ ] Keep a failure analysis with false positives, false negatives, five instructive examples, and known evaluation limitations. Do not claim the model improved unless a locked held-out comparison supports it.

**Exit evidence:** an end-to-end visitor can request recommendations; offline results are reproducible against the lexical and recency baselines; degraded mode works.

### 3. Make catalog records suitable for public recommendations

- [ ] Produce a fresh read-only catalog audit with totals, source/year/type/topic/abstract distributions, duplicates and identity conflicts. Do not use stale counts as current evidence.
  - _Status 2026-10-02:_ `athena audit` produces it, and the development catalog's report is recorded. Rerun on the server catalog after seeding; its counts will differ.
- [ ] Reconcile confirmed duplicates through a backed-up, audited migration that preserves identifiers, source records and links. Do not auto-merge on title alone. Represent preprint/publication families so one work cannot occupy many slots.
- [x] Add normalized content hashes and content revisions. Separate “fetched again” from “content changed” so metadata replay cannot cause needless embedding/model churn.
  - _Status 2026-10-02:_ Migration `0002` adds a generated hash of the title and abstract, a revision, and a change time. The importer advances the revision only when the text changes; covered by `test_replay_keeps_the_content_revision_and_a_text_change_advances_it` and two related tests. Applied to the development catalog: 7,765 papers backfilled at revision 1.
- [ ] Add explicit `retracted`/withdrawn/suppressed eligibility state, reason, source and checked time. Refresh known works so a retraction can remove a record from search and every candidate path. Filtering retracted works only during new imports is insufficient.
- [ ] Define how to treat unknown, incomplete, stale or conflicting source records. Hide, label, or hold them for review rather than manufacture certainty.
- [ ] Check sample records in the actual rendered UI for title, author, date, venue, source link, DOI and attribution correctness. Make missing abstracts/venues obvious.
- [x] Retain upstream request pacing, retries, provider budgets, import run status and safe errors. Provider outages must not take down public browsing.
  - _Status 2026-10-02:_ Unchanged and covered by the provider and import tests. Web requests never call a provider, and a failed scheduled refresh only stops that run.

**Exit evidence:** a current data quality report, controlled reconciliation history, clear retraction policy, and sampled rendered records that match the source.

### 4. Secure the public application boundary

- [ ] Deploy behind HTTPS at `athena.isaiahmcnealy.com`. Verify the certificate chain, HTTP-to-HTTPS redirect, canonical host, renewal, and direct origin access restrictions.
  - _Status 2026-10-02:_ Caddy in the release stack obtains the certificate and redirects HTTP. Checked locally with Caddy's internal certificate. The real certificate, renewal, and origin restrictions need the host.
- [ ] Keep the database private. Expose only required HTTP routes on the reverse proxy/edge. Block `/metrics`, interactive API docs if not intended for public use, and every internal/admin route from public access.
  - _Status 2026-10-02:_ PostgreSQL has no published port, and the proxy answers 404 for `/metrics`; both are checked locally and in the release smoke test. `/docs` stays public by decision (ADR 002). External verification needs the host.
- [ ] Set and test trusted host and proxy-header handling. Trust forwarded headers only from the chosen edge. Prevent host-header and spoofed client-IP errors in logs and throttling.
  - _Status 2026-10-02:_ The app accepts only configured host names and takes the client address from forwarded headers only when they come from the proxy. Checked locally (wrong host rejected, spoofed header ignored). Needs repeating on the host.
- [ ] Add rate limits for search, paper detail, recommendation and any mutation/feedback endpoint; cap body/query/page sizes, open connections and request duration. Return useful 429s. Apply stricter limits to expensive inference.
  - _Status 2026-10-02:_ Pages and the API allow 120 requests per client per minute and return 429 with Retry-After. Body size, query length, page size, and query duration are capped, and the web server answers 503 beyond 64 requests in flight. Inference limits wait for the recommender.
- [ ] Add explicit app, database and model CPU/memory limits; request concurrency bounds; disk monitoring; container log rotation; process restart policy; and graceful shutdown.
  - _Status 2026-10-02:_ Memory and CPU limits, log rotation, restart policies, and shutdown grace periods are set in the release stack. A throwaway container confirmed a clean exit on stop and 503 responses beyond the connection cap. Disk monitoring is still open.
- [x] Use separate PostgreSQL roles for runtime reads/writes, migrations and ingestion. The web process must not use the bootstrap/owner role. Restrict privileges by required tables/actions.
  - _Status 2026-10-02:_ `deploy/roles.sql` gives the web app a read-only role and the importer a rows-only role; migrations alone use the owner. Deployment reapplies it, and the release smoke test proves the web role cannot write and the importer cannot drop tables.
- [ ] Store provider keys and database secrets in the host/platform secret facility, not the repo, image, logs or browser. Use high-entropy credentials; rotate and document how.
  - _Status 2026-10-02:_ Secrets live in the server's `.env` (mode 600). Deployment requires three separate 64-character passwords, and rotating the two role passwords is documented. Nothing exists on a host yet.
- [x] Validate request schemas and source-derived URLs. Keep Jinja autoescaping. Retain secure response headers. Test malicious HTML, external links, malformed filters/cursors, oversized input and SQL/URL edge cases.
  - _Status 2026-10-02:_ Covered by tests for oversized and malformed filters, hostile search terms, literal venue wildcards, forged cursors, markup injection through stored and reflected values, external link attributes, and security headers. The tests exposed and fixed two defects: a NUL byte in a search returned 503, and a forged cursor returned 500. Unsafe source links were already rejected at import.
- [ ] Do not add authentication as an improvised home-built password feature. If accounts are enabled at launch, use a maintained OIDC provider/library, secure session cookies, CSRF protection for state changes, login abuse limits, logout/revocation, and object-level access checks.
- [ ] If collecting reading interests, saves, feedback or analytics, disclose what is stored and why. Minimize anonymous identifiers, set retention limits, avoid raw interests/query text in logs, and provide delete/reset controls. Do not retain person-level histories by default for anonymous visitors.
  - _Status 2026-10-02:_ The preview collects none of these. The About page says so, and the container no longer writes access logs with addresses or search terms. Revisit when interests or feedback are added.
- [ ] Add a license/attribution page for sources and any model. Provide a contact/abuse path and short privacy notice appropriate to the actual data collection. Do not claim legal compliance without a jurisdiction-specific review.
  - _Status 2026-10-02:_ The About page covers sources, attribution, data handling, and a contact path. Add the model's license when an encoder is chosen.
- [ ] Add dependency and container-image security checks, secret scanning, patch ownership, a process for updating pinned GitHub Actions and images, and a private vulnerability reporting/contact method.
  - _Status 2026-10-02:_ Dependabot is configured for Python packages, container images, and actions. Secret scanning and private vulnerability reporting are repository settings still to switch on; image scanning is not set up.

**Exit evidence:** verify externally that public users cannot reach PostgreSQL, metrics, debug/admin endpoints, or other users’ data; inspect headers, throttling, TLS, secrets and public error responses.

### 5. Move releases from the travel-dependent host

- [ ] Choose an always-on cloud origin. For a lowest-cost first deployment, use a small Linux VPS with Docker Compose and the database on the same private host. Size from measurements; a small app may start around 2 GB for lexical-only service, while database plus resident encoder may require about 4 GB. This is a starting estimate, not a guarantee.
  - _Status 2026-10-02:_ Chosen: a dedicated AWS Lightsail server, recorded in ADR 002. The server has not been created yet, and its size is an estimate until measured.
- [x] Keep public serving independent of the Mac mini. Use the mini for development and optional offline/batch experiments; never make it a live request dependency.
  - _Status 2026-10-02:_ The release stack runs entirely on the cloud server; nothing a request needs is on the Mac mini.
- [ ] Build a Linux AMD64 image for the chosen x86 VPS. If using ARM compute, verify every runtime image and native dependency is ARM64 compatible. Current `deploy/compose.yaml` explicitly pins `linux/arm64`.
  - _Status 2026-10-02:_ The release workflow now builds AMD64 and the ARM64 pins are removed from `deploy/compose.yaml`. The workflow has not run in GitHub Actions since the change.
- [ ] Create dev/staging/production environment separation or clearly documented staging/prod configuration. Use a distinct production database, secrets and image tags.
  - _Status 2026-10-02:_ Development (root Compose file) and production (`deploy/`) use separate databases, secrets, and image digests, and the guide documents both. There is no staging environment.
- [x] Deploy immutable image digests. Keep CI credentials restricted; pull requests must not receive server or production secrets.
  - _Status 2026-10-02:_ Unchanged: the pipeline deploys by digest, deployment secrets sit in the `production` environment, and pull requests run checks only.
- [x] Run migrations as a distinct release step after a backup. Use expand/contract migrations that the old app can tolerate during recovery. Do not make automatic destructive schema downgrades.
  - _Status 2026-10-02:_ Unchanged and covered by `tests/test_deployment.py`: backup, then migration, then roles, then the web container. Expand/contract remains a rule for each future migration.
- [ ] Add rollback for the application and embedding/model release. Retain a known-good image/model index; refuse incompatible vector dimensions/recipes at startup or promotion.
  - _Status 2026-10-02:_ Application rollback is documented in the deployment guide. Model rollback waits for the recommender.
- [x] Replace Mac mini-only assumptions in the current workflow/guide: macOS SSH paths, Tailscale-to-mini deployment, ARM-only build, loopback `8001` origin and host-local backup expectations.
  - _Status 2026-10-02:_ The workflow, Compose file, scripts, and guide now target a generic Linux server behind Caddy, with an optional off-host backup copy.
- [ ] Pin production PostgreSQL major version and schedule upgrades as planned maintenance. Add the required pgvector extension image/version if embeddings are enabled.
- [ ] Configure DNS for only `athena.isaiahmcnealy.com`. Preserve existing DNS/site records for `isaiahmcnealy.com`. Add a deployment check for the expected hostname and TLS endpoint.
  - _Status 2026-10-02:_ The release job now checks the public URL with certificate validation after deploying. The Route 53 record itself is still to be created.
- [ ] Document billable resources, budget alerts, provider account recovery, SSH/console recovery and emergency access. Turn on a spend alert and test it where available.
  - _Status 2026-10-02:_ ADR 002 lists the expected cost and a proposed alert threshold. Account recovery, console access, and the alert itself are still open.

**Exit evidence:** a release from the protected branch builds the correct platform image, deploys that image to the cloud host, runs migration/readiness checks, and can roll back to the prior compatible release.

### 6. Make data recoverable and operations observable

- [ ] Run scheduled encrypted PostgreSQL backups to storage outside the VPS/account/host failure domain. Set an explicit retention policy and restrict backup access.
  - _Status 2026-10-02:_ `deploy/backup.sh` writes dated dumps, prunes after 14 days, and can copy to S3; the cron entry is documented. The bucket, its encryption, and the schedule do not exist until the host does.
- [ ] Perform a clean restore into a disposable PostgreSQL instance. Verify schema version, canonical papers, identifiers, source provenance, recommendation embeddings and any user data. Record elapsed restore time and counts.
  - _Status 2026-10-02:_ A scheduled dump from the local release stack restored into a separate database with matching counts (5 papers). Repeat on the host with the real catalog and record the elapsed time.
- [ ] Define achievable RPO/RTO for 1.0. For a low-cost single-host demo, an initial target might be RPO 24 hours/RTO 2 hours; record whether an actual drill meets it.
  - _Status 2026-10-02:_ Targets are stated in ADR 002. No drill has measured them.
- [ ] Create an external availability check for the public hostname and a separate readiness check for database/schema. Liveness should remain independent of the provider APIs.
  - _Status 2026-10-02:_ The uptime workflow checks public readiness and that the catalog is not empty every 15 minutes once `PUBLIC_URL` is set. Liveness does not depend on the database or providers.
- [ ] Alert on downtime, repeated 5xx, high latency, disk exhaustion, backup failure, stale ingest, embedding queue age, failed model load and provider budget exhaustion. Test that an alert reaches the owner.
  - _Status 2026-10-02:_ Only the uptime workflow's failure email exists. The other alerts are open.
- [x] Capture request ID, bounded route, status and latency. Add worker/model release context where useful. Keep secrets, user identifiers, raw queries, abstracts and interests out of logs/traces and metric labels.
  - _Status 2026-10-02:_ Unchanged structured request logs. The container's access log is now off, so addresses and search terms are not written; checked on the local release stack.
- [ ] Add an operator runbook for restart, disk pressure, provider outage, stuck import, bad model promotion, compromised key, failed backup, database restore and rollback.
  - _Status 2026-10-02:_ The [server runbook](runbook.md) and deployment guide cover restart, disk pressure, provider outage, stuck import, compromised key, failed backup, restore, and rollback. Bad model promotion waits for the recommender, and none of it has been exercised on a real server.
- [ ] Run a failure drill: stop database, stop worker, fill/approach disk limit in staging, make encoder unavailable and deploy a deliberately unhealthy app. Confirm useful error behavior and recovery.
- [ ] Perform one public load test against Athena only, never the source providers. State host specs, corpus size, request mix, concurrency, p50/p95/p99, errors and memory. Choose a small initial target such as 10 requests/second only if it fits the expected demo, then record the measured result.

**Exit evidence:** successful restore and failure-drill records; alerts work; measured load and SLO statements reflect observed values.

### 7. Finish the public product and portfolio presentation

- [ ] Show search sort and filters, source/provenance, paper details, similar papers, personalized feed, explanation and fallback states.
- [ ] Include a first-visit path, interest selection/sample persona, empty results, loading, error, offline-model fallback, missing metadata and stale-data states.
- [ ] Make recommendations usable on mobile, by keyboard and with screen readers; check labels, focus, contrast, zoom and touch targets. Target WCAG 2.2 AA; document manual checks.
- [ ] Clearly distinguish “most relevant” and “newest.” Explain recommendation reasons and what interest/session data is retained.
  - _Status 2026-10-02:_ The results page has a Most relevant / Newest control, and the About page explains both and what data is kept. Recommendation reasons wait for the recommender.
- [ ] Add branded metadata, page titles/descriptions, favicon, contact/about, privacy/source information and a link back to the portfolio. Confirm deep links work on refresh and the app fits the portfolio’s security framing policy.
  - _Status 2026-10-02:_ Page titles, description, and favicon exist; the About page adds contact, source, data handling, and a portfolio link. Social preview metadata is not added.
- [ ] Publish a 60–90 second screen-recorded walkthrough and a case study with architecture, measured quality/latency/cost, a failure/recovery story, and limitations. Keep a static portfolio explanation if the demo is temporarily unavailable.
- [ ] Have at least three people unfamiliar with Athena attempt: find a paper, explain why a recommendation appeared, and recover from no results. Record and fix confusing points.

**Exit evidence:** visitor can finish core tasks without developer help; accessibility/usability review has findings and resolutions.

## P1: required if 1.0 retains personal accounts or private libraries

If Athena is launched without persistent personal data, defer these until after 1.0 and keep user state in a session with clear expiry. If it stores user-specific data at launch, all of this becomes P0:

- [ ] OIDC login, secure session lifecycle, email/provider verification policy and account deletion.
- [ ] Database ownership keys and authorization on every API read, write, export and background job. Test that two users cannot access each other’s objects by changing IDs.
- [ ] Collections, saves, reading status, feedback reasons, follows and preference reset. Distinguish a deliberate dislike from a dismissal or “already read.”
- [ ] Validated, escaped notes and exports. Rate limit mutation endpoints and add CSRF protection.
- [ ] Data inventory, privacy notice, user export/deletion workflow, event retention and cache/profile invalidation. Define how deletion is reapplied after backup restoration.
- [ ] Consent rules and opt-out for analytics/digests. Do not use demo/sample persona activity to train or evaluate real-user behavior models.
- [ ] Explicit recommendation impression logging only when a result is actually shown. Store model version and list position; deduplicate repeated deliveries.
- [ ] Account recovery/support process that does not expose private library contents.

## Release verification and sign-off

Complete against a production-like staging environment built from the same image and migration path planned for production.

### Code and data

- [ ] Set application/package/container metadata and documentation to 1.0.0. Review changelog, migration order, supported runtime and rollback target.
- [ ] Confirm lockfile and container build are reproducible; image runs as non-root; no provider secret is present in image/history/logs.
- [ ] Run the complete unit, provider, integration and deployment test suites against disposable PostgreSQL matching production major/extension versions. Verify tests refuse to reset non-test databases.
- [ ] Confirm new migrations upgrade both an empty schema and a copy of the current catalog. Check the rendered search/detail pages after migration.
- [ ] Re-import sample provider queries and verify identifier idempotency, conflict handling, provenance, source cooldown, safe logs and recovery after interruption.
- [ ] Confirm model artifact metadata matches stored vectors; reject partial/stale/incompatible release; restore prior model and verify response.
- [ ] Make sure sample data and fixtures are clearly labeled. Public demo recommendations should be based on real metadata, not fabricated papers.

### Public and operations checks

- [ ] Verify `https://athena.isaiahmcnealy.com` from a device outside the deployment network, including redirects, certificate, search, paper detail and recommendation deep links.
- [ ] Verify app-origin ports and PostgreSQL are not directly reachable. Public metrics/docs/admin paths return 404/403 at edge and application as intended.
- [ ] Exercise request limits, malformed inputs, stored/reflected HTML safety, timeouts and error pages.
- [ ] Verify external health monitoring/alerts, backup completion, restore drill, logs, disk alarms and cost alert.
- [ ] Run the failure drills and load test above, attach evidence to the release record, and make sure there are no unresolved critical/high findings.
- [ ] Check new-user relevance, sample-interest recommendations, diversity, duplicate suppression, filters, cold start and encoder failure fallback with a human reviewer.
- [ ] Review mobile, keyboard and accessibility checks; verify privacy/source/attribution content and portfolio case study.
- [ ] Record the final image digest, database migration head, encoder/index revision, evaluation report, deployment time, deployment owner and rollback command.
- [ ] Publish a dated 1.0 release note with resolved known limitations and measured results. Enable the public DNS route only after the release candidate passes.

**Release decision:** the maintainer signs off only when every P0 item is completed or an explicitly accepted limitation has an owner, impact statement and mitigation. Any auth/privacy P1 item is required before the associated personal-data feature is enabled.

## After 1.0

These can follow the public launch: learned behavior ranker/collaborative filtering, cross-encoder reranking, citation graph, email digests, broader engineering-feed ingestion, full-text article processing, high availability, autoscaling, multi-region recovery, separate queue service, and Kubernetes. Promote these only after a measured product or operating need.

Avoid claiming high availability, complete scholarly coverage, model superiority, or representative user behavior without evidence. Public launch is a milestone; it is not a substitute for continuing to watch real service health and recommendation quality.
