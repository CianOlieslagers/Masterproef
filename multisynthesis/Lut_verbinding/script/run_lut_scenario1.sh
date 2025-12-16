#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Gebruik:
#   ./run_lut_scenario1.sh \
#       /home/cian/Masterproef/multisynthesis/results/example_big_300
#
# Dit script doet automatisch:
#   1) build_lut_boolean_expressions.py
#   2) build_lut_connection_aig_json.py
#   3) filter_scenario1_pitstops.py
#
# Output:
#   ~/Masterproef/multisynthesis/Lut_verbinding/result/<design>/:
#     - <design>.lutBooleanExp.json
#     - <design>.lut_connections_full.json
#     - <design>.lut_connections_scen1.json
# ============================================================

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <RESULT_DIR (bv. .../results/example_big_300)>"
  exit 1
fi

RESULT_DIR="$1"

if [[ ! -d "$RESULT_DIR" ]]; then
  echo "Error: RESULT_DIR bestaat niet: $RESULT_DIR"
  exit 1
fi

# Designnaam = basename van de results-map, bv. "example_big_300"
DESIGN="$(basename "$RESULT_DIR")"

# Pad naar deze script-map (Lut_verbinding/script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Result-root voor alle output van deze stap
RESULT_ROOT="$SCRIPT_DIR/../result/$DESIGN"
mkdir -p "$RESULT_ROOT"

echo "=============================================="
echo " Design      : $DESIGN"
echo " Result dir  : $RESULT_DIR"
echo " Output dir  : $RESULT_ROOT"
echo "=============================================="

# ---------- 1) Paden naar inputbestanden ----------

LUT_CONES="$RESULT_DIR/JsonMapping/${DESIGN}.lut_cones.json"
MID_LUTS="$RESULT_DIR/PlaceAndRoute/05_custom_outputs/${DESIGN}.mid_luts.json"
MANHATTAN="$RESULT_DIR/PlaceAndRoute/05_custom_outputs/${DESIGN}.manhattan.json"

if [[ ! -f "$LUT_CONES" ]]; then
  echo "Error: LUT-cones JSON niet gevonden: $LUT_CONES"
  exit 1
fi
if [[ ! -f "$MID_LUTS" ]]; then
  echo "Error: mid_luts JSON niet gevonden: $MID_LUTS"
  exit 1
fi
if [[ ! -f "$MANHATTAN" ]]; then
  echo "Error: manhattan JSON niet gevonden: $MANHATTAN"
  exit 1
fi

# ---------- 2) Paden naar outputbestanden ----------

BOOL_JSON="$RESULT_ROOT/${DESIGN}.lutBooleanExp.json"
CONN_FULL="$RESULT_ROOT/${DESIGN}.lut_connections_full.json"
CONN_SCEN1="$RESULT_ROOT/${DESIGN}.lut_connections_scen1.json"

# ---------- 3) Scripts ----------

BUILD_BOOL_PY="$SCRIPT_DIR/build_lut_boolean_expressions.py"
BUILD_CONN_PY="$SCRIPT_DIR/build_lut_connection_aig_json.py"
FILTER_SCEN1_PY="$SCRIPT_DIR/filter_scenario1_pitstops.py"

for f in "$BUILD_BOOL_PY" "$BUILD_CONN_PY" "$FILTER_SCEN1_PY"; do
  if [[ ! -f "$f" ]]; then
    echo "Error: script niet gevonden: $f"
    exit 1
  fi
done

# ---------- Stap 1: LUT-boolean expressies ----------

echo "[1/3] Bouw LUT-boolean expressies → $BOOL_JSON"
python3 "$BUILD_BOOL_PY" \
  --lut-cones "$LUT_CONES" \
  --out "$BOOL_JSON"

echo "    [OK] $BOOL_JSON geschreven"

# ---------- Stap 2: Verbindingen + AIG-info + func_hex ----------

echo "[2/3] Bouw LUT-verbindingen met AIG-info + expressies → $CONN_FULL"
python3 "$BUILD_CONN_PY" \
  --mid-luts "$MID_LUTS" \
  --lut-cones "$LUT_CONES" \
  --manhattan "$MANHATTAN" \
  --lut-bool-exp "$BOOL_JSON" \
  --out "$CONN_FULL"

echo "    [OK] $CONN_FULL geschreven"

# ---------- Stap 3: Scenario 1-filter (subexpressies) ----------

echo "[3/3] Filter Scenario 1 pitstops (subexpressies) → $CONN_SCEN1"
python3 "$FILTER_SCEN1_PY" \
  --in "$CONN_FULL" \
  --lut-cones "$LUT_CONES" \
  --out "$CONN_SCEN1" \
  --min-overlap 2

echo "=============================================="
echo " Klaar."
echo "  - Boolean expressies : $BOOL_JSON"
echo "  - Alle verbindingen  : $CONN_FULL"
echo "  - Scenario 1 pits    : $CONN_SCEN1"
echo "=============================================="
