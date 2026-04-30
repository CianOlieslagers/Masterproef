#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# run_sat_sweep.sh
#
# Doel:
#   - Run dezelfde SAT flow (stap1..5) voor oplopende window depth
#   - Log per depth: window stats + cnf stats + step5 status
#   - NIET “stoppen” op SAT-A UNSAT (dat is window-afhankelijk)
#   - Wel stoppen als je zelf wil via STOP_ON_* flags
#
# Gebruik:
#   ./run_sat_sweep.sh <DESIGN_ROOT>
#   vb: ./run_sat_sweep.sh ~/Masterproef/multisynthesis/results/example_big_300
#
# Env overrides:
#   INDEX=0
#   CUTMODE=cp            # cp of nocp
#   DEPTH_MIN=1
#   DEPTH_MAX=6
#   SEED=1
#   MAX_ITERS=200
#   STEP5_TIMEOUT=900     # seconds, 0 = geen timeout
#   STOP_ON_FOUND_SAT=0   # 1 = stop als step5 “SAT/FOUND” detecteert (indien je solver dat logt)
#   STOP_ON_SAT_A_UNSAT=0 # 1 = stop als SAT-A UNSAT (meestal: “window te klein of infeasible”)
# ============================================================

DESIGN_ROOT="${1:-}"
if [[ -z "$DESIGN_ROOT" ]]; then
  echo "Usage: $0 <DESIGN_ROOT>"
  echo "Example: $0 ~/Masterproef/multisynthesis/results/example_big_300"
  exit 1
fi
DESIGN_ROOT="$(realpath -m "$DESIGN_ROOT")"

INDEX="${INDEX:-0}"
CUTMODE="${CUTMODE:-cp}"
DEPTH_MIN="${DEPTH_MIN:-1}"
DEPTH_MAX="${DEPTH_MAX:-6}"

SEED="${SEED:-1}"
MAX_ITERS="${MAX_ITERS:-200}"
STEP5_TIMEOUT="${STEP5_TIMEOUT:-0}"

STOP_ON_FOUND_SAT="${STOP_ON_FOUND_SAT:-0}"
STOP_ON_SAT_A_UNSAT="${STOP_ON_SAT_A_UNSAT:-0}"

SCRIPT_DIR="$(realpath -m "$(dirname "$0")")"

# Deze wrapper script verwacht dat run_sat_flow.sh in dezelfde map zit.
FLOW="$SCRIPT_DIR/run_sat_flow.sh"
if [[ ! -x "$FLOW" ]]; then
  echo "[ERROR] Missing or not executable: $FLOW"
  exit 2
fi

SAT_DIR="$DESIGN_ROOT/Sat"
mkdir -p "$SAT_DIR"

OUT_JSONL="$SAT_DIR/sweep_results_depth${DEPTH_MIN}_to_${DEPTH_MAX}_${CUTMODE}_idx${INDEX}.jsonl"
OUT_SUMMARY="$SAT_DIR/sweep_summary_depth${DEPTH_MIN}_to_${DEPTH_MAX}_${CUTMODE}_idx${INDEX}.json"

echo "[INFO] DESIGN_ROOT=$DESIGN_ROOT"
echo "[INFO] INDEX=$INDEX CUTMODE=$CUTMODE DEPTH_MIN=$DEPTH_MIN DEPTH_MAX=$DEPTH_MAX"
echo "[INFO] SEED=$SEED MAX_ITERS=$MAX_ITERS STEP5_TIMEOUT=$STEP5_TIMEOUT"
echo "[INFO] Writing:"
echo "  - $OUT_JSONL"
echo "  - $OUT_SUMMARY"
echo ""

: > "$OUT_JSONL"

# ------------------------------------------------------------
# Helper: maak tony_sat import betrouwbaar (ModuleNotFoundError fix)
#   - super_to_cnf_step4.py gebruikt: from tony_sat.core...
#   - dus PYTHONPATH moet $TONY_ROOT bevatten
# ------------------------------------------------------------
TONY_ROOT="$(realpath -m "$SCRIPT_DIR/..")"
export PYTHONPATH="$TONY_ROOT:${PYTHONPATH:-}"

# ------------------------------------------------------------
# Helper: classify step5 run via log parsing
# ------------------------------------------------------------
classify_step5_log() {
  local log="$1"
  if [[ ! -f "$log" ]]; then
    echo "NO_LOG"
    return
  fi

  # 1) Klassieke stopboodschap uit jouw solver:
  if grep -q "\[RESULT\] UNSAT in SAT-A" "$log"; then
    echo "SAT_A_UNSAT"
    return
  fi

  # 2) Soms zie je expliciet UNSAT / SAT in andere vorm
  if grep -q "\[RESULT\].*UNSAT" "$log"; then
    echo "UNSAT_OTHER"
    return
  fi
  if grep -q "\[RESULT\].*SAT" "$log"; then
    echo "SAT_OTHER"
    return
  fi

  # 3) Timeouts / interrupts herkenning (optioneel)
  if grep -qi "timeout" "$log"; then
    echo "TIMEOUT"
    return
  fi
  if grep -qi "keyboard interrupt" "$log"; then
    echo "INTERRUPTED"
    return
  fi

  echo "UNKNOWN"
}

# ------------------------------------------------------------
# Helper: extract window & cnf stats (robust, geen JSONDecodeError)
# ------------------------------------------------------------
emit_stats_json() {
  local depth="$1"
  local cutmode="$2"
  local index="$3"

  python3 - "$DESIGN_ROOT" "$depth" "$cutmode" "$index" <<'PY'
import json, sys, os
from pathlib import Path

design_root = Path(sys.argv[1])
depth = int(sys.argv[2])
cutmode = sys.argv[3]
index = int(sys.argv[4])

sat_dir = design_root / "Sat"
win_json = sat_dir / "Sat_Stap3" / f"results_depth{depth}_{cutmode}" / "patch_window_feasible0.json"
cnf_json = sat_dir / "Sat_Stap4" / f"results_depth{depth}_{cutmode}" / "spec_target.cnf.json"
log5 = sat_dir / "Sat_Stap5" / "run_step5.log"

def safe_load(p: Path):
    try:
        if not p.exists(): return None
        if p.stat().st_size == 0: return None
        return json.loads(p.read_text())
    except Exception:
        return None

w = safe_load(win_json)
c = safe_load(cnf_json)

out = {
  "design_root": str(design_root),
  "index": index,
  "depth": depth,
  "cutmode": cutmode,
  "paths": {
    "window_json": str(win_json),
    "cnf_json": str(cnf_json),
    "step5_log": str(log5),
  },
  "window": None,
  "cnf": None,
}

if w is not None:
    out["window"] = {
        "patch_luts_n": len(w.get("PATCH_LUTS") or []),
        "cutpoints_n": len(w.get("CUTPOINT_NETS") or []),
    }

if c is not None:
    name2var = c.get("name2var") or {}
    out["cnf"] = {
        "exists": True,
        "vars": c.get("vars"),
        "clauses": c.get("clauses"),
        "diff_or_var": c.get("diff_or_var"),
        "solver": c.get("solver"),
        "patch_luts_n": len(c.get("patch_luts") or []),
        "cutpoints_n": len(c.get("cutpoints") or []),
        "tt_count": sum(1 for k in name2var if k.startswith("TT__")),
    }
else:
    out["cnf"] = {"exists": False}

print(json.dumps(out, indent=2))
PY
}

# ------------------------------------------------------------
# Main sweep loop
# ------------------------------------------------------------
results_tmp="$(mktemp)"

for (( d=DEPTH_MIN; d<=DEPTH_MAX; d++ )); do
  echo "============================================================"
  echo "[SWEEP] DEPTH=$d CUTMODE=$CUTMODE INDEX=$INDEX"
  echo "============================================================"

  # timeout rond de hele flow (meestal step5 die hangt)
  if [[ "$STEP5_TIMEOUT" != "0" ]]; then
    # Let op: timeout is voor volledige run_sat_flow.sh
    # (simpel en betrouwbaar; als je liever enkel step5 timet, zeg het)
    if ! timeout "${STEP5_TIMEOUT}s" env \
        DEPTH="$d" CUTMODE="$CUTMODE" INDEX="$INDEX" SEED="$SEED" MAX_ITERS="$MAX_ITERS" \
        "$FLOW" "$DESIGN_ROOT"; then
      echo "[WARN] run_sat_flow failed/timed out at depth=$d (continuing)"
    fi
  else
    if ! env DEPTH="$d" CUTMODE="$CUTMODE" INDEX="$INDEX" SEED="$SEED" MAX_ITERS="$MAX_ITERS" \
        "$FLOW" "$DESIGN_ROOT"; then
      echo "[WARN] run_sat_flow failed at depth=$d (continuing)"
    fi
  fi

  # Classify via step5 log (altijd dezelfde path)
  log5="$SAT_DIR/Sat_Stap5/run_step5.log"
  status="$(classify_step5_log "$log5")"

  # Emit stats JSON + status, append to jsonl
  stats="$(emit_stats_json "$d" "$CUTMODE" "$INDEX")"
  merged="$(python3 - <<PY
import json
s = json.loads("""$stats""")
s["status"] = "$status"
print(json.dumps(s))
PY
)"
  echo "$merged" >> "$OUT_JSONL"
  echo "$merged" >> "$results_tmp"

  echo "[STATUS] depth=$d -> $status"

  # Stopregels (optioneel)
  if [[ "$STOP_ON_SAT_A_UNSAT" == "1" && "$status" == "SAT_A_UNSAT" ]]; then
    echo "[STOP] STOP_ON_SAT_A_UNSAT=1 en status=SAT_A_UNSAT."
    break
  fi
  if [[ "$STOP_ON_FOUND_SAT" == "1" && "$status" == "SAT_OTHER" ]]; then
    echo "[STOP] STOP_ON_FOUND_SAT=1 en status=SAT_OTHER."
    break
  fi

done

# ------------------------------------------------------------
# Write a compact summary
# ------------------------------------------------------------
python3 - "$results_tmp" "$OUT_SUMMARY" <<'PY'
import json, sys
from pathlib import Path

inp = Path(sys.argv[1])
outp = Path(sys.argv[2])

rows = []
for line in inp.read_text().splitlines():
    if not line.strip():
        continue
    rows.append(json.loads(line))

summary = {
  "runs": len(rows),
  "by_depth": [],
}

for r in rows:
    summary["by_depth"].append({
      "depth": r.get("depth"),
      "status": r.get("status"),
      "window": r.get("window"),
      "cnf": r.get("cnf"),
    })

outp.write_text(json.dumps(summary, indent=2))
print("[OK] Wrote summary:", outp)
PY

rm -f "$results_tmp"

echo ""
echo "[DONE] Sweep klaar."
echo "  Results (jsonl): $OUT_JSONL"
echo "  Summary  (json): $OUT_SUMMARY"
