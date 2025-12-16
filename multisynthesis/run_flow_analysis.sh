#!/usr/bin/env bash
set -euo pipefail

# =======================================
#  Config
# =======================================

RESULTS_ROOT="${RESULTS_ROOT:-$HOME/Masterproef/multisynthesis/results}"
K="${K:-4}"

ELAB_SCRIPT="${ELAB_SCRIPT:-$HOME/Masterproef/multisynthesis/elaboration/scripts/VtoAigBlif.sh}"
SYN_SCRIPT="${SYN_SCRIPT:-$HOME/Masterproef/multisynthesis/logicSynthesis/scripts/logic_synth.sh}"
PROV_SCRIPT="${PROV_SCRIPT:-$HOME/Masterproef/multisynthesis/logicSynthesis/scripts/export_lut_provenance.sh}"

# Post-routing wrapper (pack+place+route+timing)
PAR_SCRIPT="${PAR_SCRIPT:-$HOME/Masterproef/multisynthesis/placeAndRoute/scripts/PlacementRouting_volledig.sh}"

ORG_SCRIPT="${ORG_SCRIPT:-$HOME/Masterproef/multisynthesis/placeAndRoute/scripts/organize_vpr_outputs.sh}"
ARCH_XML="${ARCH_XML:-$HOME/Masterproef/vtr-verilog-to-routing/vtr_flow/arch/custom/markus_k4.xml}"

PAR_ROOT="$HOME/Masterproef/multisynthesis/placeAndRoute"
SCRIPTS_DIR="$PAR_ROOT/scripts"
TEST_SCRIPTS_DIR="$PAR_ROOT/scripts/TestPlacement"

PYTHON="${PYTHON:-python3}"

fail(){ echo "ERROR: $*" >&2; exit 1; }

# =======================================
# 1 ARGUMENT: PAD NAAR .v BESTAND
# =======================================

if [[ $# -ne 1 ]]; then
  echo "Gebruik: $0 PAD/NAAR/design.v"
  exit 1
fi

VFILE="$(realpath -m "$1")"
[[ -f "$VFILE" ]] || fail ".v bestand bestaat niet: $VFILE"

base="$(basename "$VFILE")"
design="${base%.*}"

echo "======================"
echo "Design: $design"
echo "Bron  : $VFILE"
echo "======================"

# =======================================
# Analysis root + pre/post directories
# =======================================

ANALYSIS_ROOT="$RESULTS_ROOT/${design}_analysis"
PRE_OUT="$ANALYSIS_ROOT/preRouting"
POST_OUT="$ANALYSIS_ROOT/postRouting"
ANALYSIS_DIR="$ANALYSIS_ROOT/analysis"

# Maak basisstructuur voor beide flows
for OUT in "$PRE_OUT" "$POST_OUT"; do
  mkdir -p "$OUT"/{Elaboration,LogicSynthesis,topologymapping,JsonMapping,PlaceAndRoute,_logs}
done
mkdir -p "$ANALYSIS_DIR"

# =======================================
# Stap 1 — Elaboration (in preRouting)
# =======================================

echo "[1/6] Elaboration (preRouting) …"

ELAB_DIR="$PRE_OUT/Elaboration"
LOGS_DIR_PRE="$PRE_OUT/_logs"

ELAB_LOG="$LOGS_DIR_PRE/${design}.elab.log"

"$ELAB_SCRIPT" \
    "$VFILE" \
    --out-dir "$ELAB_DIR" \
    > "$ELAB_LOG" 2>&1

PRE_BLIF="$ELAB_DIR/Blif/${design}.pre.blif"
PRE_AAG="$ELAB_DIR/Aig/${design}.pre.aag"
PRE_AIG="$ELAB_DIR/Aig/${design}.pre.aig"

[[ -s "$PRE_BLIF" ]] || fail "Ontbreekt: $PRE_BLIF"
[[ -s "$PRE_AAG"  ]] || fail "Ontbreekt: $PRE_AAG"
[[ -s "$PRE_AIG"  ]] || fail "Ontbreekt: $PRE_AIG"

# =======================================
# Stap 2 — Logic Synthesis + K-LUT mapping (preRouting)
# =======================================

echo "[2/6] Logic synthesis + mapping (K=$K, preRouting) …"

TMP_SYN_DIR="$PRE_OUT/.build_logic"
mkdir -p "$TMP_SYN_DIR"

SYN_LOG="$LOGS_DIR_PRE/${design}.abc.log"

"$SYN_SCRIPT" \
    "$PRE_AIG" \
    --lut "$K" \
    --out-dir "$TMP_SYN_DIR" \
    > "$SYN_LOG" 2>&1

POSTOPT_AIG="$TMP_SYN_DIR/Aig/${design}.postopt.aig"
POSTMAP_AIG="$TMP_SYN_DIR/Aig/${design}.postmap.aig"
MAPPED_BLIF="$TMP_SYN_DIR/Blif/${design}.mapped.blif"

[[ -s "$POSTOPT_AIG" ]] || fail "Ontbreekt: $POSTOPT_AIG"
[[ -s "$MAPPED_BLIF" ]] || fail "Ontbreekt: $MAPPED_BLIF"

mv "$POSTOPT_AIG" "$PRE_OUT/LogicSynthesis/${design}.postopt.aig"
[[ -s "$POSTMAP_AIG" ]] && mv "$POSTMAP_AIG" "$PRE_OUT/topologymapping/${design}.postmap.aig"
mv "$MAPPED_BLIF" "$PRE_OUT/topologymapping/${design}.mapped.blif"

rm -rf "$TMP_SYN_DIR"

# =======================================
# Stap 3 — LUT Provenance (preRouting)
# =======================================

echo "[3/6] Export LUT-provenance JSON (preRouting) …"

export OUT_DIR="$PRE_OUT"

PROV_LOG="$LOGS_DIR_PRE/${design}.prov.log"
POSTOPT_AIG_PRE="$PRE_OUT/LogicSynthesis/${design}.postopt.aig"

"$PROV_SCRIPT" \
    --blif "$PRE_OUT/topologymapping/${design}.mapped.blif" \
    --aag  "$POSTOPT_AIG_PRE" \
    --design "$design" \
    > "$PROV_LOG" 2>&1

if [[ -d "$PRE_OUT/Provenance" ]]; then
  shopt -s nullglob
  for f in "$PRE_OUT/Provenance/${design}.lut_to_aig_leaves."{json,lut_nodes.csv,pi_counts.csv}; do
    [[ -e "$f" ]] && mv "$f" "$PRE_OUT/JsonMapping/"
  done
  rmdir "$PRE_OUT/Provenance" 2>/dev/null || true
fi

# =======================================
# Kopieer statische resultaten naar postRouting
# =======================================

echo "[3b] Kopieer elab/synth/mapping naar postRouting …"

cp -a "$PRE_OUT/Elaboration/."     "$POST_OUT/Elaboration/"
cp -a "$PRE_OUT/LogicSynthesis/."  "$POST_OUT/LogicSynthesis/"
cp -a "$PRE_OUT/topologymapping/." "$POST_OUT/topologymapping/"
cp -a "$PRE_OUT/JsonMapping/."     "$POST_OUT/JsonMapping/" || true

LOGS_DIR_POST="$POST_OUT/_logs"
mkdir -p "$LOGS_DIR_POST"

# =======================================
# Stap 4a — VPR pack+place ONLY (preRouting) + Manhattan JSON
# =======================================

echo "[4/6] VPR pack+place ONLY (preRouting) …"

# Zoek vpr binary
VPR_BIN="${VPR_BIN:-$(command -v vpr || true)}"
if [[ -z "${VPR_BIN:-}" ]]; then
  CAND="$HOME/Masterproef/vtr-verilog-to-routing/vpr/vpr"
  [[ -x "$CAND" ]] || fail "vpr niet gevonden (zet VPR_BIN of pas pad aan)"
  VPR_BIN="$CAND"
fi

ARCH_TAG="$(basename "$ARCH_XML" .xml)"

# Pre-routing build dir (apart van de gewone build_vpr)
BUILD_PRE="$PAR_ROOT/results/build_vpr_pre/$ARCH_TAG/$design"
mkdir -p "$BUILD_PRE"

pushd "$BUILD_PRE" >/dev/null

"$VPR_BIN" "$ARCH_XML" "$PRE_OUT/topologymapping/${design}.mapped.blif" \
  --pack --place \
  --route_chan_width 100 \
  --echo_file on \
  > "$LOGS_DIR_PRE/${design}.vpr_place_only.log" 2>&1

popd >/dev/null

# Kopieer .place/.net naar preRouting/PlaceAndRoute/01_location
PRE_PAR_DIR="$PRE_OUT/PlaceAndRoute"
PRE_LOC_DIR="$PRE_PAR_DIR/01_location"
mkdir -p "$PRE_LOC_DIR"

cp "$BUILD_PRE/${design}.mapped.net"   "$PRE_LOC_DIR/${design}.mapped.net"
cp "$BUILD_PRE/${design}.mapped.place" "$PRE_LOC_DIR/${design}.mapped.place"

# Manhattan JSON + Top-N CSV
PRE_CUSTOM_DIR="$PRE_PAR_DIR/05_custom_outputs"
mkdir -p "$PRE_CUSTOM_DIR"

"$PYTHON" "$TEST_SCRIPTS_DIR/make_manhatten_json.py" \
  --place "$PRE_LOC_DIR/${design}.mapped.place" \
  --net   "$PRE_LOC_DIR/${design}.mapped.net" \
  --out   "$PRE_CUSTOM_DIR/${design}.manhattan.json" \
  --design "$design"

"$PYTHON" "$TEST_SCRIPTS_DIR/find_longest_mangatten_edge.py" \
  --json "$PRE_CUSTOM_DIR/${design}.manhattan.json" \
  --top  20 \
  --out-csv "$PRE_CUSTOM_DIR/${design}.top20_manhattan.csv"

echo "[4a] preRouting klaar: Manhattan JSON en Top20 CSV gegenereerd."

# =======================================
# Stap 4b — Volledige Placement & Routing (postRouting)
# =======================================

echo "[4/6] Volledige Placement & routing (postRouting) …"

VPR_LOG_POST="$LOGS_DIR_POST/${design}.vpr.log"

"$PAR_SCRIPT" \
    --arch "$ARCH_XML" \
    --blif "$POST_OUT/topologymapping/${design}.mapped.blif" \
    --circuit "$design" \
    > "$VPR_LOG_POST" 2>&1

# Kopieer en organiseer VPR-output naar postRouting/PlaceAndRoute
VPR_SRC_DIR="$PAR_ROOT/results/build_vpr/$ARCH_TAG/$design"
VPR_DEST_DIR="$POST_OUT/PlaceAndRoute"

if [ -d "$VPR_SRC_DIR" ]; then
  mkdir -p "$VPR_DEST_DIR"
  cp -a "$VPR_SRC_DIR"/. "$VPR_DEST_DIR"/

  if [ -x "$ORG_SCRIPT" ]; then
    "$ORG_SCRIPT" --dir "$VPR_DEST_DIR" || echo "Waarschuwing: organiseren van VPR outputs faalde" >>"$VPR_LOG_POST"
  else
    echo "Waarschuwing: organize_vpr_outputs.sh niet uitvoerbaar of niet gevonden" >>"$VPR_LOG_POST"
  fi
else
  echo "Waarschuwing: VPR bronmap niet gevonden: $VPR_SRC_DIR" >>"$VPR_LOG_POST"
fi

# =======================================
# Stap 4c — Route-analyse: LUT-phys graph + langste paden (postRouting)
# =======================================

POST_PAR_DIR="$POST_OUT/PlaceAndRoute"
POST_CUSTOM_DIR="$POST_PAR_DIR/05_custom_outputs"
mkdir -p "$POST_CUSTOM_DIR"

ROUTE_FILE="$POST_PAR_DIR/03_routing/${design}.mapped.route"
ROUTE_JSON="$POST_CUSTOM_DIR/${design}.route_lut_graph.json"
LONGEST_TXT="$POST_CUSTOM_DIR/${design}.route_longest_paths.txt"

if [[ -f "$ROUTE_FILE" ]]; then
  "$PYTHON" "$SCRIPTS_DIR/parse_lut_phy_graph.py" \
    --route "$ROUTE_FILE" \
    --out "$ROUTE_JSON"

  "$PYTHON" "$SCRIPTS_DIR/find_longest_paths.py" \
    "$ROUTE_JSON" \
    > "$LONGEST_TXT"

  echo "[4c] postRouting: route_lut_graph.json en route_longest_paths.txt gegenereerd."
else
  echo "⚠  Route-bestand niet gevonden: $ROUTE_FILE" >>"$VPR_LOG_POST"
fi

# =======================================
# Stap 5 — Analyse pre vs post (compare_pre_post_paths)
# =======================================

echo "[5/6] Analyse pre vs post (TopN edges) …"

PRE_TOP_CSV="$PRE_OUT/PlaceAndRoute/05_custom_outputs/${design}.top20_manhattan.csv"
POST_LUT_JSON="$POST_OUT/PlaceAndRoute/05_custom_outputs/${design}.route_lut_graph.json"
ANALYSIS_CSV="$ANALYSIS_DIR/${design}.pre_vs_post_paths.csv"
ANALYSIS_TXT="$ANALYSIS_DIR/${design}.pre_vs_post_paths.txt"

if [[ -f "$PRE_TOP_CSV" && -f "$POST_LUT_JSON" ]]; then
  "$PYTHON" "$SCRIPTS_DIR/compare_pre_post_paths.py" \
    --design "$design" \
    --pre-csv "$PRE_TOP_CSV" \
    --post-json "$POST_LUT_JSON" \
    --out-csv "$ANALYSIS_CSV" \
    --out-txt "$ANALYSIS_TXT"

  echo "[5] Analyse geschreven naar:"
  echo "    - $ANALYSIS_CSV"
  echo "    - $ANALYSIS_TXT"
else
  echo "⚠  Kan analyse niet uitvoeren (ontbrekende input):" >>"$LOGS_DIR_POST/${design}.analysis.warn.log"
  echo "   PRE_TOP_CSV   = $PRE_TOP_CSV"                  >>"$LOGS_DIR_POST/${design}.analysis.warn.log"
  echo "   POST_LUT_JSON = $POST_LUT_JSON"                >>"$LOGS_DIR_POST/${design}.analysis.warn.log"
fi

# =======================================
# Stap 6 — Samenvatting
# =======================================

echo "[6/6] Klaar voor $design"
echo
echo "  preRouting  : $PRE_OUT"
echo "    - PlaceAndRoute/01_location/*.place/*.net"
echo "    - PlaceAndRoute/05_custom_outputs/${design}.manhattan.json"
echo "    - PlaceAndRoute/05_custom_outputs/${design}.top20_manhattan.csv"
echo
echo "  postRouting : $POST_OUT"
echo "    - PlaceAndRoute/03_routing/${design}.mapped.route"
echo "    - PlaceAndRoute/05_custom_outputs/${design}.route_lut_graph.json"
echo "    - PlaceAndRoute/05_custom_outputs/${design}.route_longest_paths.txt"
echo
echo "  analysis    : $ANALYSIS_DIR"
echo "    - ${design}.pre_vs_post_paths.csv"
echo "    - ${design}.pre_vs_post_paths.txt"
echo
echo "Logs:"
echo "  preRouting logs : $LOGS_DIR_PRE"
echo "  postRouting logs: $LOGS_DIR_POST"
