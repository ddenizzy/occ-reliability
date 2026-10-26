#!/bin/sh
# From the Mac: download a copy of the collected data for analysis.   Usage: ./fetch.sh <server IP or occ-logger>
set -e
[ -n "$1" ] || { echo "Usage: ./fetch.sh <server IP or occ-logger>"; exit 1; }
U="${OCC_USER:-azureuser}"
ssh "$U@$1" 'sudo sqlite3 /opt/occ-reliability/data/occ.sqlite ".backup /tmp/occ-copy.sqlite" && sudo chmod 644 /tmp/occ-copy.sqlite'
scp -q "$U@$1":/tmp/occ-copy.sqlite data/occ.sqlite
echo "Saved to data/occ.sqlite"
