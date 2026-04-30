#!/usr/bin/env bash

# ============================================================
# Robust sweep runner for SAT-based resynthesis experiments
# - Keeps existing scripts untouched
# - Explores window configs first, then pivots
# - Logs every step per window/pivot/set
# - Continues after errors
# - Writes per-run summaries and a global summary JSONL
# ============================================================

# NOTE:
# This script intentionally does NOT use `set -euo pipefail`
# because the goal is dataset generation with fault isolation,
# not fail-fast behaviour.

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
MT_AIG_EQUIV="$BUILD_DIR/mt_aig_equiv"

RANDOM_PATTERNS="${RANDOM_PATTERNS:-5000}"
RANDOM_SEED="${RANDOM_SEED:-12345}"
MAX_DIVISORS="${MAX_DIVISORS:-100}"
K_MAX="${K_MAX:-3}"

# Window configs are specified as comma-separated quadruples:
#   inner_tfi:inner_tfo:outer_tfi:outer_tfo
WINDOW_CONFIGS="${WINDOW_CONFIGS:-3:3:5:5,4:4:6:6}"

# Pivot source:
#   1) --pivots-file <file>  (one pivot per line)
#   2) --pivots "120 121 122"
# If neither is given, script exits with a clear error.
PIVOTS_FILE=""
PIVOTS_STR=""

# If 1, only feasible sets proceed to dependency/apply/equiv.
ONLY_FEASIBLE="${ONLY_FEASIBLE:-1}"

# If 1, apply rewrite for feasible+consistent sets.
RUN_APPLY="${RUN_APPLY:-1}"

# If 1, run mt_aig_equiv after rewrite.
RUN_EQUIV="${RUN_EQUIV:-1}"

# ============================================================
# Helpers
# ============================================================
usage() {
  cat <<EOF
Usage:
  $0 --case-dir <dir> [--pivots-file <file> | --pivots "120 121 122"]

Environment variables:
  BUILD_DIR         Path to mockturtle build dir
  RANDOM_PATTERNS   Default: 5000
  RANDOM_SEED       Default: 12345
  MAX_DIVISORS      Default: 100
  K_MAX             Default: 3
  WINDOW_CONFIGS    Default: 3:3:5:5,4:4:6:6
                    Format: inner_tfi:inner_tfo:outer_tfi:outer_tfo,...
  ONLY_FEASIBLE     Default: 1
  RUN_APPLY         Default: 1
  RUN_EQUIV         Default: 1

Examples:
  WINDOW_CONFIGS="2:2:4:4,3:3:5:5" \
  $0 --case-dir ~/Masterproef/multisynthesis/results/example_big_300 \
     --pivots "120 121 122"

  $0 --case-dir ~/Masterproef/multisynthesis/results/example_big_300 \
     --pivots-file ./pivot_list.txt
EOF
}

log() {
  echo "[INFO] $*"
}

warn() {
  echo "[WARN] $*" >&2
}

err() {
  echo "[ERROR] $*" >&2
}

require_file() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    err "required file not found: $f"
    return 1
  fi
  return 0
}

require_exec() {
  local f="$1"
  if [[ ! -x "$f" ]]; then
    err "required executable not found or not executable: $f"
    return 1
  fi
  return 0
}

require_cmd() {
  local c="$1"
  command -v "$c" >/dev/null 2>&1 || {
    err "required command not found in PATH: $c"
    return 1
  }
  return 0
}

json_escape() {
  python3 - <<'PY' "$1"
import json, sys
print(json.dumps(sys.argv[1]))
PY
}

join_by() {
  local delim="$1"
  shift
  local first=1
  for x in "$@"; do
    if [[ $first -eq 1 ]]; then
      printf "%s" "$x"
      first=0
    else
      printf "%s%s" "$delim" "$x"
    fi
  done
}

run_and_log() {
  local log_file="$1"
  shift
  mkdir -p "$(dirname "$log_file")"
  {
    echo "[CMD] $*"
    "$@"
  } >"$log_file" 2>&1
  local rc=$?
  echo "$rc"
  return 0
}

read_pivots() {
  local pivots=()

  if [[ -n "$PIVOTS_FILE" ]]; then
    if [[ ! -f "$PIVOTS_FILE" ]]; then
      err "pivots file not found: $PIVOTS_FILE"
      return 1
    fi
    while IFS= read -r line; do
      line="${line%%#*}"
      line="$(echo "$line" | xargs)"
      [[ -z "$line" ]] && continue
      pivots+=("$line")
    done < "$PIVOTS_FILE"
  elif [[ -n "$PIVOTS_STR" ]]; then
    # shellcheck disable=SC2206
    pivots=( $PIVOTS_STR )
  else
    err "no pivots provided. Use --pivots-file or --pivots"
    return 1
  fi

  if [[ ${#pivots[@]} -eq 0 ]]; then
    err "pivot list is empty"
    return 1
  fi

  printf '%s\n' "${pivots[@]}"
  return 0
}

append_jsonl() {
  local file="$1"
  local line="$2"
  echo "$line" >> "$file"
}

extract_json_bool() {
  local file="$1"
  local query="$2"
  jq -r "$query // false" "$file" 2>/dev/null
}

extract_json_int() {
  local file="$1"
  local query="$2"
  jq -r "$query // 0" "$file" 2>/dev/null
}

# ============================================================
# Parse args
# ============================================================
CASE_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --case-dir)
      CASE_DIR="$2"
      shift 2
      ;;
    --pivots-file)
      PIVOTS_FILE="$2"
      shift 2
      ;;
    --pivots)
      PIVOTS_STR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      err "unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$CASE_DIR" ]]; then
  err "missing required argument: --case-dir"
  usage
  exit 1
fi

CASE_DIR="$(realpath "$CASE_DIR")"
CASE_NAME="$(basename "$CASE_DIR")"
AIG_PATH="$CASE_DIR/LogicSynthesis/Aig/${CASE_NAME}.clean.postopt.aig"
BASE_OUT="$CASE_DIR/Sat_Resynthesis"
SWEEP_ROOT="$BASE_OUT/Sweep"
RUN_ID="run_$(date +%Y%m%d_%H%M%S)"
RUN_ROOT="$SWEEP_ROOT/$RUN_ID"
GLOBAL_LOG_DIR="$RUN_ROOT/Logs"
GLOBAL_SUMMARY_JSONL="$RUN_ROOT/global_summary.jsonl"
GLOBAL_SUMMARY_CSV="$RUN_ROOT/global_summary.csv"
RUN_META_JSON="$RUN_ROOT/run_metadata.json"

mkdir -p "$RUN_ROOT" "$GLOBAL_LOG_DIR"

# ============================================================
# Checks
# ============================================================
require_cmd jq || exit 1
require_cmd python3 || exit 1
require_file "$AIG_PATH" || exit 1

require_exec "$MT_INNER_WINDOW" || exit 1
require_exec "$MT_EXTRACT_CARE_VARS" || exit 1
require_exec "$MT_CONSTRUCT_CARE_MITTER" || exit 1
require_exec "$MT_RANDOM_CARE_SIM" || exit 1
require_exec "$MT_CHECK_COMPLETE_CARE" || exit 1
require_exec "$MT_EXTRACT_CANDIDATE_DIVISORS" || exit 1
require_exec "$MT_CHECK_CANDIDATE_DIVISORS" || exit 1
require_exec "$MT_BUILD_COMPLETE_CARE_JSON" || exit 1
require_exec "$MT_EXTRACT_RESUB_CANDIDATES" || exit 1
require_exec "$MT_CHECK_RESUB_FEASIBLE_FULL_SAT" || exit 1
require_exec "$MT_DERIVE_DEPENDENCY_FUNCTION" || exit 1
require_exec "$MT_APPLY_DEPENDENCY_FUNCTION" || exit 1
require_exec "$MT_AIG_EQUIV" || exit 1

mapfile -t PIVOTS < <(read_pivots)
if [[ $? -ne 0 ]]; then
  exit 1
fi

IFS=',' read -r -a CONFIGS <<< "$WINDOW_CONFIGS"
if [[ ${#CONFIGS[@]} -eq 0 ]]; then
  err "WINDOW_CONFIGS is empty"
  exit 1
fi

# ============================================================
# Metadata and global summary headers
# ============================================================
cat > "$RUN_META_JSON" <<EOF
{
  "case_dir": $(json_escape "$CASE_DIR"),
  "case_name": $(json_escape "$CASE_NAME"),
  "aig_path": $(json_escape "$AIG_PATH"),
  "run_root": $(json_escape "$RUN_ROOT"),
  "window_configs": $(printf '%s\n' "${CONFIGS[@]}" | jq -R . | jq -s .),
  "pivots": $(printf '%s\n' "${PIVOTS[@]}" | jq -R . | jq -s 'map(tonumber?)'),
  "random_patterns": $RANDOM_PATTERNS,
  "random_seed": $RANDOM_SEED,
  "max_divisors": $MAX_DIVISORS,
  "k_max": $K_MAX,
  "only_feasible": $ONLY_FEASIBLE,
  "run_apply": $RUN_APPLY,
  "run_equiv": $RUN_EQUIV
}
EOF

echo "window_key,pivot,status,surviving_count,feasible_count,dependency_success_count,rewrite_success_count,equiv_success_count,window_dir,pivot_dir" > "$GLOBAL_SUMMARY_CSV"
: > "$GLOBAL_SUMMARY_JSONL"

log "Case directory: $CASE_DIR"
log "Case name:      $CASE_NAME"
log "AIG:            $AIG_PATH"
log "Sweep root:     $RUN_ROOT"
log "Window configs: $(join_by ', ' "${CONFIGS[@]}")"
log "Pivot count:    ${#PIVOTS[@]}"

# ============================================================
# Main loop: window configs first, then pivots
# ============================================================
for cfg in "${CONFIGS[@]}"; do
  IFS=':' read -r INNER_TFI INNER_TFO OUTER_TFI OUTER_TFO <<< "$cfg"

  if [[ -z "$INNER_TFI" || -z "$INNER_TFO" || -z "$OUTER_TFI" || -z "$OUTER_TFO" ]]; then
    warn "Skipping malformed window config: $cfg"
    continue
  fi

  WINDOW_KEY="i${INNER_TFI}_${INNER_TFO}__o${OUTER_TFI}_${OUTER_TFO}"
  WINDOW_ROOT="$RUN_ROOT/$WINDOW_KEY"
  WINDOW_LOG_DIR="$WINDOW_ROOT/Logs"
  mkdir -p "$WINDOW_ROOT" "$WINDOW_LOG_DIR"

  log "=== Window config: $WINDOW_KEY ==="

  for PIVOT in "${PIVOTS[@]}"; do
    PIVOT_ROOT="$WINDOW_ROOT/pivot_${PIVOT}"
    WINDOW_DIR="$PIVOT_ROOT/Window"
    CARESET_DIR="$PIVOT_ROOT/CareSet"
    DIVISOR_DIR="$PIVOT_ROOT/NodeDivisor"
    LOG_DIR="$PIVOT_ROOT/Logs"
    SUMMARY_JSON="$PIVOT_ROOT/summary.json"
    mkdir -p "$WINDOW_DIR" "$CARESET_DIR" "$DIVISOR_DIR" "$LOG_DIR"

    INNER_JSON="$WINDOW_DIR/inner_window_${INNER_TFI}_${INNER_TFO}.json"
    OUTER_JSON="$WINDOW_DIR/outer_window_${OUTER_TFI}_${OUTER_TFO}.json"
    CARE_VARS_JSON="$CARESET_DIR/care_vars_${PIVOT}.json"
    CARE_MITTER_AIG="$CARESET_DIR/care_mitter_${PIVOT}.aig"
    CARE_MITTER_JSON="$CARESET_DIR/care_mitter_${PIVOT}.json"
    F1_JSON="$CARESET_DIR/f1_random_${PIVOT}.json"
    COMPLETE_CARE_META_JSON="$CARESET_DIR/complete_care_meta_${PIVOT}.json"
    COMPLETE_CARE_JSON="$CARESET_DIR/complete_care_${PIVOT}.json"
    CANDIDATE_DIVISORS_JSON="$DIVISOR_DIR/candidate_divisors_${PIVOT}.json"
    RESUB_CANDS_JSON="$DIVISOR_DIR/resub_candidates_pivot_${PIVOT}_k${K_MAX}.json"
    SET_SUMMARY_JSONL="$DIVISOR_DIR/set_summary.jsonl"
    : > "$SET_SUMMARY_JSONL"

    log "--- Pivot: $PIVOT under $WINDOW_KEY ---"

    step_fail=0
    surviving_count=0
    feasible_count=0
    dependency_success_count=0
    rewrite_success_count=0
    equiv_success_count=0
    overall_status="success"

    # ------------------------------
    # Step 1: inner window
    # ------------------------------
    rc=$(run_and_log "$LOG_DIR/01_inner_window.log" \
      "$MT_INNER_WINDOW" "$AIG_PATH" "$PIVOT" "$INNER_TFI" "$INNER_TFO" "$INNER_JSON")
    if [[ "$rc" -ne 0 ]]; then
      overall_status="inner_window_failed"
      step_fail=1
    fi

    # ------------------------------
    # Step 2: outer window
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      rc=$(run_and_log "$LOG_DIR/02_outer_window.log" \
        "$MT_INNER_WINDOW" "$AIG_PATH" "$PIVOT" "$OUTER_TFI" "$OUTER_TFO" "$OUTER_JSON")
      if [[ "$rc" -ne 0 ]]; then
        overall_status="outer_window_failed"
        step_fail=1
      fi
    fi

    # ------------------------------
    # Step 3: care vars
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      rc=$(run_and_log "$LOG_DIR/03_extract_care_vars.log" \
        "$MT_EXTRACT_CARE_VARS" "$AIG_PATH" "$INNER_JSON" "$OUTER_JSON" "$CARE_VARS_JSON")
      if [[ "$rc" -ne 0 ]]; then
        overall_status="extract_care_vars_failed"
        step_fail=1
      fi
    fi

    # ------------------------------
    # Step 4: care miter
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      rc=$(run_and_log "$LOG_DIR/04_construct_care_mitter.log" \
        "$MT_CONSTRUCT_CARE_MITTER" "$AIG_PATH" "$INNER_JSON" "$OUTER_JSON" "$CARE_VARS_JSON" "$CARE_MITTER_AIG" "$CARE_MITTER_JSON")
      if [[ "$rc" -ne 0 ]]; then
        overall_status="construct_care_miter_failed"
        step_fail=1
      fi
    fi

    # ------------------------------
    # Step 5: random simulation
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      rc=$(run_and_log "$LOG_DIR/05_random_care_sim.log" \
        "$MT_RANDOM_CARE_SIM" "$AIG_PATH" "$OUTER_JSON" "$CARE_VARS_JSON" "$RANDOM_PATTERNS" "$RANDOM_SEED" "$F1_JSON")
      if [[ "$rc" -ne 0 ]]; then
        overall_status="random_care_sim_failed"
        step_fail=1
      fi
    fi

    # ------------------------------
    # Step 6: complete care SAT
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      rc=$(run_and_log "$LOG_DIR/06_complete_care.log" \
        "$MT_CHECK_COMPLETE_CARE" "$AIG_PATH" "$OUTER_JSON" "$CARE_VARS_JSON" "$F1_JSON" "$COMPLETE_CARE_META_JSON")
      if [[ "$rc" -ne 0 ]]; then
        overall_status="complete_care_failed"
        step_fail=1
      fi
    fi

    # ------------------------------
    # Step 6b: merge complete care
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      rc=$(run_and_log "$LOG_DIR/06b_build_complete_care_json.log" \
        "$MT_BUILD_COMPLETE_CARE_JSON" "$F1_JSON" "$COMPLETE_CARE_META_JSON" "$COMPLETE_CARE_JSON")
      if [[ "$rc" -ne 0 ]]; then
        overall_status="merge_complete_care_failed"
        step_fail=1
      fi
    fi

    # ------------------------------
    # Step 7: candidate divisors
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      rc=$(run_and_log "$LOG_DIR/07_extract_divisors.log" \
        "$MT_EXTRACT_CANDIDATE_DIVISORS" "$AIG_PATH" "$INNER_JSON" "$CARE_VARS_JSON" "$CANDIDATE_DIVISORS_JSON" "$MAX_DIVISORS")
      if [[ "$rc" -ne 0 ]]; then
        overall_status="extract_divisors_failed"
        step_fail=1
      fi
    fi

    # ------------------------------
    # Step 8: divisor check
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      rc=$(run_and_log "$LOG_DIR/08_check_divisors.log" \
        "$MT_CHECK_CANDIDATE_DIVISORS" "$AIG_PATH" "$INNER_JSON" "$CARE_VARS_JSON" "$CANDIDATE_DIVISORS_JSON")
      if [[ "$rc" -ne 0 ]]; then
        overall_status="check_divisors_failed"
        step_fail=1
      fi
    fi

    # ------------------------------
    # Step 9: extract resub candidates
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      rc=$(run_and_log "$LOG_DIR/09_extract_resub_candidates.log" \
        "$MT_EXTRACT_RESUB_CANDIDATES" "$AIG_PATH" "$INNER_JSON" "$CARE_VARS_JSON" "$CANDIDATE_DIVISORS_JSON" "$COMPLETE_CARE_JSON" "$RESUB_CANDS_JSON" "$K_MAX")
      if [[ "$rc" -ne 0 ]]; then
        overall_status="extract_resub_candidates_failed"
        step_fail=1
      fi
    fi

    # ------------------------------
    # Step 10-12: loop over surviving candidate sets
    # ------------------------------
    if [[ $step_fail -eq 0 ]]; then
      mapfile -t RAW_SETS < <(jq -c '.surviving_candidate_sets[].divisors' "$RESUB_CANDS_JSON" 2>/dev/null)
      surviving_count=${#RAW_SETS[@]}

      if [[ "$surviving_count" -eq 0 ]]; then
        overall_status="no_surviving_sets"
      else
        for (( i=0; i<surviving_count; i++ )); do
          ROW="${RAW_SETS[$i]}"
          CURRENT_SET=$(echo "$ROW" | tr -d '[]' | tr ',' ' ' | xargs)
          SET_STR=$(echo "$CURRENT_SET" | tr ' ' '_')

          FEASIBLE_JSON="$DIVISOR_DIR/resub_feasible_fig44_p${PIVOT}_s${SET_STR}.json"
          DEP_FUNC_JSON="$DIVISOR_DIR/dependency_function_p${PIVOT}_s${SET_STR}.json"
          REWRITTEN_AIG="$DIVISOR_DIR/${CASE_NAME}.pivot${PIVOT}.set_${SET_STR}.rewritten.aig"
          EQUIV_LOG="$LOG_DIR/13_equiv_s${SET_STR}.log"

          feasible_rc=$(run_and_log "$LOG_DIR/10_check_feasible_s${SET_STR}.log" \
            "$MT_CHECK_RESUB_FEASIBLE_FULL_SAT" "$AIG_PATH" "$INNER_JSON" "$CARE_VARS_JSON" "$CANDIDATE_DIVISORS_JSON" "$COMPLETE_CARE_JSON" "$FEASIBLE_JSON" $CURRENT_SET)

          feasible="false"
          if [[ "$feasible_rc" -eq 0 && -f "$FEASIBLE_JSON" ]]; then
            feasible=$(extract_json_bool "$FEASIBLE_JSON" '.feasible')
          fi

          dependency_attempted="false"
          dependency_ok="false"
          dep_rc=-1
          consistent="false"

          rewrite_attempted="false"
          rewrite_ok="false"
          apply_rc=-1

          equiv_attempted="false"
          equiv_ok="false"
          equiv_rc=-1

          if [[ "$feasible" == "true" ]]; then
            feasible_count=$((feasible_count + 1))
          fi

          if [[ "$ONLY_FEASIBLE" -eq 0 || "$feasible" == "true" ]]; then
            dependency_attempted="true"
            dep_rc=$(run_and_log "$LOG_DIR/11_derive_dependency_s${SET_STR}.log" \
              "$MT_DERIVE_DEPENDENCY_FUNCTION" "$AIG_PATH" "$INNER_JSON" "$CARE_VARS_JSON" "$CANDIDATE_DIVISORS_JSON" "$COMPLETE_CARE_JSON" "$DEP_FUNC_JSON" $CURRENT_SET)

            if [[ "$dep_rc" -eq 0 && -f "$DEP_FUNC_JSON" ]]; then
              consistent=$(extract_json_bool "$DEP_FUNC_JSON" '.consistent')
              if [[ "$consistent" == "true" ]]; then
                dependency_ok="true"
                dependency_success_count=$((dependency_success_count + 1))
              fi
            fi

            if [[ "$RUN_APPLY" -eq 1 && "$dependency_ok" == "true" ]]; then
              rewrite_attempted="true"
              apply_rc=$(run_and_log "$LOG_DIR/12_apply_dependency_s${SET_STR}.log" \
                "$MT_APPLY_DEPENDENCY_FUNCTION" "$AIG_PATH" "$DEP_FUNC_JSON" "$REWRITTEN_AIG")
              if [[ "$apply_rc" -eq 0 && -f "$REWRITTEN_AIG" ]]; then
                rewrite_ok="true"
                rewrite_success_count=$((rewrite_success_count + 1))
              fi

              if [[ "$RUN_EQUIV" -eq 1 && "$rewrite_ok" == "true" ]]; then
                equiv_attempted="true"
                equiv_rc=$(run_and_log "$EQUIV_LOG" \
                  "$MT_AIG_EQUIV" "$AIG_PATH" "$REWRITTEN_AIG")
                if [[ "$equiv_rc" -eq 0 ]]; then
                  if grep -q "AIGs are EQUIVALENT" "$EQUIV_LOG"; then
                    equiv_ok="true"
                    equiv_success_count=$((equiv_success_count + 1))
                  fi
                fi
              fi
            fi
          fi

          append_jsonl "$SET_SUMMARY_JSONL" "{\"pivot\":$PIVOT,\"window_key\":$(json_escape "$WINDOW_KEY"),\"set_index\":$i,\"set\":[$(echo "$CURRENT_SET" | tr ' ' ',' )],\"feasible_rc\":$feasible_rc,\"feasible\":$feasible,\"dependency_attempted\":$dependency_attempted,\"dependency_rc\":$dep_rc,\"consistent\":$consistent,\"dependency_ok\":$dependency_ok,\"rewrite_attempted\":$rewrite_attempted,\"apply_rc\":$apply_rc,\"rewrite_ok\":$rewrite_ok,\"equiv_attempted\":$equiv_attempted,\"equiv_rc\":$equiv_rc,\"equiv_ok\":$equiv_ok,\"feasible_json\":$(json_escape "$FEASIBLE_JSON"),\"dependency_json\":$(json_escape "$DEP_FUNC_JSON"),\"rewritten_aig\":$(json_escape "$REWRITTEN_AIG")}"
        done
      fi
    fi

    cat > "$SUMMARY_JSON" <<EOF
{
  "case_name": $(json_escape "$CASE_NAME"),
  "aig_path": $(json_escape "$AIG_PATH"),
  "window_key": $(json_escape "$WINDOW_KEY"),
  "inner": {"tfi": $INNER_TFI, "tfo": $INNER_TFO},
  "outer": {"tfi": $OUTER_TFI, "tfo": $OUTER_TFO},
  "pivot": $PIVOT,
  "status": $(json_escape "$overall_status"),
  "surviving_count": $surviving_count,
  "feasible_count": $feasible_count,
  "dependency_success_count": $dependency_success_count,
  "rewrite_success_count": $rewrite_success_count,
  "equiv_success_count": $equiv_success_count,
  "paths": {
    "pivot_root": $(json_escape "$PIVOT_ROOT"),
    "window_dir": $(json_escape "$WINDOW_DIR"),
    "careset_dir": $(json_escape "$CARESET_DIR"),
    "divisor_dir": $(json_escape "$DIVISOR_DIR"),
    "log_dir": $(json_escape "$LOG_DIR"),
    "set_summary_jsonl": $(json_escape "$SET_SUMMARY_JSONL")
  }
}
EOF

    append_jsonl "$GLOBAL_SUMMARY_JSONL" "{\"window_key\":$(json_escape "$WINDOW_KEY"),\"pivot\":$PIVOT,\"status\":$(json_escape "$overall_status"),\"surviving_count\":$surviving_count,\"feasible_count\":$feasible_count,\"dependency_success_count\":$dependency_success_count,\"rewrite_success_count\":$rewrite_success_count,\"equiv_success_count\":$equiv_success_count,\"window_dir\":$(json_escape "$WINDOW_ROOT"),\"pivot_dir\":$(json_escape "$PIVOT_ROOT")}" 

    echo "$WINDOW_KEY,$PIVOT,$overall_status,$surviving_count,$feasible_count,$dependency_success_count,$rewrite_success_count,$equiv_success_count,$WINDOW_ROOT,$PIVOT_ROOT" >> "$GLOBAL_SUMMARY_CSV"
  done
done

log "Sweep complete."
log "Run root:         $RUN_ROOT"
log "Global summary:   $GLOBAL_SUMMARY_JSONL"
log "Global summary:   $GLOBAL_SUMMARY_CSV"
