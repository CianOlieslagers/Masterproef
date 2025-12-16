#!/usr/bin/env bash
set -euo pipefail

# ===========================================
# logic_synth_mt.sh
# Mockturtle rewrite + LUT mapping
# Schrijft:
#   - Aig/<design>.postopt.aig
#   - Blif/<design>.mapped.blif
# ===========================================

MPROOT="${MPROOT:-$HOME/Masterproef/multisynthesis}"
OUT_DIR="${OUT_DIR:-$MPROOT/logicSynthesis/results}"
LOG_DIR="${LOG_DIR:-$MPROOT/logicSynthesis/logs}"

K="${K:-6}"   # default LUT size

# NIEUWE binary: mt_logic_synth (niet mt_lut_cones!)
MT_SYN_BIN="${MT_SYN_BIN:-$MPROOT/logicSynthesis/tools/mockturtle/build/mt_logic_synth}"

IN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lut)      K="$2"; shift 2;;
    --out-dir)  OUT_DIR="$(realpath -m "$2")"; shift 2;;
    --log-dir)  LOG_DIR="$(realpath -m "$2")"; shift 2;;
    -h|--help)
      echo "Gebruik: logic_synth_mt.sh <input.aig> [--lut K] [--out-dir DIR] [--log-dir DIR]"
      exit 0;;
    *)
      if [[ -z "$IN" ]]; then
        IN="$(realpath -m "$1")"
        shift
      else
        echo "Onbekend argument: $1"
        exit 1
      fi;;
  esac
done

[[ -f "$IN" ]] || { echo "Fout: inputbestand bestaat niet: $IN"; exit 1; }
[[ -x "$MT_SYN_BIN" ]] || { echo "Fout: Mockturtle binary niet uitvoerbaar: $MT_SYN_BIN"; exit 1; }

mkdir -p "$OUT_DIR/Aig" "$OUT_DIR/Blif" "$LOG_DIR"

base="$(basename "$IN")"
design="${base%.*}"

LOG_FILE="$LOG_DIR/${design}.mt.log"

echo "[Mockturtle] Rewrite + LUT mapping (K=$K)"
echo "Log: $LOG_FILE"

"$MT_SYN_BIN" \
  --aig "$IN" \
  --lut "$K" \
  --out-aig  "$OUT_DIR/Aig/${design}.postopt.aig" 
  > "$LOG_FILE" 2>&1

echo "OK: ${design}.postopt.aig"
echo "OK: ${design}.mapped.blif"
