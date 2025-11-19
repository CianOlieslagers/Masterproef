#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Gebruik: $0 pad/naar/design.v"
  exit 1
fi

VERILOG_PATH="$1"

if [ ! -f "$VERILOG_PATH" ]; then
  echo "Bestand niet gevonden: $VERILOG_PATH"
  exit 1
fi

# --- Paden (pas aan indien nodig) ---
ABC="$HOME/Masterproef/vtr-verilog-to-routing/abc/abc"
SCRIPTS_DIR="$HOME/Masterproef/visualisatie/scripts"
DOT_JSON="$SCRIPTS_DIR/dot_json.py"
JSON_HTML="$SCRIPTS_DIR/json_to_html.py"

# --- Basisnamen + outputdirs ---

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BASE_NAME="$(basename "$VERILOG_PATH" .v)"

# Outputmap: <script-map>/<v-naam>
OUT_ROOT="$SCRIPT_DIR/$BASE_NAME"

DOT_DIR="$OUT_ROOT/dot"
JSON_DIR="$OUT_ROOT/json"
HTML_DIR="$OUT_ROOT/html"

mkdir -p "$DOT_DIR" "$JSON_DIR" "$HTML_DIR"

PRE_DOT="$DOT_DIR/${BASE_NAME}.pre.dot"
POST_DOT="$DOT_DIR/${BASE_NAME}.post.dot"

PRE_JSON="$JSON_DIR/${BASE_NAME}.pre.json"
POST_JSON="$JSON_DIR/${BASE_NAME}.post.json"

PRE_HTML="$HTML_DIR/${BASE_NAME}.pre.html"
POST_HTML="$HTML_DIR/${BASE_NAME}.post.html"

echo "Design  : $BASE_NAME"
echo "Verilog : $VERILOG_PATH"
echo "Output  : $OUT_ROOT"
echo

# --- 1) ABC: DOT vóór en ná RESUB (substitution) ---
echo "[ABC] pre-dot (strash)..."
"$ABC" -c "read $VERILOG_PATH; strash; write_dot $PRE_DOT"

echo "[ABC] post-dot (strash + resub)..."
"$ABC" -c "read $VERILOG_PATH; strash; resub; write_dot $POST_DOT"

# --- 2) DOT -> JSON ---
echo "[dot_json] pre-dot -> json..."
python3 "$DOT_JSON" "$PRE_DOT" "$PRE_JSON"

echo "[dot_json] post-dot -> json..."
python3 "$DOT_JSON" "$POST_DOT" "$POST_JSON"

# --- 3) JSON -> HTML ---
echo "[json_to_html] pre-json -> html..."
python3 "$JSON_HTML" "$PRE_JSON" "$PRE_HTML"

echo "[json_to_html] post-json -> html..."
python3 "$JSON_HTML" "$POST_JSON" "$POST_HTML"

echo
echo "Klaar! Resultaten:"
echo "  DOT : $DOT_DIR"
echo "  JSON: $JSON_DIR"
echo "  HTML: $HTML_DIR"
