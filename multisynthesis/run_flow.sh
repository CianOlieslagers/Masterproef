#!/usr/bin/env bash
set -euo pipefail

# =======================================
#  Config
# =======================================

RESULTS_ROOT="${RESULTS_ROOT:-$HOME/Masterproef/multisynthesis/results}"
K="${K:-4}"

ELAB_SCRIPT="${ELAB_SCRIPT:-$HOME/Masterproef/multisynthesis/elaboration/scripts/VtoAigBlif.sh}"
SYN_SCRIPT="${SYN_SCRIPT:-$HOME/Masterproef/multisynthesis/logicSynthesis/scripts/logic_synth_mt.sh}"
PAR_SCRIPT="${PAR_SCRIPT:-$HOME/Masterproef/multisynthesis/placeAndRoute/scripts/PlacementRouting.sh}"

ORG_SCRIPT="${ORG_SCRIPT:-$HOME/Masterproef/multisynthesis/placeAndRoute/scripts/organize_vpr_outputs.sh}"
ARCH_XML="${ARCH_XML:-$HOME/Masterproef/vtr-verilog-to-routing/vtr_flow/arch/custom/markus_k4.xml}"

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
# Output-structuur opzetten
# =======================================

OUT_DIR="$RESULTS_ROOT/$design"
ELAB_DIR="$OUT_DIR/Elaboration"
LOGS_DIR="$OUT_DIR/_logs"

mkdir -p "$ELAB_DIR" "$LOGS_DIR" \
         "$OUT_DIR/LogicSynthesis" \
         "$OUT_DIR/topologymapping" \
         "$OUT_DIR/JsonMapping"

# =======================================
# Stap 1 — Elaboration
# =======================================

echo "[1/6] Elaboration (Yosys) …"

ELAB_LOG="$LOGS_DIR/${design}.elab.log"

"$ELAB_SCRIPT" \
    "$VFILE" \
    --out-dir "$ELAB_DIR" \
    > "$ELAB_LOG" 2>&1

PRE_BLIF="$ELAB_DIR/Blif/${design}.pre.blif"
PRE_AAG_YOSYS="$ELAB_DIR/Aig/${design}.pre.aag"

[[ -s "$PRE_BLIF"       ]] || fail "Ontbreekt: $PRE_BLIF"
[[ -s "$PRE_AAG_YOSYS"  ]] || fail "Ontbreekt: $PRE_AAG_YOSYS"


# =======================================
# Stap 2 — ABC cleansing (maak clean AIG voor Mockturtle)
# =======================================

echo "[2/6] ABC: strash + write_aiger (clean AIG) …"

ABC_BIN="${ABC_BIN:-$HOME/Masterproef/vtr-verilog-to-routing/abc/abc}"

CLEAN_AIG="$ELAB_DIR/Aig/${design}.clean.aig"
ABC_LOG="$LOGS_DIR/${design}.abc.clean.log"

"$ABC_BIN" -c "
read_blif $PRE_BLIF;
strash;
write_aiger $CLEAN_AIG;
" > "$ABC_LOG" 2>&1


[[ -s "$CLEAN_AIG" ]] || fail "ABC kon geen clean AIG genereren: $CLEAN_AIG"

# =======================================
# Stap 3 — Logic Synthesis (Mockturtle)
# =======================================

echo "[3/6] Logic synthesis (Mockturtle) op clean .aig …"

MT_WRAP_LOG="$LOGS_DIR/${design}.mt.wrapper.log"

"$SYN_SCRIPT" \
    "$CLEAN_AIG" \
    --lut "$K" \
    --out-dir "$OUT_DIR/LogicSynthesis" \
    --log-dir "$LOGS_DIR" \
    > "$MT_WRAP_LOG" 2>&1

MT_BASENAME="$(basename "$CLEAN_AIG")"   # bv. example_big_300.clean.aig
MT_DESIGN="${MT_BASENAME%.*}"            # bv. example_big_300.clean

# Hier nog geen BLIF meer; die komt straks uit mt_lut_cones
POSTOPT_AIG="$OUT_DIR/LogicSynthesis/Aig/${MT_DESIGN}.postopt.aig"
[[ -s "$POSTOPT_AIG" ]] || fail "Ontbreekt: $POSTOPT_AIG"

# ---------------------------------------
# Extra stap — Equivalence check AIG vóór/na Mockturtle
# ---------------------------------------
echo "[3b/6] Equivalence check (mt_aig_equiv) …"

MT_AIG_EQUIV_BIN="${MT_AIG_EQUIV_BIN:-$HOME/Masterproef/multisynthesis/logicSynthesis/tools/mockturtle/build/mt_aig_equiv}"
[[ -x "$MT_AIG_EQUIV_BIN" ]] || fail "mt_aig_equiv binary niet gevonden of niet uitvoerbaar: $MT_AIG_EQUIV_BIN"

AIG_EQUIV_LOG="$LOGS_DIR/${design}.aig_equiv.log"

if ! "$MT_AIG_EQUIV_BIN" "$CLEAN_AIG" "$POSTOPT_AIG" >"$AIG_EQUIV_LOG" 2>&1; then
  echo "[ERROR] AIG equivalence check is NIET geslaagd. Zie log:"
  cat "$AIG_EQUIV_LOG"
  fail "Logic synthesis heeft de functionaliteit gewijzigd (mt_aig_equiv gaf een fout of mismatch)."
else
  echo "[3b/6] Equivalence check geslaagd: CLEAN_AIG ≡ POSTOPT_AIG"
fi

# Hier nog geen BLIF meer; die komt straks uit mt_lut_cones


# =======================================
# Stap 3 — LUT → AIG cones (mt_lut_cones)
# =======================================
echo "[3/5] Export LUT→AIG cones (mt_lut_cones) …"

MT_LUT_CONES_BIN="${MT_LUT_CONES_BIN:-$HOME/Masterproef/multisynthesis/logicSynthesis/tools/mockturtle/build/mt_lut_cones}"
[[ -x "$MT_LUT_CONES_BIN" ]] || fail "mt_lut_cones binary niet gevonden: $MT_LUT_CONES_BIN"

LUT_JSON="$OUT_DIR/JsonMapping/${design}.lut_cones.json"
LUT_LOG="$LOGS_DIR/${design}.lut_cones.log"
MAPPED_BLIF="$OUT_DIR/topologymapping/${design}.mapped.blif"

"$MT_LUT_CONES_BIN" \
    --aig "$POSTOPT_AIG" \
    --out-json "$LUT_JSON" \
    --out-blif "$MAPPED_BLIF" \
    --lut "$K" \
    --top "$design" \
    > "$LUT_LOG" 2>&1

[[ -s "$LUT_JSON"   ]] || fail "LUT JSON niet gegenereerd: $LUT_JSON"
[[ -s "$MAPPED_BLIF" ]] || fail "Mapped BLIF niet gegenereerd: $MAPPED_BLIF"

# =======================================
# Stap 4 — Placement & Routing (VPR)
# =======================================

echo "[4/5] Placement & routing (VPR) …"

VPR_LOG="$LOGS_DIR/${design}.vpr.log"

"$PAR_SCRIPT" \
    --arch "$ARCH_XML" \
    --blif "$OUT_DIR/topologymapping/${design}.mapped.blif" \
    --circuit "$design" \
    > "$VPR_LOG" 2>&1

ARCH_TAG="$(basename "$ARCH_XML" .xml)"
VPR_SRC_DIR="$HOME/Masterproef/multisynthesis/placeAndRoute/results/build_vpr/$ARCH_TAG/$design"
VPR_DEST_DIR="$OUT_DIR/PlaceAndRoute"

if [ -d "$VPR_SRC_DIR" ]; then
  mkdir -p "$VPR_DEST_DIR"
  cp -a "$VPR_SRC_DIR"/. "$VPR_DEST_DIR"/

  if [ -x "$ORG_SCRIPT" ]; then
    "$ORG_SCRIPT" --dir "$VPR_DEST_DIR" || echo "Waarschuwing: organiseren van VPR outputs faalde" >>"$LOGS_DIR/${design}.vpr.log"
  else
    echo "Waarschuwing: organize_vpr_outputs.sh niet uitvoerbaar of niet gevonden" >>"$LOGS_DIR/${design}.vpr.log"
  fi
else
  echo "Waarschuwing: VPR bronmap niet gevonden: $VPR_SRC_DIR" >>"$LOGS_DIR/${design}.vpr.log"
fi

# =======================================
# Stap 4b — PRE-ROUTING Manhattan analyse
# (ongewijzigd t.o.v. je huidige versie)
# =======================================

echo "[4b] Pre-routing placement analyse (Manhattan) ..."

PAR_ROOT="${PAR_ROOT:-$HOME/Masterproef/multisynthesis/placeAndRoute}"
TEST_SCRIPTS="$PAR_ROOT/scripts/TestPlacement"
PYTHON="${PYTHON:-python3}"

VPR_BIN="${VPR_BIN:-$(command -v vpr || true)}"
if [[ -z "$VPR_BIN" ]]; then
  CAND="$HOME/Masterproef/vtr-verilog-to-routing/vpr/vpr"
  [[ -x "$CAND" ]] || fail "vpr niet gevonden (zet VPR_BIN of pas pad aan in run_flow.sh)"
  VPR_BIN="$CAND"
fi

ARCH_TAG="$(basename "$ARCH_XML" .xml)"
BUILD_PRE="$PAR_ROOT/results/build_vpr_pre/$ARCH_TAG/$design"
mkdir -p "$BUILD_PRE"

pushd "$BUILD_PRE" >/dev/null

"$VPR_BIN" "$ARCH_XML" "$OUT_DIR/topologymapping/${design}.mapped.blif" \
    --pack --place \
    --route_chan_width 100 \
    --echo_file on \
    > "$LOGS_DIR/${design}.vpr_place_only.log" 2>&1

popd >/dev/null

PRE_PAR_DIR="$OUT_DIR/PlaceAndRoute"
PRE_LOC="$PRE_PAR_DIR/01_location"
PRE_CUSTOM_DIR="$PRE_PAR_DIR/05_custom_outputs"
mkdir -p "$PRE_LOC" "$PRE_CUSTOM_DIR"

cp "$BUILD_PRE/${design}.mapped.place" "$PRE_LOC/"
cp "$BUILD_PRE/${design}.mapped.net"   "$PRE_LOC/"

"$PYTHON" "$TEST_SCRIPTS/make_manhatten_json.py" \
    --place "$PRE_LOC/${design}.mapped.place" \
    --net   "$PRE_LOC/${design}.mapped.net" \
    --out   "$PRE_CUSTOM_DIR/${design}.manhattan.json" \
    --design "$design"

"$PYTHON" "$TEST_SCRIPTS/find_longest_mangatten_edge.py" \
    --json "$PRE_CUSTOM_DIR/${design}.manhattan.json" \
    --top  20 \
    --out-csv "$PRE_CUSTOM_DIR/${design}.top20_manhattan.csv"

echo "[4b] Manhattan JSON + Top20 verbindingen gegenereerd."

# =======================================
# Stap 4c — Mid-LUT analyse + selectie
# (zoals je eerder had, blijft gelijk)
# =======================================

echo "[4c] Mid-LUT analyse (kandidaten zoeken) ..."

LUT_ANALYSE_DIR="$PAR_ROOT/scripts/LutAnalyse"
MID_LUTS_JSON="$PRE_CUSTOM_DIR/${design}.mid_luts.json"
BEST_MID_LUTS_JSON="$PRE_CUSTOM_DIR/${design}.best_mid_luts.json"

MID_LUT_TOP="${MID_LUT_TOP:-5}"

"$PYTHON" "$LUT_ANALYSE_DIR/find_mid_luts.py" \
    --json "$PRE_CUSTOM_DIR/${design}.manhattan.json" \
    --csv  "$PRE_CUSTOM_DIR/${design}.top20_manhattan.csv" \
    --out  "$MID_LUTS_JSON" \
    --min-gain 0.0

echo "[4c] Mid-LUT kandidaten geschreven naar: $MID_LUTS_JSON"

echo "[4c] Selecteer beste mid-LUT combinaties (top=$MID_LUT_TOP) ..."

"$PYTHON" "$LUT_ANALYSE_DIR/select_best_mid_luts.py" \
    --mid-luts-json "$MID_LUTS_JSON" \
    --top "$MID_LUT_TOP" \
    --out-json "$BEST_MID_LUTS_JSON"

echo "[4c] Beste mid-LUT combinaties geschreven naar: $BEST_MID_LUTS_JSON"

# =======================================
# Stap 5 — Samenvatting
# =======================================

echo "[5/5] Klaar voor $design"
echo "  Elaboration    : $ELAB_DIR"
echo "  LogicSynthesis : $OUT_DIR/LogicSynthesis"
echo "  TopologyMapping: $OUT_DIR/topologymapping"
echo "  JsonMapping    : $OUT_DIR/JsonMapping"
echo "  PlaceAndRoute  : $OUT_DIR/PlaceAndRoute"
echo "  Logs           : $LOGS_DIR"
