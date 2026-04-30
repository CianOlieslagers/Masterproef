#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from typing import Any, Dict, Optional

RE_UNSAT_SAT_A = re.compile(r"\[RESULT\]\s+UNSAT in SAT-A", re.IGNORECASE)
RE_UNSAT_GENERIC = re.compile(r"\bUNSAT\b", re.IGNORECASE)
RE_SAT_A_UNSAT_LINE = re.compile(r"\[SAT-A\]\s+UNSAT", re.IGNORECASE)
RE_MAX_ITERS = re.compile(r"Max iterations reached", re.IGNORECASE)
RE_KEYBOARDINT = re.compile(r"keyboard interrupt", re.IGNORECASE)

def load_json(p: Path) -> Any:
    return json.loads(p.read_text())

def parse_status(step5_log: str) -> str:
    # Strong signals first
    if RE_UNSAT_SAT_A.search(step5_log) or RE_SAT_A_UNSAT_LINE.search(step5_log):
        return "CLASSIFIED_UNSAT_SAT_A"
    if RE_MAX_ITERS.search(step5_log):
        return "MAX_ITERS"
    if RE_KEYBOARDINT.search(step5_log):
        return "INTERRUPTED"
    # If it contains SAT-A SAT-B lines but no final, it’s incomplete/timeout-ish
    if "[ITER" in step5_log and "SAT-A" in step5_log and "SAT-B" in step5_log:
        return "INCOMPLETE"
    return "UNKNOWN"

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--design-root", required=True)
    ap.add_argument("--depth", type=int, required=True)
    ap.add_argument("--cutmode", required=True)
    ap.add_argument("--index", type=int, required=True)
    args = ap.parse_args()

    design_root = Path(args.design_root).expanduser().resolve()

    step3_dir = design_root / "Sat" / "Sat_Stap3" / f"results_depth{args.depth}_{args.cutmode}"
    step4_dir = design_root / "Sat" / "Sat_Stap4" / f"results_depth{args.depth}_{args.cutmode}"
    step5_log_path = design_root / "Sat" / "Sat_Stap5" / "run_step5.log"

    window_json = step3_dir / "patch_window_feasible0.json"
    window_nocp_json = step3_dir / "patch_window_feasible0_nocp.json"
    cnf_json = step4_dir / "spec_target.cnf.json"

    # Window info
    win: Dict[str, Any] = {}
    if window_json.exists():
        win = load_json(window_json)

    patch_luts = win.get("PATCH_LUTS") or []
    cutpoints = win.get("CUTPOINT_NETS") or []

    # CNF info
    cnf: Dict[str, Any] = {}
    if cnf_json.exists():
        cnf = load_json(cnf_json)

    # Step5 log
    log_txt = step5_log_path.read_text(errors="replace") if step5_log_path.exists() else ""
    status = parse_status(log_txt)

    out = {
        "design_root": str(design_root),
        "index": args.index,
        "depth": args.depth,
        "cutmode": args.cutmode,
        "status": status,
        "window": {
            "patch_luts_n": len(patch_luts),
            "cutpoints_n": len(cutpoints),
            "patch_luts_path": str(window_nocp_json if args.cutmode == "nocp" else window_json),
        },
        "cnf": {
            "exists": cnf_json.exists(),
            "vars": cnf.get("vars"),
            "clauses": cnf.get("clauses"),
            "tt_count": sum(1 for k in (cnf.get("name2var") or {}) if str(k).startswith("TT__")),
            "patch_luts_n": len(cnf.get("patch_luts") or []),
            "cutpoints_n": len(cnf.get("cutpoints") or []),
        },
        "paths": {
            "step5_log": str(step5_log_path),
            "window_json": str(window_json),
            "cnf_json": str(cnf_json),
        },
    }

    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
