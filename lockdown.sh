#!/bin/sh
# From the Mac, after Tailscale works: close SSH to the internet so the server is reachable only over Tailscale.
# Connecting through the Tailscale name first proves that path works, so this can't lock you out.
# Usage: ./lockdown.sh occ-logger
set -e
[ -n "$1" ] || { echo "Usage: ./lockdown.sh occ-logger"; exit 1; }
U="${OCC_USER:-azureuser}"
ssh -o StrictHostKeyChecking=accept-new "$U@$1" 'sudo tailscale status >/dev/null &&
  sudo ufw allow in on tailscale0 >/dev/null && sudo ufw delete allow OpenSSH >/dev/null && sudo ufw status verbose'
echo "Locked down. From now on use: ./fetch.sh $1"
