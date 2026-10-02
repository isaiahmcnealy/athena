#!/usr/bin/env bash
# One-time setup for a new Athena server running Ubuntu LTS. Safe to rerun.
# Run as root: paste it as the instance's launch script, or use `sudo bash bootstrap.sh`.
#
# It installs Docker Engine with the Compose plugin and Tailscale from their own apt
# repositories, lets the deployment account use Docker, and creates ~/athena with a
# settings file holding freshly generated database passwords.
# It does not join Tailscale, open firewall ports, or create DNS records.
set -euo pipefail

account="${ATHENA_ACCOUNT:-ubuntu}"
domain="${ATHENA_DOMAIN:-athena.isaiahmcnealy.com}"

if [[ $EUID -ne 0 ]]; then
  echo 'Run this script as root.' >&2
  exit 1
fi
if ! id "$account" > /dev/null 2>&1; then
  echo "The deployment account '$account' does not exist. Set ATHENA_ACCOUNT." >&2
  exit 1
fi
if [[ ! "$domain" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]; then
  echo 'ATHENA_DOMAIN must be the public hostname, for example athena.example.com.' >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
. /etc/os-release
codename="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
apt-get update -q
apt-get install -yq ca-certificates curl openssl

if ! command -v docker > /dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]" \
    "https://download.docker.com/linux/ubuntu $codename stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
# Membership in the docker group is equivalent to root on this server.
usermod -aG docker "$account"

if ! command -v tailscale > /dev/null; then
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/$codename.noarmor.gpg" \
    -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/$codename.tailscale-keyring.list" \
    -o /etc/apt/sources.list.d/tailscale.list
  apt-get update -q
  apt-get install -yq tailscale
fi

home="$(getent passwd "$account" | cut -d: -f6)"
install -d -m 700 -o "$account" -g "$account" "$home/athena" "$home/athena/logs"
settings="$home/athena/.env"
if [[ -f "$settings" ]]; then
  # Regenerating would lock the app out of an initialized database.
  echo "Keeping the existing $settings."
else
  umask 077
  cat > "$settings" << SETTINGS
POSTGRES_PASSWORD=$(openssl rand -hex 32)
ATHENA_WEB_DB_PASSWORD=$(openssl rand -hex 32)
ATHENA_INGEST_DB_PASSWORD=$(openssl rand -hex 32)
ATHENA_DOMAIN=$domain
ATHENA_PORT=8001
RATE_LIMIT_PER_MINUTE=120
OPENALEX_API_KEY=
CONTACT_EMAIL=
REFRESH_PER_QUERY=50
BACKUP_RETENTION_DAYS=14
BACKUP_S3_URI=
SETTINGS
  chown "$account:$account" "$settings"
  echo "Created $settings with generated passwords."
fi

cat << NEXT

Athena server setup finished for account '$account' and hostname '$domain'.
Next, on this server:
  1. sudo tailscale up --advertise-tags=tag:athena-server
  2. Sign out and back in so '$account' can use Docker, then check: docker compose version
Then continue with the deployment guide: DNS record, deploy key, and GitHub settings.
NEXT
