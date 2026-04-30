#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Config
# ============================================================
BUILD_DIR="${BUILD_DIR:-$HOME/Masterproef/multisynthesis/logicSynthesis/tools/mockturtle/build}"

MT_INNER_WINDOW="$BUILD_DIR/mt_inner_window"
MT_EXTRACT_CARE_VARS="$BUILD_DIR/mt_extract_care_vars"
MT_CONSTRUCT_CARE_MITTER="$BUILD_DIR/mt_construct_care_mitter"
MT_RANDOM_CARE_SIM="$BUILD_DIR/mt_random_care_sim"
MT_CHECK_COMPLETE_CARE="$BUILD_DIR/mt_check_complete_care"

MT_EXTRACT_CANDIDATE_DIVISORS="$BUILD_DIR/mt_extract_candidate_divisors"
MT_CHECK_CANDIDATE_DIVISORS="$BUILD_DIR/mt_check_candidate_divisors"

MT_BUILD_COMPLETE_CARE_JSON="$BUILD_DIR/mt_build_complete_care_json"
MT_EXTRACT_RESUB_CANDIDATES="$BUILD_DIR/mt_extract_resub_candidates"
MT_CHECK_RESUB_FEASIBLE_FULL_SAT="$BUILD_DIR/mt_check_resub_feasible_Full_Sat"

MT_DERIVE_DEPENDENCY_FUNCTION="$BUILD_DIR/mt_derive_dependency_function"

MT_APPLY_DEPENDENCY_FUNCTION="$BUILD_DIR/mt_apply_dependency_function"

RANDOM_PATTERNS="${RANDOM_PATTERNS:-5000}"
RANDOM_SEED="${RANDOM_SEED:-12345}"
MAX_DIVISORS="${MAX_DIVISORS:-100}"
K_MAX="${K_MAX:-3}" # Standaard subset grootte voor resub candidates

# ============================================================
# Helpers
# ============================================================
usage() {
  cat <<EOF
Usage:
  $0 --case-dir <dir> --pivot <node> \
     --inner-tfi <n> --inner-tfo <n> \
     --outer-tfi <n> --outer-tfo <n>

Example:
  $0 --case-dir ~/Masterproef/multisynthesis/results/example_big_300 \
     --pivot 120 \
     --inner-tfi 3 --inner-tfo 3 \
     --outer-tfi 5 --outer-tfo 5
EOF
}

require_file() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo "ERROR: required file not found: $f" >&2
    exit 10
  fi
}

require_exec() {
  local f="$1"
  if [[ ! -x "$f" ]]; then
    echo "ERROR: required executable not found or not executable: $f" >&2
    exit 11
  fi
}

log() {
  echo "[INFO] $*"
}

run_and_log() {
  local log_file="$1"
  shift
  echo "[CMD] $*" | tee "$log_file"
  "$@" 2>&1 | tee -a "$log_file"
}

# ============================================================
# Parse args
# ============================================================
CASE_DIR=""
PIVOT=""
INNER_TFI=""
INNER_TFO=""
OUTER_TFI=""
OUTER_TFO=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --case-dir)
      CASE_DIR="$2"
      shift 2
      ;;
    --pivot)
      PIVOT="$2"
      shift 2
      ;;
    --inner-tfi)
      INNER_TFI="$2"
      shift 2
      ;;
    --inner-tfo)
      INNER_TFO="$2"
      shift 2
      ;;
    --outer-tfi)
      OUTER_TFI="$2"
      shift 2
      ;;
    --outer-tfo)
      OUTER_TFO="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$CASE_DIR" || -z "$PIVOT" || -z "$INNER_TFI" || -z "$INNER_TFO" || -z "$OUTER_TFI" || -z "$OUTER_TFO" ]]; then
  echo "ERROR: missing required arguments" >&2
  usage
  exit 1
fi

CASE_DIR="$(realpath "$CASE_DIR")"
CASE_NAME="$(basename "$CASE_DIR")"

# ============================================================
# Input paths
# ============================================================
AIG_PATH="$CASE_DIR/LogicSynthesis/Aig/${CASE_NAME}.clean.postopt.aig"

# ============================================================
# Output structure
# ============================================================
OUT_ROOT="$CASE_DIR/Sat_Resynthesis/pivot_${PIVOT}"
WINDOW_DIR="$OUT_ROOT/Window"
CARESET_DIR="$OUT_ROOT/CareSet"
DIVISOR_DIR="$OUT_ROOT/NodeDivisor"
LOG_DIR="$OUT_ROOT/Logs"

mkdir -p "$WINDOW_DIR" "$CARESET_DIR" "$DIVISOR_DIR" "$LOG_DIR"


INNER_JSON="$WINDOW_DIR/inner_window_${INNER_TFI}_${INNER_TFO}.json"
OUTER_JSON="$WINDOW_DIR/outer_window_${OUTER_TFI}_${OUTER_TFO}.json"

CARE_VARS_JSON="$CARESET_DIR/care_vars_${PIVOT}.json"
CARE_MITTER_AIG="$CARESET_DIR/care_mitter_${PIVOT}.aig"
CARE_MITTER_JSON="$CARESET_DIR/care_mitter_${PIVOT}.json"
F1_JSON="$CARESET_DIR/f1_random_${PIVOT}.json"
COMPLETE_CARE_META_JSON="$CARESET_DIR/complete_care_meta_${PIVOT}.json"
CANDIDATE_DIVISORS_JSON="$DIVISOR_DIR/candidate_divisors_${PIVOT}.json"
COMPLETE_CARE_JSON="$CARESET_DIR/complete_care_${PIVOT}.json"

#RESUB_CANDS_JSON="$RESUB_DIR/resub_candidates_${PIVOT}.json"
#FEASIBILITY_REPORT_JSON="$RESUB_DIR/feasibility_report_${PIVOT}.json"


RESUB_CANDS_STUB="$DIVISOR_DIR/resub_candidates_stub_${PIVOT}V2.json"
# We gebruiken 118 119 als voorbeeld voor de outputnaam
RESUB_FEASIBLE_FIG="$DIVISOR_DIR/resub_feasible_fig44_${PIVOT}_118_119.json"
# ============================================================
# Checks
# ============================================================
[[ -d "$CASE_DIR" ]] || { echo "ERROR: case-dir not found: $CASE_DIR" >&2; exit 2; }

require_file "$AIG_PATH"

require_exec "$MT_INNER_WINDOW"
require_exec "$MT_EXTRACT_CARE_VARS"
require_exec "$MT_CONSTRUCT_CARE_MITTER"
require_exec "$MT_RANDOM_CARE_SIM"
require_exec "$MT_CHECK_COMPLETE_CARE"
require_exec "$MT_EXTRACT_CANDIDATE_DIVISORS"
require_exec "$MT_CHECK_CANDIDATE_DIVISORS"
require_exec "$MT_BUILD_COMPLETE_CARE_JSON"
require_exec "$MT_EXTRACT_RESUB_CANDIDATES"
require_exec "$MT_CHECK_RESUB_FEASIBLE_FULL_SAT"
require_exec "$MT_APPLY_DEPENDENCY_FUNCTION"

# ============================================================
# Summary
# ============================================================
log "Case directory: $CASE_DIR"
log "Case name:      $CASE_NAME"
log "Pivot:          $PIVOT"
log "Inner window:   tfi=$INNER_TFI tfo=$INNER_TFO"
log "Outer window:   tfi=$OUTER_TFI tfo=$OUTER_TFO"
log "AIG:            $AIG_PATH"
log "Output root:    $OUT_ROOT"

# ============================================================
# Step 1: inner window
# ============================================================
log "Running inner window..."
run_and_log "$LOG_DIR/01_inner_window.log" \
  "$MT_INNER_WINDOW" \
  "$AIG_PATH" \
  "$PIVOT" \
  "$INNER_TFI" \
  "$INNER_TFO" \
  "$INNER_JSON"

# ============================================================
# Step 2: outer window
# ============================================================
log "Running outer window..."
run_and_log "$LOG_DIR/02_outer_window.log" \
  "$MT_INNER_WINDOW" \
  "$AIG_PATH" \
  "$PIVOT" \
  "$OUTER_TFI" \
  "$OUTER_TFO" \
  "$OUTER_JSON"

# ============================================================
# Step 3: care vars
# ============================================================
log "Extracting care vars..."
run_and_log "$LOG_DIR/03_extract_care_vars.log" \
  "$MT_EXTRACT_CARE_VARS" \
  "$AIG_PATH" \
  "$INNER_JSON" \
  "$OUTER_JSON" \
  "$CARE_VARS_JSON"

# ============================================================
# Step 4: care miter
# ============================================================
log "Constructing care miter..."
run_and_log "$LOG_DIR/04_construct_care_mitter.log" \
  "$MT_CONSTRUCT_CARE_MITTER" \
  "$AIG_PATH" \
  "$INNER_JSON" \
  "$OUTER_JSON" \
  "$CARE_VARS_JSON" \
  "$CARE_MITTER_AIG" \
  "$CARE_MITTER_JSON"

# ============================================================
# Step 5: random simulation
# ============================================================
log "Running random simulation..."
run_and_log "$LOG_DIR/05_random_care_sim.log" \
  "$MT_RANDOM_CARE_SIM" \
  "$AIG_PATH" \
  "$OUTER_JSON" \
  "$CARE_VARS_JSON" \
  "$RANDOM_PATTERNS" \
  "$RANDOM_SEED" \
  "$F1_JSON"

# ============================================================
# Step 6: complete care via SAT
# ============================================================
log "Running complete care SAT enumeration..."
run_and_log "$LOG_DIR/06_complete_care.log" \
  "$MT_CHECK_COMPLETE_CARE" \
  "$AIG_PATH" \
  "$OUTER_JSON" \
  "$CARE_VARS_JSON" \
  "$F1_JSON" \
  "$COMPLETE_CARE_META_JSON"

# ============================================================
# Step 7: Extract candidate divisors
# ============================================================
log "Extracting candidate divisors to NodeDivisor/..."
run_and_log "$LOG_DIR/07_extract_divisors.log" \
  "$MT_EXTRACT_CANDIDATE_DIVISORS" \
  "$AIG_PATH" \
  "$INNER_JSON" \
  "$CARE_VARS_JSON" \
  "$CANDIDATE_DIVISORS_JSON" \
  "$MAX_DIVISORS"

# ============================================================
# Step 8: Check candidate divisors
# ============================================================
log "Verifying candidate divisors consistency..."
run_and_log "$LOG_DIR/08_check_divisors.log" \
  "$MT_CHECK_CANDIDATE_DIVISORS" \
  "$AIG_PATH" \
  "$INNER_JSON" \
  "$CARE_VARS_JSON" \
  "$CANDIDATE_DIVISORS_JSON"


# ============================================================
# Step 6.5: Build merged complete care JSON
# ============================================================
log "Merging simulation and SAT care sets..."
run_and_log "$LOG_DIR/06b_build_complete_care_json.log" \
  "$MT_BUILD_COMPLETE_CARE_JSON" \
  "$F1_JSON" \
  "$COMPLETE_CARE_META_JSON" \
  "$COMPLETE_CARE_JSON"

# ============================================================
# Step 9: Extract resub candidates (Dynamisch met K_MAX)
# ============================================================
log "Extracting resub candidates (K_MAX=$K_MAX)..."
RESUB_CANDS_JSON="$DIVISOR_DIR/resub_candidates_pivot_${PIVOT}_k${K_MAX}.json"

run_and_log "$LOG_DIR/09_extract_resub_candidates.log" \
  "$MT_EXTRACT_RESUB_CANDIDATES" \
  "$AIG_PATH" \
  "$INNER_JSON" \
  "$CARE_VARS_JSON" \
  "$CANDIDATE_DIVISORS_JSON" \
  "$COMPLETE_CARE_JSON" \
  "$RESUB_CANDS_JSON" \
  "$K_MAX"

# ============================================================
# Loop over alle surviving candidate sets (Gecorrigeerd voor Object-structuur)
# ============================================================
# We halen specifiek de .divisors array uit elk object in de lijst
mapfile -t RAW_SETS < <(jq -c '.surviving_candidate_sets[].divisors' "$RESUB_CANDS_JSON")

SETS_COUNT=${#RAW_SETS[@]}

if [[ "$SETS_COUNT" -eq 0 ]]; then
    log "WARNING: No surviving candidate sets found for pivot $PIVOT."
else
    log "Found $SETS_COUNT surviving candidate sets. Starting sweep..."

    for (( i=0; i<$SETS_COUNT; i++ )); do
        # Pak de i-de set (dit is nu een schone array zoals [118,119])
        ROW="${RAW_SETS[$i]}"
        
        # 1. Maak de lijst voor de tool-input: [118,119] -> 118 119
        CURRENT_SET=$(echo "$ROW" | tr -d '[]' | tr ',' ' ')
        
        # 2. Maak de string voor bestandsnamen: 118 119 -> 118_119
        # De xargs verwijdert eventuele extra spaties
        SET_STR=$(echo "$CURRENT_SET" | xargs | tr ' ' '_')
        
        log "--- Processing Set $((i+1))/$SETS_COUNT: [$CURRENT_SET] ---"

        # Step 10: SAT Feasibility
        FEASIBLE_JSON="$DIVISOR_DIR/resub_feasible_fig44_p${PIVOT}_s${SET_STR}.json"
        run_and_log "$LOG_DIR/10_check_feasible_s${SET_STR}.log" \
          "$MT_CHECK_RESUB_FEASIBLE_FULL_SAT" \
          "$AIG_PATH" "$INNER_JSON" "$CARE_VARS_JSON" "$CANDIDATE_DIVISORS_JSON" \
          "$COMPLETE_CARE_JSON" "$FEASIBLE_JSON" $CURRENT_SET

        # Step 11: Dependency Function
        DEP_FUNC_JSON="$DIVISOR_DIR/dependency_function_p${PIVOT}_s${SET_STR}.json"
        run_and_log "$LOG_DIR/11_derive_dependency_s${SET_STR}.log" \
          "$MT_DERIVE_DEPENDENCY_FUNCTION" \
          "$AIG_PATH" "$INNER_JSON" "$CARE_VARS_JSON" "$CANDIDATE_DIVISORS_JSON" \
          "$COMPLETE_CARE_JSON" "$DEP_FUNC_JSON" $CURRENT_SET

        # Step 12: Apply Substitution
        REWRITTEN_AIG="$DIVISOR_DIR/${CASE_NAME}.pivot${PIVOT}.set_${SET_STR}.rewritten.aig"
        run_and_log "$LOG_DIR/12_apply_dependency_s${SET_STR}.log" \
          "$MT_APPLY_DEPENDENCY_FUNCTION" \
          "$AIG_PATH" "$DEP_FUNC_JSON" "$REWRITTEN_AIG"

        log "Finished processing set [$CURRENT_SET]. Result: $REWRITTEN_AIG"
    done
fi

log "Done."
log "Outputs written under: $OUT_ROOT"
