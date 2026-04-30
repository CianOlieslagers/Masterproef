#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os
from pathlib import Path
from typing import Any, Dict, List
from pysat.solvers import Solver

def load(p: str) -> Any:
    return json.loads(Path(os.path.expanduser(p)).read_text())

def bits_to_hex16(bits_lsb_first: List[int]) -> str:
    val = 0
    for i,b in enumerate(bits_lsb_first):
        val |= (int(b) & 1) << i
    return f"{val:04x}"

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cnfjson", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    J = load(args.cnfjson)
    name2var: Dict[str,int] = J["name2var"]
    cnf = J["clauses_dimacs"]
    diff = int(J["diff_or_var"])
    solver_name = J.get("solver","glucose4")

    patch_luts: List[str] = list(J["patch_luts"])

    with Solver(name=solver_name) as s:
        for c in cnf:
            s.add_clause(c)

        # We want an equivalent patch: diff_or = 0
        if not s.solve(assumptions=[-diff]):
            raise RuntimeError("UNSAT under diff=0 => no equivalent patch exists (unexpected here)")

        model = s.get_model()
        modelset = set(model)

        def val(var: int) -> int:
            if var in modelset: return 1
            if -var in modelset: return 0
            return 0

        patched_func: Dict[str,Any] = {}
        for lut in patch_luts:
            bits = []
            for r in range(16):
                tv = name2var.get(f"TT__{lut}__{r}")
                if tv is None:
                    raise RuntimeError(f"Missing TT var TT__{lut}__{r}")
                bits.append(val(int(tv)))

            patched_func[lut] = {
                "bits_lsb_first": bits,
                "func_hex": bits_to_hex16(bits),
            }

    out = {
        "source_cnf": J["spec"],
        "target": J["target"],
        "window": J["window"],
        "diff_or_var": diff,
        "patch_luts": patch_luts,
        "patched_func": patched_func,
    }
    outp = Path(os.path.expanduser(args.out))
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2))
    print("[OK] wrote", outp)

if __name__ == "__main__":
    main()
