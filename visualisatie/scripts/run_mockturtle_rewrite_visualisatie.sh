#!/usr/bin/env bash
set -euo pipefail



if [ "$#" -ne 1 ]; then
  echo "Gebruik: $0 pad/naar/design.v"
  exit 1
fi

VERILOG_PATH="$1"

if [ ! -f "$VERILOG_PATH" ]; then
  echo "Bestand niet gevonden: $VERILOG_PATH" >&2
  exit 1
fi

# --- Basis-paden ---

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"   # .../Masterproef
VIS_DIR="$PROJECT_ROOT/visualisatie"
EXAMPLES_DIR="$VIS_DIR/examples"

# ABC-bin: laat toe om dit te overriden met omgeving
ABC_BIN_DEFAULT="$HOME/Masterproef/vtr-verilog-to-routing/abc/abc"
ABC_BIN="${ABC_BIN:-$ABC_BIN_DEFAULT}"
# Mockturtle tool
MT_BIN_DEFAULT="$PROJECT_ROOT/multisynthesis/logicSynthesis/tools/mockturtle/build/mt_rewrite_to_dot"
MT_BIN="${MT_BIN:-$MT_BIN_DEFAULT}"

if [ ! -x "$MT_BIN" ]; then
  echo "[ERROR] mt_rewrite_to_dot niet gevonden of niet uitvoerbaar: $MT_BIN" >&2
  exit 1
fi

# --- Designnaam en outputmappen ---

ABS_V="$(realpath "$VERILOG_PATH")"
BASENAME="$(basename "$ABS_V")"
DESIGN="${BASENAME%.v}"

OUT_ROOT="$EXAMPLES_DIR/mockturtle_rewrite/$DESIGN"
AIG_DIR="$OUT_ROOT/aig"
DOT_DIR="$OUT_ROOT/dot"
JSON_DIR="$OUT_ROOT/json"
HTML_DIR="$OUT_ROOT/html"

mkdir -p "$AIG_DIR" "$DOT_DIR" "$JSON_DIR" "$HTML_DIR"

AIG_IN="$AIG_DIR/${DESIGN}.pre.aig"
AIG_MT="$AIG_DIR/${DESIGN}.post.aig"

DOT_PRE="$DOT_DIR/${DESIGN}.pre.dot"
DOT_POST="$DOT_DIR/${DESIGN}.post.dot"

JSON_PRE="$JSON_DIR/${DESIGN}.pre.json"
JSON_POST="$JSON_DIR/${DESIGN}.post.json"

HTML_PRE="$HTML_DIR/${DESIGN}.pre.html"
HTML_POST="$HTML_DIR/${DESIGN}.post.html"

echo "Design      : $DESIGN"
echo "Verilog     : $ABS_V"
echo "ABC         : $ABC_BIN"
echo "Mockturtle  : $MT_BIN"
echo "Output root : $OUT_ROOT"
echo

# -------------------------------------------------------
# 1) ABC: Verilog → AIG (en eventueel al een DOT vóór rewrite)
# -------------------------------------------------------

echo "[1/4] ABC: lees Verilog en schrijf AIG (pre)..."
"$ABC_BIN" -c "
  read $ABS_V;
  strash;
  write_aiger $AIG_IN;
  write_dot $DOT_PRE;
"

# -------------------------------------------------------
# 2) Mockturtle: AIG herschrijven → nieuwe AIG
#    (hier veronderstellen we dat mt_rewrite_to_dot:
#     - het AIG inleest
#     - een herschreven AIG uitschrijft naar \$AIG_MT
# -------------------------------------------------------

echo "[2/4] Mockturtle: rewrite AIG..."
# Aanname: mt_rewrite_to_dot ingang.aig uitgang.aig
"$MT_BIN" "$AIG_IN" "$AIG_MT"

if [ ! -f "$AIG_MT" ]; then
  echo "[ERROR] Mockturtle heeft geen herschreven AIG gemaakt: $AIG_MT" >&2
  exit 1
fi

# -------------------------------------------------------
# 3) ABC: herschreven AIG → DOT (post)
# -------------------------------------------------------

echo "[3/4] ABC: herschreven AIG naar DOT..."
"$ABC_BIN" -c "
  read_aiger $AIG_MT;
  strash;
  write_dot $DOT_POST;
"

# -------------------------------------------------------
# 4) Visualisatie: DOT → JSON → HTML (zoals run_all_visualisatie)
# -------------------------------------------------------

echo "[4/4] Visualisatie: DOT → JSON → HTML..."

# DOT → JSON
python3 "$VIS_DIR/scripts/dot_json.py"   "$DOT_PRE"  "$JSON_PRE"
python3 "$VIS_DIR/scripts/dot_json.py"   "$DOT_POST" "$JSON_POST"

# JSON → HTML
python3 "$VIS_DIR/scripts/json_to_html.py" "$JSON_PRE"  "$HTML_PRE"
python3 "$VIS_DIR/scripts/json_to_html.py" "$JSON_POST" "$HTML_POST"

echo
echo "Klaar."
echo "  Pre-rewrite :"
echo "    AIG  = $AIG_IN"
echo "    DOT  = $DOT_PRE"
echo "    JSON = $JSON_PRE"
echo "    HTML = $HTML_PRE"
echo
echo "  Post-rewrite:"
echo "    AIG  = $AIG_MT"
echo "    DOT  = $DOT_POST"
echo "    JSON = $JSON_POST"
echo "    HTML = $HTML_POST"
