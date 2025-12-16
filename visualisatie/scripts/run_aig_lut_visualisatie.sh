#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Gebruik:
#   ./run_aig_lut_visualisatie.sh \
#       /home/cian/Masterproef/multisynthesis/results/example_big_300 \
#       0
#
# Argumenten:
#   1) RESULT_DIR  = map onder .../multisynthesis/results (bv. .../example_big_300)
#   2) MID_INDEX   = index in mid_luts.json (default 0)
#
# Output:
#   ~/Masterproef/visualisatie/results/Aig_Lut_visualisatie/<design>/
#     - <design>.pre.aig.dot
#     - <design>.pre.aig.json          (basis)
#     - <design>.annotated.json        (met roles)
#     - <design>.annotated.html        (visualisatie)
# ============================================================

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <RESULT_DIR> [MID_INDEX]"
  exit 1
fi

RESULT_DIR="$1"
MID_INDEX="${2:-0}"

if [[ ! -d "$RESULT_DIR" ]]; then
  echo "[ERROR] RESULT_DIR bestaat niet: $RESULT_DIR"
  exit 1
fi

DESIGN="$(basename "$RESULT_DIR")"

echo "[INFO] Design      : $DESIGN"
echo "[INFO] Result dir  : $RESULT_DIR"
echo "[INFO] MID index   : $MID_INDEX"

# ====== paden naar inputbestanden in multisynthesis/results ======

AIG_PRE="$RESULT_DIR/Elaboration/Aig/${DESIGN}.pre.aig"
LUT_CONES="$RESULT_DIR/JsonMapping/${DESIGN}.lut_cones.json"
MID_LUTS="$RESULT_DIR/PlaceAndRoute/05_custom_outputs/${DESIGN}.mid_luts.json"

if [[ ! -f "$AIG_PRE" ]]; then
  echo "[ERROR] Pre-AIG niet gevonden: $AIG_PRE"
  exit 1
fi
if [[ ! -f "$LUT_CONES" ]]; then
  echo "[ERROR] lut_cones JSON niet gevonden: $LUT_CONES"
  exit 1
fi
if [[ ! -f "$MID_LUTS" ]]; then
  echo "[ERROR] mid_luts JSON niet gevonden: $MID_LUTS"
  exit 1
fi

# ====== paden naar visualisatie scripts ======
# PAS AAN indien je scripts elders staan

VIS_ROOT="$HOME/Masterproef/visualisatie"
SCRIPTS_DIR="$VIS_ROOT/scripts"

AIG_TO_DOT="$SCRIPTS_DIR/aig_to_dot.sh"
DOT_TO_JSON="$SCRIPTS_DIR/dot_json.py"
ANNOTATE="$SCRIPTS_DIR/annotate_graph_with_luts.py"
JSON_TO_HTML="$SCRIPTS_DIR/json_to_html.py"

if [[ ! -f "$AIG_TO_DOT" ]]; then
  echo "[ERROR] aig_to_dot.sh niet gevonden: $AIG_TO_DOT"
  exit 1
fi
if [[ ! -f "$DOT_TO_JSON" ]]; then
  echo "[ERROR] dot_json.py niet gevonden: $DOT_TO_JSON"
  exit 1
fi
if [[ ! -f "$ANNOTATE" ]]; then
  echo "[ERROR] annotate_graph_with_luts.py niet gevonden: $ANNOTATE"
  exit 1
fi
if [[ ! -f "$JSON_TO_HTML" ]]; then
  echo "[ERROR] json_to_html.py niet gevonden: $JSON_TO_HTML"
  exit 1
fi

# ====== output directory ======

OUT_BASE="$VIS_ROOT/results/Aig_Lut_visualisatie"
OUT_DIR="$OUT_BASE/$DESIGN"
mkdir -p "$OUT_DIR"

DOT_FILE="$OUT_DIR/${DESIGN}.pre.aig.dot"
GRAPH_JSON="$OUT_DIR/${DESIGN}.pre.aig.json"
ANNOTATED_JSON="$OUT_DIR/${DESIGN}.annotated.json"
HTML_FILE="$OUT_DIR/${DESIGN}.annotated.html"

echo "[INFO] Output dir  : $OUT_DIR"

# ------------------------------------------------------------
# Stap 1: AIG -> DOT
# ------------------------------------------------------------
echo "[STEP 1] AIG -> DOT: $DOT_FILE"

bash "$AIG_TO_DOT" "$AIG_PRE" "$DOT_FILE"

# ------------------------------------------------------------
# Stap 2: DOT -> JSON (graph voor visualisatie)
# ------------------------------------------------------------
echo "[STEP 2] DOT -> JSON graph: $GRAPH_JSON"

# dot_json.py <dot_file> <json_file>
python3 "$DOT_TO_JSON" "$DOT_FILE" "$GRAPH_JSON"

# ------------------------------------------------------------
# Stap 3: Annoteren met LUT-informatie
# ------------------------------------------------------------
echo "[STEP 3] Annoteren met LUT-info → $ANNOTATED_JSON"

python3 "$ANNOTATE" \
  --graph "$GRAPH_JSON" \
  --lut-cones "$LUT_CONES" \
  --mid-luts "$MID_LUTS" \
  --mid-index "$MID_INDEX" \
  --out "$ANNOTATED_JSON"

# ------------------------------------------------------------
# Stap 4: JSON -> HTML visualisatie
# ------------------------------------------------------------
echo "[STEP 4] JSON -> HTML visualisatie: $HTML_FILE"

# json_to_html.py <json_file> <html_file>
python3 "$JSON_TO_HTML" "$ANNOTATED_JSON" "$HTML_FILE"

echo ""
echo "[DONE] Visualisatie klaar."
echo "       DOT      : $DOT_FILE"
echo "       JSON     : $GRAPH_JSON"
echo "       Annotated: $ANNOTATED_JSON"
echo "       HTML     : $HTML_FILE"
