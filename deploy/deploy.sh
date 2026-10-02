#!/usr/bin/env bash
set -euo pipefail
umask 077

# Noninteractive SSH sessions may omit the Docker CLI from PATH.
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin"
root="${ATHENA_DEPLOY_ROOT:-$HOME/athena}"
release_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
image="${1:-}"
if [[ ! "$image" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]; then
  echo 'Usage: bash deploy.sh ghcr.io/owner/image@sha256:<64-character digest>' >&2
  exit 1
fi
if [[ ! -f "$root/.env" ]]; then
  echo "Create $root/.env from deploy/.env.example before deploying." >&2
  exit 1
fi
# Passwords are interpolated into database URLs; hex needs no URL escaping.
for name in POSTGRES_PASSWORD ATHENA_WEB_DB_PASSWORD ATHENA_INGEST_DB_PASSWORD; do
  if ! grep -Eq "^$name=[a-fA-F0-9]{64}\$" "$root/.env"; then
    echo "$name must be a 64-character hex value (openssl rand -hex 32)." >&2
    exit 1
  fi
done
if ! grep -Eq '^ATHENA_DOMAIN=[a-z0-9]([a-z0-9.-]*[a-z0-9])?$' "$root/.env"; then
  echo 'ATHENA_DOMAIN must be the public hostname, for example athena.example.com.' >&2
  exit 1
fi
for file in compose.yaml manage.sh roles.sql Caddyfile; do
  if [[ ! -f "$release_dir/$file" ]]; then
    echo "The release directory is missing $file." >&2
    exit 1
  fi
done
if ! mkdir "$root/.deploy-lock" 2>/dev/null; then
  echo "Another deployment holds $root/.deploy-lock; see the recovery guide." >&2
  exit 1
fi
trap 'rmdir "$root/.deploy-lock"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export ATHENA_IMAGE="$image"
compose=(docker compose --env-file "$root/.env" -p athena-release -f "$release_dir/compose.yaml")

docker info > /dev/null
# Pull the application before making changes. Do not upgrade PostgreSQL on each release.
"${compose[@]}" pull web migrate
"${compose[@]}" up -d --wait --wait-timeout 120 db

mkdir -p "$root/backups"
backup="$root/backups/$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$release_dir").dump"
"${compose[@]}" exec -T db pg_dump -U athena -d athena -Fc > "$backup.partial"
mv "$backup.partial" "$backup"
echo "Database backup saved: $backup"

# A failure stops here, before the web container is replaced.
"${compose[@]}" run --rm --no-deps migrate
# Limited roles for the web app and importer; grants follow the migrated schema.
"${compose[@]}" exec -T db psql -U athena -d athena -v ON_ERROR_STOP=1 -q -f - \
  < "$release_dir/roles.sql"
"${compose[@]}" up -d --no-deps --wait --wait-timeout 120 web
# Reads the catalog as the web role, so it also proves that role's grants.
"${compose[@]}" exec -T web /app/.venv/bin/python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/papers', timeout=10)"
# The HTTPS entry point starts only behind an app that answers.
"${compose[@]}" up -d --no-deps --wait --wait-timeout 120 caddy

# These pointers record successful deployments only. Failed rollouts require inspection.
printf '%s\n' "$image" > "$release_dir/image"
if [[ -L "$root/current" ]]; then
  ln -sfn "$(readlink "$root/current")" "$root/previous"
fi
ln -sfn "$release_dir" "$root/current"
echo "Deployed $image successfully."
