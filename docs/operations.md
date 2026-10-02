# Local operations

## Inspect

```sh
docker compose ps
docker compose logs --tail=100 web
curl --fail http://localhost:8000/health/ready
curl --fail http://localhost:8000/metrics
docker compose exec db psql -U athena -d athena -c 'SELECT source, status, processed, rejected, started_at FROM import_runs ORDER BY started_at DESC LIMIT 10'
```

Catalog cards show fetch freshness, not guaranteed publication or upstream completeness.
Metrics use route templates, never paper IDs or search terms, to keep label cardinality bounded.
Keep `/metrics` private; the UI itself has no administrative mutation endpoint.

## Safe retries

Rerun the same import command after a failed provider request or interrupted process. Unique
identifiers and per-record transactions preserve completed work. Inspect `import_runs` for failures
and identifier conflicts. A conflict leaves the existing catalog intact; manual resolution must
preserve all identifiers and source records. Do not delete identifiers merely to make an import pass.

Current imports process a bounded newest-first search window. They do not promise exhaustive delta
capture or exactly-once source delivery. Do not run load tests against upstream scholarly APIs.

## Catalog expansion

```sh
athena seed --dry-run --per-query 250   # the plan only; no network or database access
athena seed --per-query 250             # 42 queries, up to 10,500 requested records
athena stats                            # counts and storage after the run
athena audit                            # coverage by source, year, and type, plus quality checks
```

`athena audit` runs in one read-only transaction. It reports which fields are missing by
source and counts records that need review, such as papers sharing a title or imports left
running. It repairs nothing. The latest recorded run is the
[2026-10-02 catalog audit](reports/catalog-audit-2026-10-02.md).

Take a backup first (see below). The seed runs 21 topics against arXiv and OpenAlex, one query
at a time, and prints one JSON event per query. `inserted` counts new canonical papers;
`updated` counts records that resolved to a paper already in the catalog, through a replay,
an overlapping query, or a shared identifier. Only `athena stats` reports the unique total.

Provider budgets, as observed on 2026-10-02 and subject to change by the providers:

- arXiv: one request at a time with a 3-second pause between pages and between queries.
  A full seed makes 63 arXiv requests.
- OpenAlex without an API key: 1,000 credits per day at 10 credits per search page, so about
  100 pages. A full seed uses 63 pages (630 credits); a second full run on the same day does
  not fit. Set `OPENALEX_API_KEY` for a larger budget. An exhausted budget stops the import.

When a query fails, the seed stops and prints the job number and a safe provider error, for
example `Upstream HTTP 503 after 5 attempts`. Records committed before the failure stay in the
catalog. Resume with the same `--per-query` and `--source` values and `--start-at N`. The failed
query restarts from its first page; there is no page-level checkpoint, and the replayed records
count as `updated`.

### Measured trial (2026-10-02)

One run of `athena seed --per-query 250` on a development Mac against local PostgreSQL 17 in
Docker, without an OpenAlex API key. The plan had 20 topics and 40 queries at the time; the Oil
and gas topic was added and imported afterward. These are single-run observations, not guarantees.

| Measure | Result |
| --- | --- |
| Requested and processed records | 10,000 across 40 queries; 0 rejected, 0 failed queries |
| New canonical papers | 7,314 (4,055 from arXiv queries, 3,259 from OpenAlex queries) |
| Records resolved to an existing paper | 2,686 (overlapping queries and earlier imports) |
| Catalog size | 162 papers before, 7,476 after |
| Elapsed time | 8 min 34 s, mostly provider pacing |
| Importer peak memory | 140 MiB resident set size |
| Catalog tables and indexes | 1.7 MiB before, 55.4 MiB after: about 7.5 KiB per paper |
| Whole database | 9.3 MiB before, 63.3 MiB after |

Source payloads are the largest part of storage, followed by the papers table with its
full-text index. After adding Oil and gas (500 requested, 399 new papers) the catalog holds
7,875 papers in 58.6 MiB.

Search stayed responsive at 7,875 papers. Over 22 sequential local requests per case to
`GET /api/papers`, after `ANALYZE`:

| Request | Matches | Median | 95th percentile |
| --- | --- | --- | --- |
| Browse, no query | 7,875 | 8 ms | 11 ms |
| `q=graph neural` | 325 | 7 ms | 9 ms |
| `q=learning` | 2,717 | 8 ms | 10 ms |
| `q=learning&limit=100` | 2,717 | 20 ms | 24 ms |
| `q="language model" agent` | 393 | 12 ms | 13 ms |
| `q=learning&source=openalex` | 495 | 25 ms | 60 ms |
| `year=2026` | 7,692 | 13 ms | 17 ms |
| `venue=nature` | 25 | 25 ms | 31 ms |

This is one client with no concurrent load. It is not a load test.

Replay and overlap checks:

- Replaying one arXiv and one OpenAlex query (500 records) inserted 0 papers and left paper,
  source record, and identifier counts unchanged.
- All 198 identifiers present before the trial still map to the same papers.
- An earlier attempt failed on the second arXiv page of query 1 after committing 100 records.
  The rerun reported those 100 as `updated` and continued.

Known duplicates, left in place because merging removes paper rows and needs an operator decision:

- 55 papers appear twice, once from arXiv and once from an OpenAlex work that carries only the
  arXiv DOI. They were imported before arXiv DOIs were used for matching. New imports merge
  such records. Re-importing one of these 55 OpenAlex works is rejected as an identity conflict,
  which marks that query `partial` and stops the seed; continue with `--start-at` at the next
  job until the pairs are reconciled.
- About 300 OpenAlex papers are extra copies with the same title as another OpenAlex paper,
  almost all separate Zenodo version deposits with their own DOIs. No shared identifier links
  them, and titles never drive merges.
- 12 OpenAlex records from an import that predates the date and type filters have future
  publication dates or excluded types. The trial added none.

## Backup and recovery

For a local logical backup (the `artifacts` directory is ignored by Git):

```sh
mkdir -p artifacts
docker compose exec -T db pg_dump -U athena -d athena -Fc > artifacts/athena.dump
docker compose exec db createdb -U athena athena_restore
docker compose exec -T db pg_restore -U athena -d athena_restore < artifacts/athena.dump
```

Inspect counts and representative source mappings in `athena_restore`. Restoring into a separate
database avoids overwriting a working catalog. Never treat an untested backup as a recovery guarantee.

`docker compose down` retains the database volume. `docker compose down -v` destroys it.

## First failure experiments

- Replay an import; paper and identifier counts should remain stable.
- Stop the database; readiness and catalog requests should fail with 503 within bounded time.
  Liveness should remain 200. Restart and verify recovery.
- Inject provider 429/503 responses in tests; verify retry bounds and partial-progress preservation.
- Attempt a source record with identifiers belonging to two papers; verify safe rejection.

The local stack is for development only. The release stack in `deploy/` adds HTTPS, private
database networking, limited database roles, non-default secrets, trusted proxy handling, rate
limits, private metrics, and scheduled backups; see the [deployment guide](deployment.md).
Still open before a 1.0 claim: a recorded restore drill and load test on the real host.
Authentication is required before personal collections are added. This release makes no
unmeasured throughput or availability claims.
