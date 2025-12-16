	#!/usr/bin/env bash
set -euo pipefail

# === Config ===
MPROOT="${MPROOT:-$HOME/Masterproef/multisynthesis}"
PAR_ROOT="$MPROOT/placeAndRoute"
SCRIPTS_DIR="$PAR_ROOT/scripts"

# Args
ARCH_XML=""
BLIF_IN=""
CIRCUIT=""
NPATHS="${NPATHS:-200}"
CHANW="${CHANW:-100}"

# Graphics control (defaults)
DISP="${DISP:-off}"             # valid: on/off
SAVE_GRAPHICS="${SAVE_GRAPHICS:-off}"  # valid: on/off

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch)    ARCH_XML="$(realpath -m "$2")"; shift 2;;
    --blif)    BLIF_IN="$(realpath -m "$2")"; shift 2;;
    --circuit) CIRCUIT="$2"; shift 2;;
    --npaths)  NPATHS="$2"; shift 2;;
    --chanw)   CHANW="$2"; shift 2;;
    -h|--help)
      echo "Gebruik: $0 --arch arch.xml --blif circuit.blif --circuit NAME [--npaths N] [--chanw W]"
      exit 0;;
    *) echo "Onbekend arg: $1" >&2; exit 1;;
  esac
done

[[ -z "$ARCH_XML" || -z "$BLIF_IN" || -z "$CIRCUIT" ]] && { echo "Vereist: --arch --blif --circuit"; exit 1; }
[[ ! -f "$ARCH_XML" ]] && { echo "Arch niet gevonden: $ARCH_XML"; exit 1; }
[[ ! -f "$BLIF_IN"  ]] && { echo "BLIF niet gevonden: $BLIF_IN"; exit 1; }



# Binaries


# Binaries
VPR_BIN="${VPR_BIN:-$(command -v vpr || true)}"

# Als vpr niet in PATH zit, probeer de lokale build onder Masterproef
if [[ -z "${VPR_BIN:-}" ]]; then
  CAND="$HOME/Masterproef/vtr-verilog-to-routing/vpr/vpr"
  if [[ -x "$CAND" ]]; then
    VPR_BIN="$CAND"
  fi
fi

[[ -x "${VPR_BIN:-}" ]] || { echo "vpr niet gevonden (zet VPR_BIN of PATH of pas CAND-pad aan in PlacementRouting.sh)"; exit 1; }




# Afleidingen
ARCH_TAG="$(basename "$ARCH_XML" .xml)"
BUILD_DIR="$PAR_ROOT/results/build_vpr/$ARCH_TAG/$CIRCUIT"
LOG_DIR="$PAR_ROOT/logs/$ARCH_TAG/$CIRCUIT"
mkdir -p "$BUILD_DIR" "$LOG_DIR"

echo "[Stap3] Run VPR pack/place (no routing)"
pushd "$BUILD_DIR" >/dev/null

# VPR: alleen pack + place, geen routing, geen analysis
"$VPR_BIN" "$ARCH_XML" "$BLIF_IN" \
  --pack --place \
  --route_chan_width "$CHANW" \
  --echo_file on \
  --timing_report_detail debug \
  --disp "$DISP" \
  --save_graphics "$SAVE_GRAPHICS" \
  2>&1 | tee "$LOG_DIR/vpr_${CIRCUIT}.log"

echo
echo "Klaar met pack + place in: $BUILD_DIR"
echo "Belangrijkste files:"
echo " - ${CIRCUIT}.net   (clustered netlist)"
echo " - ${CIRCUIT}.place (placement, met coords)"
echo " - vpr_${CIRCUIT}.log (bevat 'Placement estimated critical path delay ...')"

popd >/dev/null
