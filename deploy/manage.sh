#!/usr/bin/env bash
set -euo pipefail
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin"
root="${ATHENA_DEPLOY_ROOT:-$HOME/athena}"
release_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# Run through ~/athena/current/manage.sh to use the last successful release.
ATHENA_IMAGE="$(cat "$release_dir/image")"
export ATHENA_IMAGE
exec docker compose --env-file "$root/.env" -p athena-release -f "$release_dir/compose.yaml" "$@"
