#!/bin/sh
# From the Mac: download a copy of the collected data for analysis.   Usage: ./fetch.sh <server IP>
set -e
[ -n "$1" ] || { echo "Usage: ./fetch.sh <server IP>"; exit 1; }
ssh root@"$1" 'sqlite3 /opt/occ-reliability/data/occ.sqlite ".backup /tmp/occ-copy.sqlite"'
scp -q root@"$1":/tmp/occ-copy.sqlite data/occ.sqlite
echo "Saved to data/occ.sqlite"
