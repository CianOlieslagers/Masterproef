#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path
from typing import Any, Dict, List
from pysat.solvers import Solver

def load(p: str) -> Any:
    return json.loads(Path(p).read_text())

def bit_lits_for_row(xs: List[int], r: int) -> List[int]:
    # MUST match super_to_cnf_step4.add_lut4_patch:
    # b0 = (r>>0), ... b3=(r>>3) and xs=[x0,x1,x2,x3]
    b0 = (r >> 0) & 1
    b1 = (r >> 1) & 1
    b2 = (r >> 2) & 1
    b3 = (r >> 3) & 1
    bits = [b0,b1,b2,b3]
    lits = []
    for x, b in zip(xs, bits):
        lits.append(x if b == 1 else -x)
    return lits

def model_value(model: List[int], var: int) -> int:
    s = set(model)
    if var in s: return 1
    if -var in s: return 0
    # should not happen in SAT model; but keep safe
    return 0

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cnfjson", required=True, help="spec_target.cnf.json from step4")
    ap.add_argument("--target", required=True, help="target_feasible0.super.sat.v2.json (for pins)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--solver", default=None)
    args = ap.parse_args()

    J = load(args.cnfjson)
    T = load(args.target)

    clauses = J["clauses_dimacs"]
    name2var: Dict[str,int] = J["name2var"]
    diff = int(J["diff_or_var"])
    solver_name = args.solver or J.get("solver","glucose4")

    patch_luts: List[str] = list(J["patch_luts"])

    # Build pin var lists for each patch LUT from TARGET netlist order
    lut2xs: Dict[str,List[int]] = {}
    for lut in patch_luts:
        pins = (((T.get("luts") or {}).get(lut) or {}).get("netlist") or {}).get("lut_inputs_ordered") or []
        if len(pins) != 4:
            raise RuntimeError(f"{lut}: expected 4 pins, got {len(pins)}: {pins}")
        xs = []
        for net in pins:
            key = f"T__{net}"
            v = name2var.get(key)
            if v is None:
                raise RuntimeError(f"Missing var for net {net} as {key} in CNF json")
            xs.append(int(v))
        lut2xs[lut] = xs

    # Solve per row per LUT
    patched_func: Dict[str,Any] = {}
    with Solver(name=solver_name) as s:
        for c in clauses:
            s.add_clause(c)

        for lut in patch_luts:
            xs = lut2xs[lut]
            bits = []
            sat_rows = 0
            for r in range(16):
                ass = [-diff] + bit_lits_for_row(xs, r)
                ok = s.solve(assumptions=ass)
                if not ok:
                    bits.append(None)
                    continue
                sat_rows += 1
                model = s.get_model()
                tv = name2var.get(f"TT__{lut}__{r}")
                if tv is None:
                    raise RuntimeError(f"Missing TT var TT__{lut}__{r}")
                bits.append(model_value(model, int(tv)))

            # Convert to hex if all rows SAT; else mark partial
            if all(b in (0,1) for b in bits):
                val = 0
                for i,b in enumerate(bits):
                    val |= (int(b) & 1) << i  # LSB-first
                func_hex = f"{val:04x}"
            else:
                func_hex = None

            patched_func[lut] = {
                "pins_ordered": [(((T["luts"][lut]["netlist"])["lut_inputs_ordered"])[i]) for i in range(4)],
                "bits_lsb_first": bits,
                "func_hex": func_hex,
                "sat_rows": sat_rows,
            }

    out = {
        "source_cnf": J["spec"],
        "target": J["target"],
        "window": J["window"],
        "diff_or_var": diff,
        "patch_luts": patch_luts,
        "patched_func": patched_func,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print("[OK] wrote", args.out)

if __name__ == "__main__":
    main()
