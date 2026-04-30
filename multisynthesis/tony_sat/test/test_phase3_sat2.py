# test_phase3_sat2.py
from __future__ import annotations
from pysat.solvers import Solver

from cnf_builder import CNFBuilder
from cnf_gates import gate_xor
from toy_circuit import build_spec, build_target


def pick_solver_name() -> str:
    # Same strategy as in phase2
    candidates = ["cadical", "glucose4", "glucose3", "minisat22", "minicard"]
    for name in candidates:
        try:
            s = Solver(name=name)
            s.delete()
            return name
        except Exception:
            continue
    raise RuntimeError("No SAT solver backend found in PySAT.")


def lit_for_value(var: int, value: int) -> int:
    return var if value == 1 else -var


def main():
    cnf = CNFBuilder()

    # PI's
    a = cnf.new_var("a")
    b = cnf.new_var("b")
    c = cnf.new_var("c")
    d = cnf.new_var("d")

    # LUT program bits v0..v3
    v0 = cnf.new_var("v0")
    v1 = cnf.new_var("v1")
    v2 = cnf.new_var("v2")
    v3 = cnf.new_var("v3")
    v = [v0, v1, v2, v3]

    # Build SPEC and TARGET
    S, g = build_spec(cnf, a, b, c, d)
    T = build_target(cnf, g, c, d, v)

    # miter: diff = S XOR T, and force diff=1
    diff = cnf.new_var("diff")
    gate_xor(cnf, S, T, diff)
    cnf.add_unit(diff, True)

    # Fix v to XOR truth table using idx=2*c+d:
    # cd=00->0, 01->1, 10->1, 11->0  => (0,1,1,0)
    cnf.add_unit(v0, False)
    cnf.add_unit(v1, True)
    cnf.add_unit(v2, True)
    cnf.add_unit(v3, False)

    solver_name = pick_solver_name()
    print(f"[INFO] Using SAT solver backend: {solver_name}")

    with Solver(name=solver_name) as solver:
        for cl in cnf.clauses:
            solver.add_clause(cl)

        sat = solver.solve()
        if sat:
            model = set(solver.get_model())

            def val(x: int) -> int:
                return 1 if x in model else 0

            print("[FAIL] SAT: counterexample gevonden (dit zou niet mogen).")
            print("a b c d =", val(a), val(b), val(c), val(d))
            print("g =", val(g), "S =", val(S), "T =", val(T))
        else:
            print("[OK] UNSAT: geen counterexample; TARGET == SPEC voor alle inputs.")


if __name__ == "__main__":
    main()
