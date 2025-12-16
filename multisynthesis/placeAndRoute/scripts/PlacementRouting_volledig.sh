cian@MSI:~/Masterproef/multisynthesis/placeAndRoute/scripts$ cat PlacementRouting.sh
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

echo "[Stap3] Run VPR pack/place/route"
pushd "$BUILD_DIR" >/dev/null


# ... net boven de VPR run, na pushd en vóór "$VPR_BIN" ...
TD="${TIMING_DETAIL:-detailed}"                 # fallback = detailed
TD="${TD//[$'\t\r\n ']/}"                       # alle whitespace strippen
[[ -z "$TD" ]] && TD="detailed"                 # leeg? opnieuw 'detailed'


# VPR run (timing + echos + post-synth netlist)
"$VPR_BIN" "$ARCH_XML" "$BLIF_IN" \
  --pack --place --route \
  --route_chan_width "$CHANW" \
  --analysis --echo_file on \
  --timing_report_detail "$TD" \
  --timing_report_npaths "$NPATHS" \
  --gen_post_synthesis_netlist on \
  --disp "$DISP" \
  --save_graphics "$SAVE_GRAPHICS" \
  2>&1 | tee "$LOG_DIR/vpr_${CIRCUIT}.log"

# Kies beste beschikbare setup-report (post-route is voorkeur)
RPT=""
for cand in \
  "report_timing.setup.rpt" \
  "report_unconstrained_timing.setup.rpt" \
  "pre_pack.report_timing.setup.rpt"
do
  if [[ -s "$cand" ]]; then RPT="$cand"; break; fi
done

if [[ -z "$RPT" ]]; then
  echo "⚠  Geen timing report gevonden in $BUILD_DIR" >&2
  ls -1 *.rpt || true
  popd >/dev/null
  exit 2
fi


echo "[Stap3] Zoek bruikbaar timing report in: $BUILD_DIR"

# Submap voor top-N paden
PATH_DIR="$BUILD_DIR/top_paths"

PY="${PYTHON:-python3}"
set +e
PARSE_OUT=$("$PY" "$SCRIPTS_DIR/parse_vtr_timing.py" \
  --searchdir "$BUILD_DIR" \
  --outdir "$PATH_DIR" \
  --npaths "$NPATHS" 2>&1)
PARSE_RC=$?
set -e


if [[ $PARSE_RC -ne 0 ]]; then
  echo "$PARSE_OUT" >&2
  echo "⚠  Geen paden gevonden. Controleer of VPR met '--analysis --timing_report_detail netlist' draaide of bekijk *.rpt in $BUILD_DIR." >&2
  exit 3
else
  echo "$PARSE_OUT"
fi

echo
echo "Klaar. Belangrijkste outputs in: $BUILD_DIR"
echo " - $CIRCUIT.place / .route / .net"
echo " - report_timing.*.rpt (gekozen file staat vermeld in parser-output)"
echo " - top-N paden: $PATH_DIR/report_top_paths.csv"
echo " - net-ranglijst: $PATH_DIR/trace_selected_nets.csv | .txt | .json"
echo " - (echo's) atom_netlist.*.echo.blif, clusters.echo, timing_graph.*.echo*"
