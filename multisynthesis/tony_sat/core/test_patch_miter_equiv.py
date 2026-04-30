from __future__ import annotations
import argparse
from pysat.solvers import Solver

from tony_sat.core.blif_parser import parse_blif, summarize
from tony_sat.core.dc_io import load_dc_rows
from tony_sat.core.patch_miter_blif import build_patch_miter
from tony_sat.core.dc_blif import pick_solver_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    ap.add_argument("--pit", required=True)
    ap.add_argument("--dc_json", required=True)
    args = ap.parse_args()

    design = parse_blif(args.blif)
    print("[INFO] BLIF summary:", summarize(design))

    care, free = load_dc_rows(args.dc_json)
    pm = build_patch_miter(design, pit_lut=args.pit, care_rows=care, free_rows=free)

    solver_name = pick_solver_name()
    with Solver(name=solver_name) as s:
        for cl in pm.cnf.clauses:
            s.add_clause(cl)

        # Check if there exists an assignment making diff=1
        s.add_clause([pm.diff_var])
        sat = s.solve()
        print("[INFO] diff=1 SAT?", sat)
        if sat:
            model = set(s.get_model())
            def val(v):
                return (v in model)

            print("[DBG] diff_var =", pm.diff_var, "val=", val(pm.diff_var))
            # print outputs
            for o in design.outputs:
                vo = pm.cnf.var(f"o__{o}")
                vm = pm.cnf.var(f"m__{o}")
                print(f"[DBG] {o}: orig={val(vo)} mut={val(vm)}")

            # print pit fanins in both circuits
            for n in pm.pit_fanins:
                vo = pm.cnf.var(f"o__{n}")
                vm = pm.cnf.var(f"m__{n}")
                print(f"[DBG] pit fanin {n}: orig={val(vo)} mut={val(vm)}")

            # print patch bits
            print("[DBG] patch bits:")
            for r in sorted(pm.patch_bits.keys()):
                print("  r", r, "var", pm.patch_bits[r], "val", val(pm.patch_bits[r]))
            print("[WARN] Found a counterexample: patchable mutant can differ -> DC set inconsistent or bug")
        else:
            print("[OK] UNSAT: with CARE constraints, mutant cannot differ on outputs (paper-consistent)")


if __name__ == "__main__":
    main()
