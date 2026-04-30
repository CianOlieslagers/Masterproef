# cegar_toy_contextual.py
from __future__ import annotations
from typing import List, Optional, Tuple

from pysat.solvers import Solver

from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_gates import gate_xor


from tony_sat.toy.toy_circuit import (
    build_spec,
    build_target_contextual,
    add_conditional_not_equal,
)

from tony_sat.core.cnf_gates import gate_or
from tony_sat.toy.toy_circuit import enforce_when_row




SolverName = "glucose4"  # jij gebruikt deze, dus we pinnen


def bits_to_hex(vbits: List[int]) -> str:
    # v0 LSB ... v3 MSB
    nibble = vbits[0] + 2 * vbits[1] + 4 * vbits[2] + 8 * vbits[3]
    return hex(nibble)


def model_val(model_set: set[int], var: int) -> int:
    return 1 if var in model_set else 0


def sat1_find_candidate(W: List[Tuple[int, int, int, int]]) -> Optional[List[int]]:
    """
    SAT-1: find v such that for all patterns in W: T(v,x)=S(x)
    """
    cnf = CNFBuilder()

    # shared LUT program bits
    v0 = cnf.new_var("v0")
    v1 = cnf.new_var("v1")
    v2 = cnf.new_var("v2")
    v3 = cnf.new_var("v3")
    v = [v0, v1, v2, v3]

    # --- Step 6B: subexpression-like constraint on DON'T-CARE rows ---
    # Choose F(u,w) = u OR w.
    # Then: F(0,0)=0 => force v0=0
    #       F(1,1)=1 => force v3=1
    cnf.add_unit(v0, False)   # v0 = F(0,0) = 0
    cnf.add_unit(v3, True)    # v3 = F(1,1) = 1

    for i, (av, bv, cv, dv) in enumerate(W):
        prefix = f"p{i}_"

        # Per-pattern PI vars
        a = cnf.new_var(f"{prefix}a")
        b = cnf.new_var(f"{prefix}b")
        c = cnf.new_var(f"{prefix}c")
        d = cnf.new_var(f"{prefix}d")

        cnf.add_unit(a, bool(av))
        cnf.add_unit(b, bool(bv))
        cnf.add_unit(c, bool(cv))
        cnf.add_unit(d, bool(dv))

        # SPEC
        S, g = build_spec(cnf, a, b, c, d, prefix=prefix)

        # context constraint: g -> (d = ~c)
        add_conditional_not_equal(cnf, g, c, d)

        # TARGET
        T, u, w, L = build_target_contextual(cnf, g, c, d, v, prefix=prefix)

        # Build F = u OR w
        F = cnf.new_var(f"{prefix}F_or")
        gate_or(cnf, u, w, F)

        # Enforce only on DON'T-CARE rows: (u,w)=(0,0) and (1,1)
        enforce_when_row(cnf, u, w, 0, 0, L, F, prefix=prefix)
        enforce_when_row(cnf, u, w, 1, 1, L, F, prefix=prefix)

        # enforce S == T
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
        return [
            model_val(model, v0),
            model_val(model, v1),
            model_val(model, v2),
            model_val(model, v3),
        ]


def sat2_find_counterexample(vbits: List[int]) -> Optional[Tuple[int, int, int, int]]:
    """
    SAT-2: with fixed vbits, find x such that T(v,x) != S(x).
    Returns counterexample (a,b,c,d) or None if UNSAT.
    """
    cnf = CNFBuilder()

    # Free PI vars
    a = cnf.new_var("a")
    b = cnf.new_var("b")
    c = cnf.new_var("c")
    d = cnf.new_var("d")

    # LUT bits fixed
    v0 = cnf.new_var("v0")
    v1 = cnf.new_var("v1")
    v2 = cnf.new_var("v2")
    v3 = cnf.new_var("v3")
    v = [v0, v1, v2, v3]
    cnf.add_unit(v0, bool(vbits[0]))
    cnf.add_unit(v1, bool(vbits[1]))
    cnf.add_unit(v2, bool(vbits[2]))
    cnf.add_unit(v3, bool(vbits[3]))

    S, g = build_spec(cnf, a, b, c, d, prefix="m_")
    add_conditional_not_equal(cnf, g, c, d)
    T, _, _, _ = build_target_contextual(cnf, g, c, d, v, prefix="m_")
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


def sat2_is_equivalent(vbits: List[int]) -> bool:
    return sat2_find_counterexample(vbits) is None


def freedom_check(vbits: List[int]) -> None:
    """
    For each program bit, flip it and re-run SAT-2.
    If SAT-2 stays UNSAT => that bit is a don't-care under the context.
    """
    print("\n[FREEDOM CHECK] Flip each v_i and re-check equivalence via SAT-2")
    for i in range(4):
        v2 = vbits.copy()
        v2[i] ^= 1
        ok = sat2_is_equivalent(v2)
        status = "FREE (flip still OK)" if ok else "FIXED (flip breaks)"
        print(f"  v{i}: {vbits[i]} -> {v2[i]}  => {status}   (hex {bits_to_hex(v2)})")


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
    freedom_check(v_final)
