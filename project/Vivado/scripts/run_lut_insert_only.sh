#!/bin/bash
set -euo pipefail

# =========================================================
# Alleen RapidWright LUT-insert test
# Geen Vivado synth/place/route
# Geen diagnose achteraf
# Alleen:
#   1) Java compileren
#   2) InsertBufferECO runnen op bestaande baseline-DCP
# =========================================================

if [ -z "${1:-}" ]; then
    echo "Fout: Geen configuratiebestand opgegeven."
    echo "Gebruik: ./run_lut_insert_only.sh <config_file.conf> [baseline_dcp]"
    exit 1
fi

CONFIG_FILE="$1"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Fout: Configuratiebestand '$CONFIG_FILE' niet gevonden."
    exit 1
fi

source "$CONFIG_FILE"

# Optionele override via command line
if [ -n "${2:-}" ]; then
    ORIGINAL_DCP="$2"
else
    # STANDAARD: gebruik routed baseline als vaste start
    ORIGINAL_DCP="$PROJ_DIR/baseline_impl/checkpoints/post_route_timingexp.dcp"
fi

if [ ! -f "$ORIGINAL_DCP" ]; then
    echo "Fout: baseline DCP niet gevonden:"
    echo "  $ORIGINAL_DCP"
    exit 1
fi

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
RESULT_DIR="$PROJ_DIR/results/run_lut_insert_only/$TIMESTAMP"
LOG_DIR="$RESULT_DIR/logs"
DCP_DIR="$RESULT_DIR/dcp"

mkdir -p "$LOG_DIR" "$DCP_DIR"

ECO_DCP="$DCP_DIR/test_eco_output.dcp"

echo "========================================"
echo "      RAPIDWRIGHT LUT INSERT TEST       "
echo "========================================"
echo "Baseline DCP : $ORIGINAL_DCP"
echo "Target Net   : $TARGET_NET"
echo "Target Sink  : $TARGET_LUT_B"
echo "Target Slice : $TARGET_SLICE"
echo "Output DCP   : $ECO_DCP"
echo "========================================"

cd "$PROJ_DIR/Readwright/scripts"

echo
echo "[1/2] Java compileren..."
javac -cp "$RAPIDWRIGHT_JAR:$PROJ_DIR/Readwright/scripts" InsertBufferECO.java

echo
echo "[2/2] InsertBufferECO uitvoeren..."
java -cp "$RAPIDWRIGHT_JAR:$PROJ_DIR/Readwright/scripts" InsertBufferECO \
  "$ORIGINAL_DCP" \
  "$ECO_DCP" \
  "$TARGET_LUT_B" \
  "$TARGET_NET" \
  "$TARGET_SLICE" | tee "$LOG_DIR/rapidwright_insert.log"

echo
if [ -f "$ECO_DCP" ]; then
    echo "[SUCCES] ECO DCP aangemaakt:"
    echo "  $ECO_DCP"
else
    echo "[FOUT] ECO DCP werd niet aangemaakt."
    echo "Bekijk log:"
    echo "  $LOG_DIR/rapidwright_insert.log"
    exit 1
fi

echo
echo "Resultaten:"
echo "  $RESULT_DIR"
