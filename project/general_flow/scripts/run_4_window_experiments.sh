#!/usr/bin/env bash
set -u

SCRIPT="/home/cian/Masterproef/project/general_flow/scripts/run_general_eco_flow.py"
CFG_DIR="/home/cian/Masterproef/project/general_flow/config_files/"
LOG_DIR="/home/cian/Masterproef/project/results/general_flow_runs/batch_logs"

mkdir -p "$LOG_DIR"

CONFIGS=(
  "config_5in_12_false.yaml"
  "config_5in14_false.yaml"
  "config_6in12_false.yaml"
  "config_6in15_false.yaml"
)

for cfg in "${CONFIGS[@]}"; do
  echo "============================================================"
  echo "RUNNING $cfg"
  echo "============================================================"

  python3 "$SCRIPT" "$CFG_DIR/$cfg" --until phase7 \
    2>&1 | tee "$LOG_DIR/${cfg%.yaml}.log"

  echo "DONE $cfg"
done

echo "ALL CONFIGS DONE"
