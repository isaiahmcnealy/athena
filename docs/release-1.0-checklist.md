# Athena 1.0 public release checklist

**Purpose:** bring the current Athena catalog to a safe, useful, always-on public research discovery and recommendation service at `athena.isaiahmcnealy.com`.

**Release policy:** do not advertise version 1.0 as ready until the P0 release gates below have an owner, implementation, and recorded evidence. “Works on my machine,” green CI, a running container, and a DNS record by themselves are not release evidence.

## Release definition

Athena 1.0 should let a first-time visitor search real technical papers, get useful recommendations from chosen interests or a paper they like, understand why items were suggested, and open the original scholarly record. The service must stay usable without an account. A visitor’s session may hold temporary interests; retain personal library/history only after implementing account access controls, disclosure, retention, export and deletion.

Host the application and database on an always-on cloud instance because the owner travels with the Mac mini. Keep the Mac mini for development and optional background embedding work. All components required to answer a live request must remain available when the mini is offline. A small single-host deployment is acceptable for an early portfolio release when its single-host availability limit, monitoring, backup and restore have been disclosed and verified.

## Current state and the release gap

The repository currently identifies itself as release **0.1.0**. It has a FastAPI/Jinja app, PostgreSQL schema and full-text search, arXiv/OpenAlex importers, provenance, request logs/metrics, database migrations, CI, and a digest-based Mac mini Compose release path. The app is not yet a recommender. The README explicitly says accounts and recommendations are planned. There is no embedding/index pipeline, feedback/profile store, recommendation API, authentication, public ingress configuration, off-host backup configuration, or verified live host.

Current search matches PostgreSQL full-text tokens and sorts by publication date; it does not rank matching papers by learned or lexical relevance. OpenAlex abstracts are excluded. Ingestion requests exclude retracted OpenAlex works, but existing records have no retraction/tombstone lifecycle. The deployment Compose file gives the same PostgreSQL account to web, migration and ingestion. `/metrics` is served publicly by the application unless the network boundary blocks it. These are release work items, not hypothetical future scale problems.

Prior local verification: 35 non-integration tests passed, 15 integration tests were deselected, and lint/format checks passed. This does not verify PostgreSQL integration, current cloud configuration, public behavior, or recovery. Run the full applicable release checks on the actual deployment candidate before launch.

## P0: required before opening the site to the public

### 1. Decide and freeze what 1.0 promises

- [ ] Write a short product contract: target readers, supported topics, publication types, recommendation surfaces, and supported locale.
- [ ] Keep the first public release focused on AI/ML and adjacent technical scholarship. Label preprints, journal articles, conference papers and reviews accurately. Do not imply that all catalog entries are peer-reviewed.
- [ ] Decide whether recommendations use an anonymous, temporary profile or account-backed profile. Anonymous discovery must work without login. If any per-user interests, events, saves, notes, or history are retained, complete P1 identity/privacy items before enabling that storage.
- [ ] Define the sources and permitted fields used by the system. Keep source URLs, identifiers and provenance visible. Do not download or redistribute full papers without checking rights for the particular work.
- [ ] Pick an explicit initial serving and availability target. A single VPS cannot provide host-level high availability. State the measured limits instead of promising enterprise uptime.
- [ ] Add 1.0 acceptance criteria and the target deployment region, provider, instance size, backup target and monthly budget to an ADR.

**Exit evidence:** a reviewed product/release note and one scope that can be completed without unresolved policy or cost decisions.

### 2. Make the recommender real and measurable

- [ ] Fix the search contract: add a relevance sort using a documented lexical score and preserve “Newest” as a separate sort. Exact title/DOI searches should behave predictably.
- [ ] Add a curated, versioned evaluation set with a written 0–3 relevance rubric. Begin with at least 30 queries across exact technical phrases, conceptual searches, application areas, foundational work, recent work, rare topics, missing abstracts and restrictive filters. Keep a held-out subset out of tuning.
- [ ] Record catalog coverage and bias by year, source, topic, publication type and abstract availability. Audit documented duplicates and historical data skew before using offline metrics.
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
- [ ] Reconcile confirmed duplicates through a backed-up, audited migration that preserves identifiers, source records and links. Do not auto-merge on title alone. Represent preprint/publication families so one work cannot occupy many slots.
- [ ] Add normalized content hashes and content revisions. Separate “fetched again” from “content changed” so metadata replay cannot cause needless embedding/model churn.
- [ ] Add explicit `retracted`/withdrawn/suppressed eligibility state, reason, source and checked time. Refresh known works so a retraction can remove a record from search and every candidate path. Filtering retracted works only during new imports is insufficient.
- [ ] Define how to treat unknown, incomplete, stale or conflicting source records. Hide, label, or hold them for review rather than manufacture certainty.
- [ ] Check sample records in the actual rendered UI for title, author, date, venue, source link, DOI and attribution correctness. Make missing abstracts/venues obvious.
- [ ] Retain upstream request pacing, retries, provider budgets, import run status and safe errors. Provider outages must not take down public browsing.

**Exit evidence:** a current data quality report, controlled reconciliation history, clear retraction policy, and sampled rendered records that match the source.

### 4. Secure the public application boundary

- [ ] Deploy behind HTTPS at `athena.isaiahmcnealy.com`. Verify the certificate chain, HTTP-to-HTTPS redirect, canonical host, renewal, and direct origin access restrictions.
- [ ] Keep the database private. Expose only required HTTP routes on the reverse proxy/edge. Block `/metrics`, interactive API docs if not intended for public use, and every internal/admin route from public access.
- [ ] Set and test trusted host and proxy-header handling. Trust forwarded headers only from the chosen edge. Prevent host-header and spoofed client-IP errors in logs and throttling.
- [ ] Add rate limits for search, paper detail, recommendation and any mutation/feedback endpoint; cap body/query/page sizes, open connections and request duration. Return useful 429s. Apply stricter limits to expensive inference.
- [ ] Add explicit app, database and model CPU/memory limits; request concurrency bounds; disk monitoring; container log rotation; process restart policy; and graceful shutdown.
- [ ] Use separate PostgreSQL roles for runtime reads/writes, migrations and ingestion. The web process must not use the bootstrap/owner role. Restrict privileges by required tables/actions.
- [ ] Store provider keys and database secrets in the host/platform secret facility, not the repo, image, logs or browser. Use high-entropy credentials; rotate and document how.
- [ ] Validate request schemas and source-derived URLs. Keep Jinja autoescaping. Retain secure response headers. Test malicious HTML, external links, malformed filters/cursors, oversized input and SQL/URL edge cases.
- [ ] Do not add authentication as an improvised home-built password feature. If accounts are enabled at launch, use a maintained OIDC provider/library, secure session cookies, CSRF protection for state changes, login abuse limits, logout/revocation, and object-level access checks.
- [ ] If collecting reading interests, saves, feedback or analytics, disclose what is stored and why. Minimize anonymous identifiers, set retention limits, avoid raw interests/query text in logs, and provide delete/reset controls. Do not retain person-level histories by default for anonymous visitors.
- [ ] Add a license/attribution page for sources and any model. Provide a contact/abuse path and short privacy notice appropriate to the actual data collection. Do not claim legal compliance without a jurisdiction-specific review.
- [ ] Add dependency and container-image security checks, secret scanning, patch ownership, a process for updating pinned GitHub Actions and images, and a private vulnerability reporting/contact method.

**Exit evidence:** verify externally that public users cannot reach PostgreSQL, metrics, debug/admin endpoints, or other users’ data; inspect headers, throttling, TLS, secrets and public error responses.

### 5. Move releases from the travel-dependent host

- [ ] Choose an always-on cloud origin. For a lowest-cost first deployment, use a small Linux VPS with Docker Compose and the database on the same private host. Size from measurements; a small app may start around 2 GB for lexical-only service, while database plus resident encoder may require about 4 GB. This is a starting estimate, not a guarantee.
- [ ] Keep public serving independent of the Mac mini. Use the mini for development and optional offline/batch experiments; never make it a live request dependency.
- [ ] Build a Linux AMD64 image for the chosen x86 VPS. If using ARM compute, verify every runtime image and native dependency is ARM64 compatible. Current `deploy/compose.yaml` explicitly pins `linux/arm64`.
- [ ] Create dev/staging/production environment separation or clearly documented staging/prod configuration. Use a distinct production database, secrets and image tags.
- [ ] Deploy immutable image digests. Keep CI credentials restricted; pull requests must not receive server or production secrets.
- [ ] Run migrations as a distinct release step after a backup. Use expand/contract migrations that the old app can tolerate during recovery. Do not make automatic destructive schema downgrades.
- [ ] Add rollback for the application and embedding/model release. Retain a known-good image/model index; refuse incompatible vector dimensions/recipes at startup or promotion.
- [ ] Replace Mac mini-only assumptions in the current workflow/guide: macOS SSH paths, Tailscale-to-mini deployment, ARM-only build, loopback `8001` origin and host-local backup expectations.
- [ ] Pin production PostgreSQL major version and schedule upgrades as planned maintenance. Add the required pgvector extension image/version if embeddings are enabled.
- [ ] Configure DNS for only `athena.isaiahmcnealy.com`. Preserve existing DNS/site records for `isaiahmcnealy.com`. Add a deployment check for the expected hostname and TLS endpoint.
- [ ] Document billable resources, budget alerts, provider account recovery, SSH/console recovery and emergency access. Turn on a spend alert and test it where available.

**Exit evidence:** a release from the protected branch builds the correct platform image, deploys that image to the cloud host, runs migration/readiness checks, and can roll back to the prior compatible release.

### 6. Make data recoverable and operations observable

- [ ] Run scheduled encrypted PostgreSQL backups to storage outside the VPS/account/host failure domain. Set an explicit retention policy and restrict backup access.
- [ ] Perform a clean restore into a disposable PostgreSQL instance. Verify schema version, canonical papers, identifiers, source provenance, recommendation embeddings and any user data. Record elapsed restore time and counts.
- [ ] Define achievable RPO/RTO for 1.0. For a low-cost single-host demo, an initial target might be RPO 24 hours/RTO 2 hours; record whether an actual drill meets it.
- [ ] Create an external availability check for the public hostname and a separate readiness check for database/schema. Liveness should remain independent of the provider APIs.
- [ ] Alert on downtime, repeated 5xx, high latency, disk exhaustion, backup failure, stale ingest, embedding queue age, failed model load and provider budget exhaustion. Test that an alert reaches the owner.
- [ ] Capture request ID, bounded route, status and latency. Add worker/model release context where useful. Keep secrets, user identifiers, raw queries, abstracts and interests out of logs/traces and metric labels.
- [ ] Add an operator runbook for restart, disk pressure, provider outage, stuck import, bad model promotion, compromised key, failed backup, database restore and rollback.
- [ ] Run a failure drill: stop database, stop worker, fill/approach disk limit in staging, make encoder unavailable and deploy a deliberately unhealthy app. Confirm useful error behavior and recovery.
- [ ] Perform one public load test against Athena only, never the source providers. State host specs, corpus size, request mix, concurrency, p50/p95/p99, errors and memory. Choose a small initial target such as 10 requests/second only if it fits the expected demo, then record the measured result.

**Exit evidence:** successful restore and failure-drill records; alerts work; measured load and SLO statements reflect observed values.

### 7. Finish the public product and portfolio presentation

- [ ] Show search sort and filters, source/provenance, paper details, similar papers, personalized feed, explanation and fallback states.
- [ ] Include a first-visit path, interest selection/sample persona, empty results, loading, error, offline-model fallback, missing metadata and stale-data states.
- [ ] Make recommendations usable on mobile, by keyboard and with screen readers; check labels, focus, contrast, zoom and touch targets. Target WCAG 2.2 AA; document manual checks.
- [ ] Clearly distinguish “most relevant” and “newest.” Explain recommendation reasons and what interest/session data is retained.
- [ ] Add branded metadata, page titles/descriptions, favicon, contact/about, privacy/source information and a link back to the portfolio. Confirm deep links work on refresh and the app fits the portfolio’s security framing policy.
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
