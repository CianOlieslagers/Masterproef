#!/usr/bin/env bash
set -euo pipefail

# ========= Config =========
SRC_DIR="${SRC_DIR:-$HOME/Masterproef/benchmarks/Benchmark/EPFL_Benchmarks/arithmetic}"
RESULTS_ROOT="${RESULTS_ROOT:-$HOME/Masterproef/multisynthesis/results}"
K="${K:-6}"

# Paden naar jouw subscripts (zoals je me gaf)
ELAB_SCRIPT="${ELAB_SCRIPT:-$HOME/Masterproef/multisynthesis/elaboration/scripts/VtoAigBlif.sh}"
SYN_SCRIPT="${SYN_SCRIPT:-$HOME/Masterproef/multisynthesis/logicSynthesis/scripts/logic_synth.sh}"
PROV_SCRIPT="${PROV_SCRIPT:-$HOME/Masterproef/multisynthesis/logicSynthesis/scripts/export_lut_provenance.sh}"

# Optioneel: tools (alleen nodig als je wil forceren)
# export YOSYS_BIN="$HOME/oss-cad-suite/bin/yosys"
# export ABC_BIN="$HOME/Masterproef/vtr-verilog-to-routing/build/abc/abc"

fail(){ echo "ERROR: $*" >&2; exit 1; }

[ -x "$ELAB_SCRIPT" ] || fail "Niet uitvoerbaar: $ELAB_SCRIPT"
[ -x "$SYN_SCRIPT" ]  || fail "Niet uitvoerbaar: $SYN_SCRIPT"
[ -x "$PROV_SCRIPT" ] || fail "Niet uitvoerbaar: $PROV_SCRIPT"
[ -d "$SRC_DIR" ] || fail "SRC_DIR bestaat niet: $SRC_DIR"
mkdir -p "$RESULTS_ROOT"

shopt -s nullglob
for vfile in "$SRC_DIR"/*.v; do
  base="$(basename "$vfile")"
  design="${base%.*}"

  echo "======================"
  echo "Design: $design"
  echo "Bron  : $vfile"
  echo "======================"

  OUT_DIR="$RESULTS_ROOT/$design"
  ELAB_DIR="$OUT_DIR/Elaboration"
  LOGS_DIR="$OUT_DIR/_logs"             # lokale logdump
  mkdir -p "$ELAB_DIR" "$LOGS_DIR" "$OUT_DIR/LogicSynthesis" "$OUT_DIR/topologymapping" "$OUT_DIR/JsonMapping"

  # ---------- Stap 1: Elaboration (Yosys) ----------
  # Waarom dit werkt: jouw VtoAigBlif.sh accepteert --out-dir en maakt daarbinnen Blif/ en Aig/ aan.
  # We houden pre-artifacten onder Elaboration/.
  echo "[1/4] Elaboration …"
  ELAB_LOG="$LOGS_DIR/${design}.elab.log"
  "$ELAB_SCRIPT" \
      "$vfile" \
      --top "$design" \
      --out-dir "$ELAB_DIR" \
      >"$ELAB_LOG" 2>&1

  PRE_BLIF="$ELAB_DIR/Blif/${design}.pre.blif"
  PRE_AAG="$ELAB_DIR/Aig/${design}.pre.aag"
  [ -s "$PRE_BLIF" ] || fail "Elaboration BLIF ontbreekt: $PRE_BLIF"
  [ -s "$PRE_AAG" ]  || fail "Elaboration AAG ontbreekt: $PRE_AAG"

  # ---------- Stap 2: Logic Synthesis & K-LUT mapping (ABC) ----------
  # Waarom dit werkt: jouw logic_synth.sh accepteert .aag/.blif en schrijft naar OUT_DIR/{Aig,Blif}.
  # We laten naar een tijdelijke buildmap onder het design schrijven en verplaatsen daarna gericht.
  echo "[2/4] Logic synthesis + mapping (K=$K) …"
  TMP_SYN_DIR="$OUT_DIR/.build_logic"
  mkdir -p "$TMP_SYN_DIR"
  SYN_LOG="$LOGS_DIR/${design}.abc.log"

  "$SYN_SCRIPT" \
      "$PRE_AAG" \
      --lut "$K" \
      --out-dir "$TMP_SYN_DIR" \
      >"$SYN_LOG" 2>&1

  # Verwachte outputs van logic_synth.sh
  POSTOPT_AIG="$TMP_SYN_DIR/Aig/${design}.postopt.aig"
  POSTMAP_AIG="$TMP_SYN_DIR/Aig/${design}.postmap.aig"
  MAPPED_BLIF="$TMP_SYN_DIR/Blif/${design}.mapped.blif"

  [ -s "$POSTOPT_AIG" ] || fail "Ontbreekt: $POSTOPT_AIG"
  [ -s "$MAPPED_BLIF" ] || fail "Ontbreekt: $MAPPED_BLIF"
  # POSTMAP_AIG is er tenzij --no-postmap-aig; wij gebruiken default (=aan)
  [ -s "$POSTMAP_AIG" ] || echo "Waarschuwing: geen postmap AIG gevonden ($POSTMAP_AIG)"

  # Herordenen naar jouw structuur:
  #  - LogicSynthesis: postopt (combi-opt resultaat) + ABC-log
  #  - topologymapping: mapped.blif (+ postmap.aig indien aanwezig)
  mv -f "$POSTOPT_AIG" "$OUT_DIR/LogicSynthesis/${design}.postopt.aig"
  [ -s "$POSTMAP_AIG" ] && mv -f "$POSTMAP_AIG" "$OUT_DIR/topologymapping/${design}.postmap.aig"
  mv -f "$MAPPED_BLIF" "$OUT_DIR/topologymapping/${design}.mapped.blif"
  rm -rf "$TMP_SYN_DIR"

  # ---------- Stap 3: JSON-provenance (LUT ↔ AIG leaves) ----------
  # Waarom dit werkt: jouw export_lut_provenance.sh verwacht (--blif mapped.blif) + (--aag pre_of_post.aag) + (--design).
  # Het schrijft standaard naar logicSynthesis/results/Provenance, dus we forceren OUT_DIR naar het design,
  # en hernoemen de 'Provenance' submap naar 'JsonMapping' (of kopiëren de bestanden).
  echo "[3/4] Export LUT-provenance JSON …"
  export OUT_DIR="$OUT_DIR"  # overschrijft default in het script naar dit design
  PROV_LOG="$LOGS_DIR/${design}.prov.log"
  "$PROV_SCRIPT" \
      --blif "$OUT_DIR/topologymapping/${design}.mapped.blif" \
      --aag  "$PRE_AAG" \
      --design "$design" \
      >"$PROV_LOG" 2>&1

  # Het script schreef naar $OUT_DIR/Provenance/<design>.lut_to_aig_leaves.json (+ CSV’s)
  if [ -d "$OUT_DIR/Provenance" ]; then
    # Verplaats .json en .csv naar jouw JsonMapping/
    shopt -s nullglob
    for f in "$OUT_DIR/Provenance/${design}.lut_to_aig_leaves."{json,lut_nodes.csv,pi_counts.csv}; do
      [ -e "$f" ] && mv -f "$f" "$OUT_DIR/JsonMapping/"
    done
    rmdir "$OUT_DIR/Provenance" 2>/dev/null || true
  fi

  # ---------- Stap 4: Eindsamenvatting ----------
  echo "[4/4] Klaar voor $design"
  echo "  Elaboration    : $ELAB_DIR"
  echo "  LogicSynthesis : $OUT_DIR/LogicSynthesis"
  echo "  TopologyMapping: $OUT_DIR/topologymapping"
  echo "  JsonMapping    : $OUT_DIR/JsonMapping"
  echo "  Logs           : $LOGS_DIR"
done
