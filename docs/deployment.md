# Releases on the cloud host

`develop` is for local development and testing. `master` is the release branch. Only a
push to `master` (or a manual Release run targeting `master`) can publish and deploy.
Pull requests run checks without deployment access. The hosting decision and its limits
are recorded in [ADR 002](decisions/002-public-preview-cloud-host.md).

```mermaid
flowchart LR
    D[develop: local Docker and testing] -->|merge approved changes| M[master]
    M --> T[GitHub: lint and PostgreSQL tests]
    T --> B[AMD64 build and container smoke test]
    B --> R[GHCR: image tagged with commit SHA]
    R -->|immutable digest| J[Deployment job]
    J -->|Tailscale + verified SSH| S[Cloud server]
    S --> P[Pull image]
    P --> K[Database backup]
    K --> A[Alembic migration]
    A --> L[Database roles]
    L --> W[Replace web container]
    W --> C[Start HTTPS proxy]
    C --> H[Public HTTPS check]
```

The GitHub runner connects to the server to run Docker Compose. It does not copy the
source repository or build on the server. Application images come from GHCR. PostgreSQL
data stays in the `athena-release_postgres_data` volume between releases. Server imports
populate that database separately from your laptop's development catalog.

## What is public

| Path | From the internet | Notes |
| --- | --- | --- |
| `/`, `/papers/{id}`, `/about` | Yes, HTTPS only | HTTP redirects to HTTPS |
| `/api/papers`, `/api/papers/{id}`, `/docs` | Yes | Read-only API and its documentation |
| `/health/live`, `/health/ready` | Yes | Used by the uptime check; not rate limited |
| `/metrics` | No, 404 at the proxy | Read on the server: `curl http://127.0.0.1:8001/metrics` |
| PostgreSQL | No | No published port; only the Compose network reaches it |
| SSH | Tailscale only | Remove any public port 22 rule once Tailscale works |

Pages and the API allow 120 requests per client per minute (`RATE_LIMIT_PER_MINUTE`).
Requests over the limit get `429` with a `Retry-After` header. The web server handles at
most 64 requests at once and answers `503` beyond that rather than queueing.

## 1. Create the server

The stack needs an x86-64 Linux server with about 2 GB of memory and a fixed public IPv4
address. On AWS Lightsail: create an Ubuntu LTS instance, attach a static IP, and in its
networking tab allow TCP 80 and 443 from anywhere. Keep TCP 22 restricted to your own
address until Tailscale is working, then remove it.

Perform these steps **on the server**, using the account that will run Athena:

1. Install Docker Engine with the Compose plugin by following
   [Docker's Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/), then
   allow the account to use it with `sudo usermod -aG docker "$USER"` and sign in again.
   Membership in the `docker` group is equivalent to root on this server; use a dedicated
   account. Confirm that `docker info` and `docker compose version` work.
2. Install Tailscale by following its
   [Linux instructions](https://tailscale.com/docs/install/linux) and join the server to
   your tailnet with the `tag:athena-server` tag.
3. Create the server directory and three separate passwords:

   ```sh
   mkdir -p ~/athena/logs
   chmod 700 ~/athena
   for name in POSTGRES_PASSWORD ATHENA_WEB_DB_PASSWORD ATHENA_INGEST_DB_PASSWORD; do
     echo "$name=$(openssl rand -hex 32)"
   done
   ```

4. Create `~/athena/.env` from [deploy/.env.example](../deploy/.env.example). Paste the
   three generated lines over the placeholders, keeping each value exactly 64 hex
   characters. Set `ATHENA_DOMAIN`, your contact email, and optionally an OpenAlex API
   key, then run `chmod 600 ~/athena/.env`. Never commit this file. Do not change
   `POSTGRES_PASSWORD` after the database has been initialized without also changing the
   owner role's password in PostgreSQL. The other two passwords are reapplied on every
   deployment, so changing them in `.env` and redeploying rotates them.

The application binds to `127.0.0.1:8001` on the server for on-host checks. Public
traffic reaches it only through the Caddy container on ports 80 and 443.

## 2. Point DNS at the server

In the Route 53 hosted zone for `isaiahmcnealy.com`, add one `A` record for
`athena.isaiahmcnealy.com` with the server's static IP. Leave every other record as it is.
Confirm it resolves before the first deployment:

```sh
dig +short athena.isaiahmcnealy.com
```

Caddy requests the certificate when it first starts, which requires the name to resolve
to this server and ports 80 and 443 to be reachable. If either is missing, the site has
no valid certificate until Caddy's next retry succeeds.

## 3. Configure SSH and Tailscale

On your development machine, create a dedicated automation key:

```sh
ssh-keygen -t ed25519 -f ~/.ssh/athena_deploy -C athena-deploy
```

Leave its passphrase empty so this dedicated key can run unattended. Add the **public**
key (`athena_deploy.pub`) to the deployment account's `~/.ssh/authorized_keys` on the
server; use mode 700 for `~/.ssh` and 600 for `authorized_keys`. Keep its credentials
separate from your personal SSH keys.

In Tailscale, define `tag:athena-ci` and `tag:athena-server`, tag the server as
`tag:athena-server`, and permit the CI tag to reach the server tag on TCP port 22. Create
an OAuth client authorized to create tagged devices with `tag:athena-ci`. Merge the needed
rule into your existing tailnet policy; broader existing rules may already grant more access.
Follow the [official GitHub Action setup](https://tailscale.com/docs/integrations/github/github-action)
for OAuth scopes and tag ownership. CI nodes are ephemeral.

Verify an SSH connection from your own Tailscale-connected computer (replace `ACCOUNT`
and `SERVER_HOST` with the server account and its Tailscale IPv4 or full MagicDNS hostname):

```sh
ssh -i ~/.ssh/athena_deploy ACCOUNT@SERVER_HOST
```

Verify the host key fingerprint against the server's own output:

```sh
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

For GitHub's known-hosts secret, use a line containing the **exact** `SERVER_HOST`, followed
by the server's public host key, for example `SERVER_HOST ssh-ed25519 AAAA...`. Get that
public key from `/etc/ssh/ssh_host_ed25519_key.pub` on the server. Do not use a private
host key. The pipeline requires the pinned key; it never blindly trusts `ssh-keyscan` output.

## 4. Allow the server to pull images

The workflow publishes `ghcr.io/isaiahmcnealy/athena:<commit-sha>`. It records and deploys
the image's immutable SHA-256 digest. GitHub Actions uses its built-in token to publish.

For a **private** GHCR package, log Docker in on the server as the deployment account with
a GitHub personal access token (classic) that has `read:packages` and access to the package:

```sh
docker login ghcr.io --username YOUR_GITHUB_USERNAME
```

Paste the token at the password prompt. A public package can be pulled without login.
After the first publish, verify a pull from a **noninteractive SSH session** before
enabling deployment. See [GitHub's GHCR authentication documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## 5. Configure GitHub

In the repository's **Settings → Environments**, create `production` and, where your GitHub
plan supports it, limit deployment branches to `master`.

Add these **environment secrets**:

| Secret | Value |
| --- | --- |
| `TS_OAUTH_CLIENT_ID` | Tailscale OAuth client ID |
| `TS_OAUTH_SECRET` | Tailscale OAuth client secret |
| `DEPLOY_SSH_KEY` | Complete contents of the dedicated `athena_deploy` private key |
| `DEPLOY_KNOWN_HOSTS` | Verified host-key line matching `DEPLOY_HOST` exactly |

Add these **environment variables**:

| Variable | Value |
| --- | --- |
| `DEPLOY_HOST` | Tailscale IPv4 or full MagicDNS hostname; no URL scheme or port |
| `DEPLOY_USER` | Deployment account's short username |

Under **Settings → Secrets and variables → Actions → Variables**, add these **repository
variables**. They must be repository variables because job conditions are evaluated before
an environment is loaded, and the uptime workflow does not use the environment.

| Variable | Value |
| --- | --- |
| `DEPLOY_ENABLED` | `false` initially; change to `true` when the server is ready |
| `PUBLIC_URL` | `https://athena.isaiahmcnealy.com`, with no trailing slash |

Setting `PUBLIC_URL` also turns on the [uptime workflow](../.github/workflows/uptime.yml),
which checks readiness and that the catalog is not empty every 15 minutes and emails the
repository owner on failure. GitHub can delay scheduled runs and pauses them after 60 days
without repository activity, so add a dedicated external monitor when you can.

Allow Actions to publish packages. If a package already exists, grant this repository
Actions access to it. Protect `master` with pull requests and required checks when available.
Turn on secret scanning and Dependabot alerts in **Settings → Code security**;
[dependabot.yml](../.github/dependabot.yml) proposes weekly updates for Python packages,
container images, and pinned actions.

## 6. Release

Push tested changes to `develop`, open a pull request from `develop` to `master`, and merge
it. Use a regular merge so shared history stays connected. Continue local development on
`develop`. Never place development databases or `.env` files in Git.

No deployment occurs while `DEPLOY_ENABLED` is not `true`; tests and image publishing still
run. Once setup is complete, set it to `true` and rerun **Actions → Release** on `master`
(or push the next release). If the Run workflow button is unavailable, ensure the workflow
also exists on the repository's default branch.

Each deployment pulls the app image, starts or checks PostgreSQL, writes a logical backup,
runs migrations, reapplies the database roles, replaces the web container, checks readiness
and the catalog endpoint, starts the HTTPS proxy, and finally checks the public URL with
certificate validation. Deployments serialize in GitHub and on the server. PostgreSQL is
not pulled or upgraded on each release. Plan and test database version upgrades separately.

## 7. Populate and inspect the server

After the first successful deployment, on the server:

```sh
bash ~/athena/current/manage.sh ps
bash ~/athena/current/manage.sh logs --tail=100 web
bash ~/athena/current/manage.sh run --rm --no-deps ingest seed --per-query 250
bash ~/athena/current/manage.sh run --rm --no-deps ingest stats
curl --fail http://127.0.0.1:8001/health/ready
```

Imports are explicit, not a side effect of every deployment. The full seed takes about ten
minutes. Without an OpenAlex API key it uses most of the provider's daily allowance, so run
it once and let the scheduled refresh keep the catalog current.

Then check from a device outside the server's network:

```sh
curl --fail https://athena.isaiahmcnealy.com/health/ready
curl --silent --output /dev/null --write-out '%{http_code}\n' https://athena.isaiahmcnealy.com/metrics   # 404
curl --silent --output /dev/null --write-out '%{http_code}\n' http://athena.isaiahmcnealy.com/           # 308
```

## 8. Schedule the refresh and the backup

Add both jobs to the deployment account's crontab with `crontab -e`. Times are in the
server's time zone; any quiet hour works, with the backup after the refresh.

```cron
17 6 * * * bash "$HOME/athena/current/refresh.sh" >> "$HOME/athena/logs/refresh.log" 2>&1
47 7 * * * bash "$HOME/athena/current/backup.sh" >> "$HOME/athena/logs/backup.log" 2>&1
```

- **Refresh** requests the newest `REFRESH_PER_QUERY` records (default 50) for each of the
  42 seed queries. Replayed records update in place. It skips a run while a deployment
  holds its lock, and a failed provider request stops that run; the next one starts over.
- **Backup** writes `~/athena/backups/scheduled-<time>.dump` and deletes scheduled dumps
  older than `BACKUP_RETENTION_DAYS` (default 14). Pre-release dumps written by deployments
  are never deleted automatically.
- **Off-host copy:** set `BACKUP_S3_URI` (for example `s3://my-bucket/athena`) to also copy
  each scheduled dump to S3. This needs the AWS CLI on the server and credentials for an
  IAM user that may only write to that bucket prefix. Make the bucket private, enable
  default encryption, and add a lifecycle rule for retention. Without this, a lost disk
  loses every backup; the catalog can still be rebuilt with `athena seed`.

Check the logs after the first scheduled runs, and watch disk use with `df -h` and
`docker system df`.

## Failure and recovery

- **Pull, backup, migration, or role failure:** the job stops before replacing the web
  container. A failed migration may still need investigation. Use backward-compatible
  migrations while the previous app is serving. Inspect the job output and database before
  retrying.
- **New web container or proxy fails:** GitHub reports failure. The new container may
  already be running or unhealthy; `current` still records the last successful release,
  not necessarily the currently running container. There is no automatic database
  downgrade or rollback.
- **Certificate problems:** check `bash ~/athena/current/manage.sh logs --tail=100 caddy`.
  The usual causes are a DNS record that does not point at the server or a closed port 80
  or 443. Do not delete the `caddy_data` volume to "retry"; repeated reissue can hit the
  certificate authority's rate limits.
- **App rollback:** after confirming the current schema supports the previous app, inspect
  `~/athena/previous/image`, then run `bash ~/athena/previous/manage.sh up -d --no-deps --wait web`.
  For a failed rollout, use `~/athena/current/manage.sh` to restore the last successful app
  instead. These commands retain the database and do not run migrations. Record the recovery;
  the history pointers are only updated by a successful deployment.
- **Database recovery:** backups are in `~/athena/backups/*.dump`. Restore into a separate
  database first, confirm its contents, and only then plan any production replacement:

  ```sh
  bash ~/athena/current/manage.sh exec db createdb -U athena athena_restore
  bash ~/athena/current/manage.sh exec -T db pg_restore -U athena -d athena_restore --no-owner \
    < ~/athena/backups/NAME.dump
  ```

  Dumps include grants for `athena_web` and `athena_ingest`. On a new server those roles do
  not exist until a deployment has run, so restore there with `--no-acl` as well and let
  the next deployment reapply the roles. Automatic restores would risk discarding new data.
- **A visitor reports being blocked:** `429` responses mean the per-client limit was
  reached. The limit is held in memory and clears when the web container restarts. Raise
  `RATE_LIMIT_PER_MINUTE` in `.env` and redeploy if it is too strict.
- **Stale lock:** an abrupt process kill may leave `~/athena/.deploy-lock` or
  `~/athena/.refresh-lock`. Confirm no release, migration, or import is still running before
  removing the empty directory with `rmdir` and retrying.
- **Disk growth:** backups and release directories are retained. Monitor free space and
  define retention for pre-release dumps after verifying a restore.

Never run `down --volumes` on the server's release project unless you intend to destroy its
catalog and certificates. Use the root Compose file for development; server commands use
`manage.sh` to select the correct project, image, and environment.

The pipeline has been exercised locally and in tests, not yet on a real server. It still
needs a first deployment, a reboot recovery check, and a recorded restore drill on that
host before availability can be claimed.
