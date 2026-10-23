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
ufw allow OpenSSH >/dev/null && ufw --force enable >/dev/null     # only SSH is open
sleep 5
systemctl --no-pager status occ-logger.service | head -5
echo "Done. Check data with:  sqlite3 /opt/occ-reliability/data/occ.sqlite 'select count(*) from positions'"
