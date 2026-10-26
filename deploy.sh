#!/bin/sh
# From the Mac: copy the project to the server and set it up.   Usage: ./deploy.sh <server IP or occ-logger>
# Logs in as azureuser (Azure's default; set OCC_USER to change) and uses sudo for the setup.
set -e
[ -n "$1" ] || { echo "Usage: ./deploy.sh <server IP or occ-logger>"; exit 1; }
U="${OCC_USER:-azureuser}"
ssh -o StrictHostKeyChecking=accept-new "$U@$1" 'mkdir -p occ-reliability'
scp -q -r logger.py setup.sh deploy "$U@$1":occ-reliability/
ssh "$U@$1" 'cd occ-reliability && sudo sh setup.sh'
