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

Before public deployment: configure HTTPS, private database networking, non-default secrets,
backups/restore drills, trusted proxy settings, rate limits, and private metrics. Authentication is
required before personal collections are added. Validate migrations and load-test on specified
hardware. This initial release makes no unmeasured throughput or availability claims.
