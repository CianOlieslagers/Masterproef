#!/bin/bash
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Gebruik: ./run_eco_batch.sh <config.conf>"
  exit 1
fi

python3 "$(dirname "$0")/run_eco_batch.py" "$1"
