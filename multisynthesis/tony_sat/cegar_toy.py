# cegar_toy.py
from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from pysat.solvers import Solver

from cnf_builder import CNFBuilder
from cnf_gates import gate_xor
from toy_circuit import build_spec, build_target


SolverName = "glucose4"  # jij hebt deze; we pinnen dit voor reproduceerbaarheid


def bits_to_hex(vbits: List[int]) -> str:
    # v0 is LSB, v3 is MSB -> nibble = v0 + 2*v1 + 4*v2 + 8*v3
    nibble = vbits[0] + 2 * vbits[1] + 4 * vbits[2] + 8 * vbits[3]
    return hex(nibble)


def model_val(model_set: set[int], var: int) -> int:
    return 1 if var in model_set else 0


def sat1_find_candidate(W: List[Tuple[int, int, int, int]]) -> Optional[List[int]]:
    """
    SAT-1: find v such that for all patterns in W: T(v,x)=S(x)
    Returns vbits [v0,v1,v2,v3] or None if UNSAT.
    """
    cnf = CNFBuilder()

    # shared LUT program bits (existential variables)
    v0 = cnf.new_var("v0")
    v1 = cnf.new_var("v1")
    v2 = cnf.new_var("v2")
    v3 = cnf.new_var("v3")
    v = [v0, v1, v2, v3]

    # If W is empty, SAT-1 should be SAT (any v). We'll still solve.
    for i, (av, bv, cv, dv) in enumerate(W):
        # Create per-pattern PI vars (unique names)
        a = cnf.new_var(f"a_{i}")
        b = cnf.new_var(f"b_{i}")
        c = cnf.new_var(f"c_{i}")
        d = cnf.new_var(f"d_{i}")

        # Fix PI values for this pattern
        cnf.add_unit(a, bool(av))
        cnf.add_unit(b, bool(bv))
        cnf.add_unit(c, bool(cv))
        cnf.add_unit(d, bool(dv))

        # Build SPEC and TARGET for this pattern
         
        prefix = f"p{i}_"
        S, g = build_spec(cnf, a, b, c, d, prefix=prefix)
        T = build_target(cnf, g, c, d, v, prefix=prefix)
        eq = cnf.new_var(f"{prefix}eq")

        gate_xor(cnf, S, T, eq)
        cnf.add_unit(eq, False)

    with Solver(name=SolverName) as solver:
        for cl in cnf.clauses:
            solver.add_clause(cl)
        sat = solver.solve()
        if not sat:
            return None
        model = set(solver.get_model())
        return [model_val(model, v0), model_val(model, v1), model_val(model, v2), model_val(model, v3)]


def sat2_find_counterexample(vbits: List[int]) -> Optional[Tuple[int, int, int, int]]:
    """
    SAT-2: with fixed vbits, find x such that T(v,x) != S(x).
    Returns counterexample (a,b,c,d) or None if UNSAT (i.e., no counterexample).
    """
    cnf = CNFBuilder()

    # PI vars are free here
    a = cnf.new_var("a")
    b = cnf.new_var("b")
    c = cnf.new_var("c")
    d = cnf.new_var("d")

    # LUT program bits vars, then fixed to vbits
    v0 = cnf.new_var("v0")
    v1 = cnf.new_var("v1")
    v2 = cnf.new_var("v2")
    v3 = cnf.new_var("v3")
    v = [v0, v1, v2, v3]
    cnf.add_unit(v0, bool(vbits[0]))
    cnf.add_unit(v1, bool(vbits[1]))
    cnf.add_unit(v2, bool(vbits[2]))
    cnf.add_unit(v3, bool(vbits[3]))

    # Build circuits
    S, g = build_spec(cnf, a, b, c, d,prefix = "m_")
    T = build_target(cnf, g, c, d, v, prefix = "m_")

    # miter: diff = S XOR T, force diff=1
    diff = cnf.new_var("m_diff")
    gate_xor(cnf, S, T, diff)
    cnf.add_unit(diff, True)

    with Solver(name=SolverName) as solver:
        for cl in cnf.clauses:
            solver.add_clause(cl)
        sat = solver.solve()
        if not sat:
            return None
        model = set(solver.get_model())
        return (
            model_val(model, a),
            model_val(model, b),
            model_val(model, c),
            model_val(model, d),
        )


def run_cegar(max_iters: int = 50) -> List[int]:
    W: List[Tuple[int, int, int, int]] = []

    for it in range(max_iters):
        v = sat1_find_candidate(W)
        if v is None:
            raise RuntimeError("[SAT-1] UNSAT: geen kandidaat v bestaat (zou niet mogen in toy).")

        ce = sat2_find_counterexample(v)
        print(f"[ITER {it}] |W|={len(W)}  v={v}  hex={bits_to_hex(v)}")

        if ce is None:
            print("[DONE] SAT-2 UNSAT: geen counterexample. v is correct.")
            return v

        print(f"        counterexample a,b,c,d = {ce}")
        if ce in W:
            raise RuntimeError("CEGAR stuck: dezelfde counterexample opnieuw (check encodings).")
        W.append(ce)

    raise RuntimeError(f"CEGAR did not converge within {max_iters} iterations.")


if __name__ == "__main__":
    v_final = run_cegar(max_iters=50)
    print(f"[RESULT] v_final = {v_final}  hex={bits_to_hex(v_final)}")
