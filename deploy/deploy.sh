#!/usr/bin/env bash
set -euo pipefail
umask 077

# Noninteractive macOS SSH sessions may omit the Docker Desktop CLI from PATH.
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
# The password is interpolated into a database URL; hex needs no URL escaping.
if ! grep -Eq '^POSTGRES_PASSWORD=[a-fA-F0-9]{64}$' "$root/.env"; then
  echo 'POSTGRES_PASSWORD must be a 64-character hex value (openssl rand -hex 32).' >&2
  exit 1
fi
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
"${compose[@]}" up -d --no-deps --wait --wait-timeout 120 web
"${compose[@]}" exec -T web /app/.venv/bin/python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/papers', timeout=10)"

# These pointers record successful deployments only. Failed rollouts require inspection.
printf '%s\n' "$image" > "$release_dir/image"
if [[ -L "$root/current" ]]; then
  ln -sfn "$(readlink "$root/current")" "$root/previous"
fi
ln -sfn "$release_dir" "$root/current"
echo "Deployed $image successfully."
