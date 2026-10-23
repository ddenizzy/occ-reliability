#!/bin/sh
# One-time setup on a fresh Ubuntu server (run as root, from the folder this repo was copied into).
# Installs the logger as a service that starts on boot and restarts itself, plus a nightly backup.
set -e
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3 sqlite3 unattended-upgrades ufw
id occ >/dev/null 2>&1 || useradd --system --home /opt/occ-reliability --shell /usr/sbin/nologin occ
mkdir -p /opt/occ-reliability/data
cp logger.py /opt/occ-reliability/
chown -R occ:occ /opt/occ-reliability
timedatectl set-timezone America/New_York        # the buses run on Binghamton time
cp deploy/occ-logger.service deploy/occ-backup.service deploy/occ-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now occ-logger.service occ-backup.timer
# SSH with keys only, never passwords
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' > /etc/ssh/sshd_config.d/10-occ.conf
systemctl reload ssh
ufw allow OpenSSH >/dev/null && ufw --force enable >/dev/null     # only SSH is open (lockdown.sh closes it later)
# Tailscale: the private network between the Mac and this server. First run prints a login link to open.
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
tailscale status >/dev/null 2>&1 || tailscale up --hostname=occ-logger
sleep 5
systemctl --no-pager status occ-logger.service | head -5
echo "Done. Check data with:  sqlite3 /opt/occ-reliability/data/occ.sqlite 'select count(*) from positions'"
