#!/bin/sh
# From the Mac: copy the project to the server and set it up.   Usage: ./deploy.sh <server IP>
set -e
[ -n "$1" ] || { echo "Usage: ./deploy.sh <server IP>"; exit 1; }
ssh -o StrictHostKeyChecking=accept-new root@"$1" 'mkdir -p /root/occ-reliability'
scp -q -r logger.py setup.sh deploy root@"$1":/root/occ-reliability/
ssh root@"$1" 'cd /root/occ-reliability && sh setup.sh'
