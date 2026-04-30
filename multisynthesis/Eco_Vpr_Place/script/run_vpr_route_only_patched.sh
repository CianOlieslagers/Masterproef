#!/usr/bin/env bash
set -euo pipefail

DESIGN="${1:-example_big_300}"

RESULTS_ROOT="${RESULTS_ROOT:-$HOME/Masterproef/multisynthesis/results}"
ARCH_XML="${ARCH_XML:-$HOME/Masterproef/vtr-verilog-to-routing/vtr_flow/arch/custom/markus_k4.xml}"

VPR_BIN="${VPR_BIN:-$(command -v vpr || true)}"
if [[ -z "$VPR_BIN" ]]; then
  CAND="$HOME/Masterproef/vtr-verilog-to-routing/vpr/vpr"
  if [[ ! -x "$CAND" ]]; then
    echo "ERROR: vpr niet gevonden. Zet VPR_BIN expliciet." >&2
    exit 1
  fi
  VPR_BIN="$CAND"
fi

ECO_ROOT="$RESULTS_ROOT/$DESIGN/PlaceAndRoute/06_eco_lut_insertion"

BLIF="$ECO_ROOT/phase2_patch_blif/patched.blif"
NET="$ECO_ROOT/phase3_patch_net/patched.net"
PLACE="$ECO_ROOT/phase4_patch_place/patched.place"

OUT_DIR="$ECO_ROOT/phase6_route_patched"
mkdir -p "$OUT_DIR"

ROUTE="$OUT_DIR/patched.route"
LOG="$OUT_DIR/patched.route_only.log"

[[ -s "$BLIF" ]] || { echo "ERROR: ontbreekt: $BLIF" >&2; exit 1; }
[[ -s "$NET" ]] || { echo "ERROR: ontbreekt: $NET" >&2; exit 1; }
[[ -s "$PLACE" ]] || { echo "ERROR: ontbreekt: $PLACE" >&2; exit 1; }
[[ -s "$ARCH_XML" ]] || { echo "ERROR: ontbreekt: $ARCH_XML" >&2; exit 1; }

echo "[INFO] VPR_BIN  = $VPR_BIN"
echo "[INFO] ARCH_XML = $ARCH_XML"
echo "[INFO] BLIF     = $BLIF"
echo "[INFO] NET      = $NET"
echo "[INFO] PLACE    = $PLACE"
echo "[INFO] ROUTE    = $ROUTE"
echo "[INFO] LOG      = $LOG"

cd "$OUT_DIR"

"$VPR_BIN" "$ARCH_XML" "$BLIF" \
  --route \
  --net_file "$NET" \
  --place_file "$PLACE" \
  --route_file "$ROUTE" \
  --route_chan_width 100 \
  --echo_file on \
  > "$LOG" 2>&1

[[ -s "$ROUTE" ]] || {
  echo "ERROR: VPR heeft geen route file geschreven: $ROUTE" >&2
  echo "Zie log: $LOG" >&2
  exit 1
}

echo "[OK] Route-only patched ECO gelukt."
echo "[OK] Route file: $ROUTE"
echo "[OK] Log file  : $LOG"

echo
echo "[INFO] Snelle log-check:"
grep -Ei "Packer:|Placer:|Router:|Load packing|Load Placement|Routing|Successfully routed|routing consistency|error|failed|mismatch|Fixed" "$LOG" | tail -120 || true
