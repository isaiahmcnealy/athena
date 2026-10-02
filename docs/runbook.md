# Server runbook

What to check and do when the public server misbehaves. Setup and releases are in the
[deployment guide](deployment.md); this page assumes that guide's layout under `~/athena`.
Nothing here has been exercised on a real server yet. Correct it after the first incident
or drill.

Commands use this shorthand, which runs Docker Compose against the last successful release:

```sh
m() { bash ~/athena/current/manage.sh "$@"; }
```

## First look

```sh
m ps                                            # which containers are up and healthy
m logs --tail=100 web                           # request logs and errors
curl --fail http://127.0.0.1:8001/health/ready  # app and database, bypassing the proxy
df -h / && docker system df                     # free disk
tail -n 20 ~/athena/logs/refresh.log ~/athena/logs/backup.log
```

| Symptom | Likely cause | Go to |
| --- | --- | --- |
| Browser cannot connect, or certificate warning | Proxy down, DNS, or certificate | [Site unreachable](#site-unreachable) |
| "Catalog temporarily unavailable" or readiness fails | Database down or out of disk | [Database unavailable](#database-unavailable) |
| Bare `503` under load | More than 64 requests in flight | Wait; check for abuse in `m logs web` |
| `429` for one visitor | Per-client limit reached | [Deployment guide](deployment.md#failure-and-recovery) |
| "Synced" date on the home page is old | Refresh failing | [Refresh failing](#refresh-failing-or-provider-outage) |
| Uptime check fails on catalog size | Empty or wrong database | [Database unavailable](#database-unavailable) |

## Site unreachable

1. From the server, check the app without the proxy: `curl --fail http://127.0.0.1:8001/health/live`.
2. If that works, the problem is the proxy, DNS, or the firewall. Check `m logs --tail=100 caddy`,
   that `dig +short athena.isaiahmcnealy.com` returns the server's address, and that ports
   80 and 443 are open in the provider's firewall.
3. Restart one service with `m up -d --no-deps --wait caddy` or `m up -d --no-deps --wait web`.
4. After a reboot, containers return on their own once Docker starts. If they do not, start
   them in order: `m up -d --wait db`, then `web`, then `caddy` as above.

Do not delete the `caddy_data` volume. It holds the certificate, and repeated reissue can hit
the certificate authority's rate limits.

## Database unavailable

1. `m ps` and `m logs --tail=100 db`. A full disk shows as write errors or a refusal to start.
2. If the disk is full, free space first (next section), then `m up -d --wait db`.
3. Confirm with `curl --fail http://127.0.0.1:8001/health/ready` and
   `m run --rm --no-deps ingest stats`.
4. If data is missing or damaged, follow the restore steps in the
   [deployment guide](deployment.md#failure-and-recovery). Restore into a separate database
   and compare counts before replacing anything.

## Disk pressure

```sh
du -sh ~/athena/backups ~/athena/releases
docker system df
```

Free space in this order, checking `df -h /` after each step:

1. Release directories other than the ones `~/athena/current` and `~/athena/previous` point to.
2. Pre-release dumps in `~/athena/backups` older than the newest scheduled dump you have
   verified. Scheduled dumps prune themselves.
3. Unused images: `docker image prune -a --filter "until=720h"`. This keeps recent images,
   including the previous release needed for a rollback.

Never run `docker volume prune` or `docker system prune --volumes` on this server. The
catalog and the certificate live in volumes.

## Refresh failing or provider outage

Browsing and search do not depend on arXiv or OpenAlex, so a provider outage only delays
new papers.

1. Read the last run in `~/athena/logs/refresh.log`. A `seed_stopped` event names the job
   and a safe provider error.
2. For a provider error such as an HTTP 429 or 503, wait. The next scheduled run starts over,
   and replayed records update in place. Do not retry in a loop.
3. If OpenAlex reports an exhausted budget every day, set `OPENALEX_API_KEY` in
   `~/athena/.env` or lower `REFRESH_PER_QUERY`.
4. To refresh one provider by hand:
   `m run --rm --no-deps ingest seed --per-query 50 --source arxiv`.
5. A `partial` status means a record was rejected for an identity conflict. The catalog is
   intact. Resolve the conflict by review; never delete identifiers to make an import pass.

## Stuck import

A killed import leaves its run marked `running` and may leave `~/athena/.refresh-lock`.

1. Confirm nothing is importing: `docker ps --filter name=ingest`.
2. Remove a stale lock with `rmdir ~/athena/.refresh-lock`.
3. Count stale runs with `m run --rm --no-deps ingest audit` (see `imports_left_running`).
   Committed records are safe, and rerunning the import is idempotent.
4. To close the stale runs so the audit is clean again:

   ```sh
   m exec db psql -U athena -d athena -c "UPDATE import_runs SET status = 'failed', \
     finished_at = now(), error = 'Closed by operator after an interrupted import' \
     WHERE status = 'running' AND started_at < now() - interval '1 hour'"
   ```

## Failed backup

1. Read `~/athena/logs/backup.log`. A failed run leaves no partial file and deletes nothing.
2. Usual causes: the database container is down, the disk is full, or the S3 credentials or
   bucket policy changed. If only the upload failed, the local dump was still written.
3. Fix the cause and run `bash ~/athena/current/backup.sh` by hand. Check that a new
   `scheduled-*.dump` exists and, if configured, that it reached the bucket.
4. If backups have been failing for longer than the recovery point you promised, say so in
   your records. The catalog can be rebuilt with `athena seed`, but not to the same state.

## Compromised or leaked secret

Rotate first, investigate second. After any rotation, read `m logs web` and the
`import_runs` table for activity you do not recognize.

| Secret | Rotate by |
| --- | --- |
| `ATHENA_WEB_DB_PASSWORD`, `ATHENA_INGEST_DB_PASSWORD` | Put new `openssl rand -hex 32` values in `~/athena/.env`, then rerun the Release workflow on `master`. Deployment recreates the database container with the new values and reapplies the roles. |
| `POSTGRES_PASSWORD` (owner) | Open `m exec db psql -U athena -d athena`, run `\password athena`, enter a new 64-character hex value, put the same value in `~/athena/.env`, then rerun the Release workflow. Both must match. |
| Deploy SSH key | Remove its line from `~/.ssh/authorized_keys` on the server, create a new key pair, add the public key, and replace the `DEPLOY_SSH_KEY` secret in GitHub. |
| Tailscale OAuth client | Revoke it in the Tailscale admin console, create a new one, and replace `TS_OAUTH_CLIENT_ID` and `TS_OAUTH_SECRET`. |
| OpenAlex API key | Replace it at OpenAlex and in `~/athena/.env`. The next import reads the new value; no redeploy is needed. |
| GHCR token on the server | Revoke it in GitHub, then run `docker login ghcr.io` again with a new one. |
| AWS backup credentials | Deactivate the access key in IAM, create a new one, and run `aws configure` on the server. |

Rerun the Release workflow rather than running `deploy.sh` by hand from the current release
directory, which would overwrite the `previous` pointer used for rollback.

## Rollback and restore

Application rollback and database restore are in the
[deployment guide](deployment.md#failure-and-recovery). There is no model to roll back until
recommendations exist.
