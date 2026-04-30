#!/usr/bin/env bash
set -euo pipefail

# ------------------------
# Usage
# ------------------------
DESIGN_ROOT="${1:-}"
if [[ -z "$DESIGN_ROOT" ]]; then
  echo "Usage: $0 <DESIGN_ROOT>"
  echo "Example: $0 ~/Masterproef/multisynthesis/results/example_big_300"
  exit 1
fi

DESIGN_ROOT="$(realpath -m "$DESIGN_ROOT")"

# ------------------------
# Params (override via env)
# ------------------------
DEPTH="${DEPTH:-3}"            # step3 depth
CUTMODE="${CUTMODE:-cp}"       # "cp" or "nocp"
INDEX="${INDEX:-0}"            # feasible index from step1_report.json
SEED="${SEED:-1}"              # step5
MAX_ITERS="${MAX_ITERS:-200}"  # step5
SELF_CHECK="${SELF_CHECK:-0}"  # step4 selfcheck: 1 enables

# Optional: limit step5 runtime (seconds). 0 = no timeout.
STEP5_TIMEOUT_S="${STEP5_TIMEOUT_S:-0}"

# ------------------------
# Repo paths
# ------------------------
SAT_REPO_ROOT="$(realpath -m "$(dirname "$0")")"
TONY_ROOT="$(realpath -m "$SAT_REPO_ROOT/..")"  # multisynthesis root

STEP1_PY="$TONY_ROOT/SAT/Sat/Sat_Stap1/fanout/script/stap1_fanout_Json.py"
STEP2_PY="$TONY_ROOT/SAT/Sat/Sat_Stap2/scripts/apply_rewire_patch.py"
STEP3_PY="$TONY_ROOT/SAT/Sat/Sat_Stap3/scripts/build_patch_window.py"
STEP4_PY="$TONY_ROOT/tony_sat/core/super_to_cnf_step4.py"
STEP5_PY="$TONY_ROOT/tony_sat/core/solve_patch_tt_step5_global_cegar.py"

# ------------------------
# SUPER_JSON (hardcoded, but overridable)
# ------------------------
SUPER_JSON_DEFAULT="/home/cian/Masterproef/multisynthesis/Lut_verbinding/result/example_big_300/example_big_300.super.sat.v2.json"
SUPER_JSON="${SUPER_JSON:-$SUPER_JSON_DEFAULT}"
SUPER_JSON="$(realpath -m "$SUPER_JSON")"

if [[ ! -f "$SUPER_JSON" ]]; then
  echo "[ERROR] SUPER_JSON not found: $SUPER_JSON"
  exit 2
fi

# Ensure Python can import tony_sat.*
export PYTHONPATH="$TONY_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# ------------------------
# Output dirs under DESIGN_ROOT
# ------------------------
SAT_DIR="$DESIGN_ROOT/Sat"
S1="$SAT_DIR/Sat_Stap1/fanout/result"
S2="$SAT_DIR/Sat_Stap2/results"

S3_VARIANT="$SAT_DIR/Sat_Stap3/results_depth${DEPTH}_${CUTMODE}"
S4_VARIANT="$SAT_DIR/Sat_Stap4/results_depth${DEPTH}_${CUTMODE}"
S5_RES="$SAT_DIR/Sat_Stap5/results"

mkdir -p "$S1" "$S2" "$S3_VARIANT" "$S4_VARIANT" "$S5_RES"

# ------------------------
# Helper: run with logging
# ------------------------
run_logged() {
  local logfile="$1"; shift
  echo ">>> $*" | tee -a "$logfile"
  "$@" 2>&1 | tee -a "$logfile"
}

echo "[INFO] DESIGN_ROOT  = $DESIGN_ROOT"
echo "[INFO] SUPER_JSON   = $SUPER_JSON"
echo "[INFO] DEPTH        = $DEPTH"
echo "[INFO] CUTMODE      = $CUTMODE"
echo "[INFO] INDEX        = $INDEX"
echo "[INFO] SEED         = $SEED"
echo "[INFO] MAX_ITERS    = $MAX_ITERS"
echo "[INFO] SELF_CHECK   = $SELF_CHECK"
echo "[INFO] PYTHONPATH   = $PYTHONPATH"
echo ""

# =========================================================
# STEP 1
# =========================================================
LOG1="$SAT_DIR/Sat_Stap1/run_step1.log"
: > "$LOG1"
[[ -f "$STEP1_PY" ]] || { echo "[ERROR] Missing $STEP1_PY"; exit 3; }

run_logged "$LOG1" python3 "$STEP1_PY" \
  --super "$SUPER_JSON" \
  --outdir "$S1"

FANOUT_JSON="$S1/fanout.json"
STEP1_REPORT="$S1/step1_report.json"
[[ -f "$FANOUT_JSON" && -f "$STEP1_REPORT" ]] || { echo "[ERROR] Step1 outputs missing"; exit 4; }

# =========================================================
# STEP 2
# =========================================================
LOG2="$SAT_DIR/Sat_Stap2/run_step2.log"
: > "$LOG2"
[[ -f "$STEP2_PY" ]] || { echo "[ERROR] Missing $STEP2_PY"; exit 5; }

run_logged "$LOG2" python3 "$STEP2_PY" \
  --super "$SUPER_JSON" \
  --step1 "$STEP1_REPORT" \
  --index "$INDEX" \
  --outdir "$S2"

PATCH_JSON="$S2/patch_feasible${INDEX}.json"
TARGET_SUPER="$S2/target_feasible${INDEX}.super.sat.v2.json"
[[ -f "$PATCH_JSON" && -f "$TARGET_SUPER" ]] || { echo "[ERROR] Step2 outputs missing"; exit 6; }

# =========================================================
# STEP 3
# =========================================================
LOG3="$SAT_DIR/Sat_Stap3/run_step3.log"
: > "$LOG3"
[[ -f "$STEP3_PY" ]] || { echo "[ERROR] Missing $STEP3_PY"; exit 7; }

run_logged "$LOG3" python3 "$STEP3_PY" \
  --target "$TARGET_SUPER" \
  --fanout "$FANOUT_JSON" \
  --outdir "$S3_VARIANT" \
  --depth "$DEPTH"

WINDOW_CP_JSON="$S3_VARIANT/patch_window_feasible0.json"
[[ -f "$WINDOW_CP_JSON" ]] || { echo "[ERROR] Step3 output missing: $WINDOW_CP_JSON"; exit 8; }

WINDOW_JSON="$WINDOW_CP_JSON"
if [[ "$CUTMODE" == "nocp" ]]; then
  WINDOW_NOCP_JSON="$S3_VARIANT/patch_window_feasible0_nocp.json"
  python3 - "$WINDOW_CP_JSON" "$WINDOW_NOCP_JSON" <<'PY'
import json,sys
inp, outp = sys.argv[1], sys.argv[2]
j = json.load(open(inp))

patch = set(j.get("PATCH_LUTS") or [])
cut = set(j.get("CUTPOINT_NETS") or [])

# nocp semantics:
# - keep CUTPOINT_NETS (needed for miter)
# - allow patching them too
j["PATCH_LUTS"] = sorted(patch | cut)

with open(outp, "w") as f:
    json.dump(j, f, indent=2)

print("[OK] Wrote nocp window:", outp)
print("  PATCH_LUTS:", len(j["PATCH_LUTS"]))
print("  CUTPOINT_NETS:", len(j["CUTPOINT_NETS"]))
PY
  WINDOW_JSON="$WINDOW_NOCP_JSON"
fi

# =========================================================
# STEP 4
# =========================================================
LOG4="$SAT_DIR/Sat_Stap4/run_step4.log"
: > "$LOG4"
[[ -f "$STEP4_PY" ]] || { echo "[ERROR] Missing $STEP4_PY"; exit 9; }

if [[ "$SELF_CHECK" == "1" ]]; then
  run_logged "$LOG4" python3 "$STEP4_PY" \
    --spec "$SUPER_JSON" \
    --target "$TARGET_SUPER" \
    --window "$WINDOW_JSON" \
    --outdir "$S4_VARIANT" \
    --selfcheck
else
  run_logged "$LOG4" python3 "$STEP4_PY" \
    --spec "$SUPER_JSON" \
    --target "$TARGET_SUPER" \
    --window "$WINDOW_JSON" \
    --outdir "$S4_VARIANT"
fi

CNFJSON="$S4_VARIANT/spec_target.cnf.json"
[[ -f "$CNFJSON" ]] || { echo "[ERROR] Step4 output missing: $CNFJSON"; exit 10; }

# =========================================================
# STEP 5
# =========================================================
LOG5="$SAT_DIR/Sat_Stap5/run_step5.log"
: > "$LOG5"
[[ -f "$STEP5_PY" ]] || { echo "[ERROR] Missing $STEP5_PY"; exit 11; }

OUT_TT="$S5_RES/patch_tt_feasible${INDEX}.global_cegar.json"

STEP5_CMD=(python3 "$STEP5_PY" --cnfjson "$CNFJSON" --out "$OUT_TT" --max-iters "$MAX_ITERS" --seed "$SEED" --verbose)

if [[ "$STEP5_TIMEOUT_S" != "0" ]] && command -v timeout >/dev/null 2>&1; then
  run_logged "$LOG5" timeout "$STEP5_TIMEOUT_S" "${STEP5_CMD[@]}"
else
  run_logged "$LOG5" "${STEP5_CMD[@]}"
fi

echo ""
echo "[DONE] SAT flow completed."
echo "  Step1 out: $S1"
echo "  Step2 out: $S2"
echo "  Step3 out: $S3_VARIANT"
echo "  Step4 out: $S4_VARIANT"
echo "  Step5 out: $OUT_TT"
