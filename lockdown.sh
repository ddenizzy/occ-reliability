#!/bin/sh
# From the Mac, after Tailscale works: close SSH to the internet so the server is reachable only over Tailscale.
# Connecting through the Tailscale name first proves that path works, so this can't lock you out.
# Usage: ./lockdown.sh occ-logger
set -e
[ -n "$1" ] || { echo "Usage: ./lockdown.sh occ-logger"; exit 1; }
ssh -o StrictHostKeyChecking=accept-new root@"$1" 'tailscale status >/dev/null &&
  ufw allow in on tailscale0 >/dev/null && ufw delete allow OpenSSH >/dev/null && ufw status verbose'
echo "Locked down. From now on use: ./fetch.sh $1"
