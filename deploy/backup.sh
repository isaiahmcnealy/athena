#!/usr/bin/env bash
# Scheduled logical backup of the release database. Run from cron through
# ~/athena/current/backup.sh so it uses the last successful release.
set -euo pipefail
umask 077

export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin"
root="${ATHENA_DEPLOY_ROOT:-$HOME/athena}"
release_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

setting() {
  { grep -E "^$1=" "$root/.env" || true; } | tail -n 1 | cut -d= -f2-
}
retention="$(setting BACKUP_RETENTION_DAYS)"
retention="${retention:-14}"
destination="$(setting BACKUP_S3_URI)"
if [[ ! "$retention" =~ ^[1-9][0-9]{0,3}$ ]]; then
  echo 'BACKUP_RETENTION_DAYS must be a whole number of days from 1 to 9999.' >&2
  exit 1
fi
if [[ -n "$destination" && ! "$destination" =~ ^s3://[a-z0-9][a-z0-9.-]+(/[A-Za-z0-9._/-]*)?$ ]]; then
  echo 'BACKUP_S3_URI must look like s3://bucket/optional/prefix.' >&2
  exit 1
fi

mkdir -p "$root/backups"
backup="$root/backups/scheduled-$(date -u +%Y%m%dT%H%M%SZ).dump"
trap 'rm -f "$backup.partial"' EXIT
bash "$release_dir/manage.sh" exec -T db pg_dump -U athena -d athena -Fc > "$backup.partial"
# An empty dump is a failed backup, not a small one.
test -s "$backup.partial"
mv "$backup.partial" "$backup"
echo "Database backup saved: $backup"

if [[ -n "$destination" ]]; then
  # Encryption at rest and retention of remote copies are properties of the bucket.
  aws s3 cp --only-show-errors "$backup" "${destination%/}/$(basename "$backup")"
  echo "Database backup copied to ${destination%/}/"
fi

# Prune only after this run succeeded, so a failing job never deletes the last good copies.
find "$root/backups" -name 'scheduled-*.dump' -mtime +"$retention" -delete
