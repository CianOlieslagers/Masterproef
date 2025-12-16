#!/usr/bin/env bash
set -euo pipefail

PR_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) PR_DIR="$(realpath -m "$2")"; shift 2;;
    -h|--help)
      echo "Gebruik: $0 --dir PAD/NAAR/PlaceAndRoute"
      exit 0;;
    *)
      echo "Onbekend argument: $1" >&2
      exit 1;;
  esac
done

if [[ -z "${PR_DIR:-}" ]]; then
  echo "Fout: geen --dir opgegeven" >&2
  exit 1
fi

if [[ ! -d "$PR_DIR" ]]; then
  echo "Fout: directory bestaat niet: $PR_DIR" >&2
  exit 1
fi

cd "$PR_DIR"

# Submappen
LOC_DIR="01_location"
TIM_DIR="02_paths_timing"
ROU_DIR="03_routing"
ARC_DIR="04_architecture"
CUS_DIR="05_custom_outputs"

mkdir -p "$LOC_DIR" "$TIM_DIR" "$ROU_DIR" "$ARC_DIR" "$CUS_DIR"

# Helper om veilig globs te moven
move_glob() {
  local dest="$1"; shift
  shopt -s nullglob
  local files=( "$@" )
  shopt -u nullglob
  (( ${#files[@]} )) || return 0
  mv -f "${files[@]}" "$dest" 2>/dev/null
}

###############
# 1) LOCATION #
###############
move_glob "$LOC_DIR" \
  *.mapped.place \
  *.mapped.net \
  *.mapped.net.post_routing \
  clusters.echo \
  clustering_block_criticalities.echo \
  track_to_pin_map.echo

#####################
# 2) PATHS & TIMING #
#####################
move_glob "$TIM_DIR" \
  report_timing*.rpt \
  report_unconstrained_timing*.rpt \
  pre_pack.report_timing.setup.rpt \
  timing_graph*.echo \
  timing_graph*.dot

# Als er een top_paths map is, verplaats die naar custom outputs (eigen parser-output)
if [[ -d "top_paths" ]]; then
  mv -f "top_paths" "$CUS_DIR/"
fi

################
# 3) ROUTING   #
################
move_glob "$ROU_DIR" \
  *.mapped.route \
  chan_details.txt \
  chanx_occupancy.txt \
  chany_occupancy.txt \
  rr_indexed_data.echo \
  lb_type_rr_graph.echo \
  sblock_pattern.txt \
  packing_pin_util.rpt

#####################
# 4) ARCHITECTURE   #
#####################
move_glob "$ARC_DIR" \
  arch.echo \
  pb_graph.echo \
  place_macros.echo

#####################
# 5) CUSTOM OUTPUTS #
#####################
# Eigen parser-output die soms in de root kan staan
move_glob "$CUS_DIR" \
  trace_selected_nets.txt \
  trace_selected_nets.csv \
  trace_selected_nets.json \
  report_top_paths.csv \
  vpr_stdout.log

# Klaar
echo "VPR-outputs geordend in:"
echo "  $PR_DIR/$LOC_DIR"
echo "  $PR_DIR/$TIM_DIR"
echo "  $PR_DIR/$ROU_DIR"
echo "  $PR_DIR/$ARC_DIR"
echo "  $PR_DIR/$CUS_DIR"
