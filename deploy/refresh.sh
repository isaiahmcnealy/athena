#!/usr/bin/env bash
# Scheduled catalog refresh: the newest records for every seed topic. Run from cron
# through ~/athena/current/refresh.sh so it uses the last successful release.
set -euo pipefail

export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin"
root="${ATHENA_DEPLOY_ROOT:-$HOME/athena}"
release_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

per_query="$({ grep -E '^REFRESH_PER_QUERY=' "$root/.env" || true; } | tail -n 1 | cut -d= -f2-)"
per_query="${per_query:-50}"
if [[ ! "$per_query" =~ ^[1-9][0-9]{0,3}$ ]] || (( per_query > 1000 )); then
  echo 'REFRESH_PER_QUERY must be a whole number from 1 to 1000.' >&2
  exit 1
fi

# A deployment may be migrating the schema or replacing containers.
if [[ -d "$root/.deploy-lock" ]]; then
  echo 'A deployment is in progress; skipping this refresh.' >&2
  exit 0
fi
if ! mkdir "$root/.refresh-lock" 2>/dev/null; then
  echo "Another refresh holds $root/.refresh-lock. If none is running, remove it with rmdir." >&2
  exit 1
fi
trap 'rmdir "$root/.refresh-lock"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Imports are idempotent. A failed query stops the run; the next scheduled run starts over.
# -T: cron provides no terminal.
bash "$release_dir/manage.sh" run --rm -T --no-deps ingest seed --per-query "$per_query"
