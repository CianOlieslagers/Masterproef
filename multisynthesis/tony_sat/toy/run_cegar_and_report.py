# run_cegar_and_report.py
from __future__ import annotations
from typing import List, Optional, Tuple, Dict, Set

from pysat.solvers import Solver

from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_gates import gate_xor


from tony_sat.toy.toy_circuit import (
    build_spec,
    build_target_contextual,
    add_conditional_not_equal,
    enforce_when_row,
)
from tony_sat.core.cnf_gates import gate_or


SolverName = "glucose4"


# --------------------------
# helpers
# --------------------------
def bits_to_hex(vbits: List[int]) -> str:
    nibble = vbits[0] + 2 * vbits[1] + 4 * vbits[2] + 8 * vbits[3]
    return hex(nibble)


def model_val(model_set: Set[int], var: int) -> int:
    return 1 if var in model_set else 0


def row_idx(u: int, w: int) -> int:
    return 2 * u + w


def f_or(u: int, w: int) -> int:
    return 1 if (u or w) else 0


# --------------------------
# SAT-2 (equivalence check)
# --------------------------
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

    # SPEC + context restriction
    S, g = build_spec(cnf, a, b, c, d, prefix="m_")
    add_conditional_not_equal(cnf, g, c, d)

    # TARGET
    T, _, _, _ = build_target_contextual(cnf, g, c, d, v, prefix="m_")

    # enforce difference: S xor T = 1
    diff = cnf.new_var("m_diff")
    gate_xor(cnf, S, T, diff)
    cnf.add_unit(diff, True)

    with Solver(name=SolverName) as solver:
        for cl in cnf.clauses:
            solver.add_clause(cl)
        if not solver.solve():
            return None  # UNSAT => equivalent
        model = set(solver.get_model())
        return (
            model_val(model, a),
            model_val(model, b),
            model_val(model, c),
            model_val(model, d),
        )


def sat2_is_equivalent(vbits: List[int]) -> bool:
    return sat2_find_counterexample(vbits) is None


# --------------------------
# SAT-1 (candidate synthesis)
# Two variants: baseline and with F=u OR w on DC rows
# --------------------------
def sat1_find_candidate_baseline(W: List[Tuple[int, int, int, int]]) -> Optional[List[int]]:
    cnf = CNFBuilder()

    v0 = cnf.new_var("v0")
    v1 = cnf.new_var("v1")
    v2 = cnf.new_var("v2")
    v3 = cnf.new_var("v3")
    v = [v0, v1, v2, v3]

    for i, (av, bv, cv, dv) in enumerate(W):
        prefix = f"p{i}_"
        a = cnf.new_var(f"{prefix}a")
        b = cnf.new_var(f"{prefix}b")
        c = cnf.new_var(f"{prefix}c")
        d = cnf.new_var(f"{prefix}d")

        cnf.add_unit(a, bool(av))
        cnf.add_unit(b, bool(bv))
        cnf.add_unit(c, bool(cv))
        cnf.add_unit(d, bool(dv))

        S, g = build_spec(cnf, a, b, c, d, prefix=prefix)
        add_conditional_not_equal(cnf, g, c, d)

        T, _, _, _ = build_target_contextual(cnf, g, c, d, v, prefix=prefix)

        eq = cnf.new_var(f"{prefix}eq")
        gate_xor(cnf, S, T, eq)
        cnf.add_unit(eq, False)

    with Solver(name=SolverName) as solver:
        for cl in cnf.clauses:
            solver.add_clause(cl)

        if not solver.solve():
            return None
        model = set(solver.get_model())
        return [model_val(model, v0), model_val(model, v1), model_val(model, v2), model_val(model, v3)]


def sat1_find_candidate_match_or_on_dc_rows(
    W: List[Tuple[int, int, int, int]],
    dc_rows: Set[Tuple[int, int]],
) -> Optional[List[int]]:

    """
    Enforce: on rows (u,w)=(0,0) and (1,1): LUT_out == (u OR w).
    (These are intended to be DC rows under the toy context.)
    """
    cnf = CNFBuilder()

    v0 = cnf.new_var("v0")
    v1 = cnf.new_var("v1")
    v2 = cnf.new_var("v2")
    v3 = cnf.new_var("v3")
    v = [v0, v1, v2, v3]
    # Force DC truth-table entries to match F=u OR w, but ONLY on DC rows.
    # Mapping: idx = 2*u + w  (consistent with print_truth_table)
    for (u_row, w_row) in dc_rows:
        idx = row_idx(u_row, w_row)
        cnf.add_unit(v[idx], bool(f_or(u_row, w_row)))

    for i, (av, bv, cv, dv) in enumerate(W):
        prefix = f"p{i}_"
        a = cnf.new_var(f"{prefix}a")
        b = cnf.new_var(f"{prefix}b")
        c = cnf.new_var(f"{prefix}c")
        d = cnf.new_var(f"{prefix}d")

        cnf.add_unit(a, bool(av))
        cnf.add_unit(b, bool(bv))
        cnf.add_unit(c, bool(cv))
        cnf.add_unit(d, bool(dv))

        S, g = build_spec(cnf, a, b, c, d, prefix=prefix)
        add_conditional_not_equal(cnf, g, c, d)

        T, u, w, L = build_target_contextual(cnf, g, c, d, v, prefix=prefix)

        # Build F = u OR w
        F = cnf.new_var(f"{prefix}F_or")
        gate_or(cnf, u, w, F)

        # Enforce on the intended DC rows only
        enforce_when_row(cnf, u, w, 0, 0, L, F, prefix=prefix)
        enforce_when_row(cnf, u, w, 1, 1, L, F, prefix=prefix)

        eq = cnf.new_var(f"{prefix}eq")
        gate_xor(cnf, S, T, eq)
        cnf.add_unit(eq, False)

    with Solver(name=SolverName) as solver:
        for cl in cnf.clauses:
            solver.add_clause(cl)

        if not solver.solve():
            return None
        model = set(solver.get_model())
        return [model_val(model, v0), model_val(model, v1), model_val(model, v2), model_val(model, v3)]


# --------------------------
# CEGAR driver (generic)
# --------------------------
def run_cegar(sat1_fn, max_iters: int = 50, label: str = "", *args) -> List[int]:
    W: List[Tuple[int, int, int, int]] = []

    for it in range(max_iters):
        v = sat1_fn(W, *args)
        if v is None:
            raise RuntimeError(f"[{label}] SAT-1 UNSAT: no candidate v exists.")

        ce = sat2_find_counterexample(v)
        print(f"[{label} ITER {it}] |W|={len(W)}  v={v}  hex={bits_to_hex(v)}")

        if ce is None:
            print(f"[{label} DONE] SAT-2 UNSAT: no counterexample. v is correct.")
            return v

        print(f"[{label}] counterexample a,b,c,d = {ce}")
        if ce in W:
            raise RuntimeError(f"[{label}] CEGAR stuck: repeated counterexample.")
        W.append(ce)

    raise RuntimeError(f"[{label}] CEGAR did not converge within {max_iters} iterations.")


# --------------------------
# Derive CARE/DC rows empirically (via flips)
# --------------------------
def classify_rows_by_flip(v_ref: List[int]) -> Dict[Tuple[int, int], str]:
    """
    For each LUT row (u,w), flip the corresponding v-bit and see if equivalence remains.
    If flip keeps equivalence => DC row, else CARE row.
    """
    cls: Dict[Tuple[int, int], str] = {}
    for u in (0, 1):
        for w in (0, 1):
            idx = row_idx(u, w)
            v2 = v_ref.copy()
            v2[idx] ^= 1
            cls[(u, w)] = "DC" if sat2_is_equivalent(v2) else "CARE"
    return cls


def print_truth_table(v: List[int], title: str, cls: Dict[Tuple[int, int], str]) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    print(" u  w | idx | v[idx] | F=u OR w | row-type")
    print("-----+-----+--------+----------+---------")
    for u in (0, 1):
        for w in (0, 1):
            idx = row_idx(u, w)
            print(f" {u}  {w} |  {idx}  |   {v[idx]}   |    {f_or(u,w)}     | {cls[(u,w)]}")
    print(f"hex = {bits_to_hex(v)}")


if __name__ == "__main__":
    print("[RUN] Baseline CEGAR (no extra subexpression constraint)")
    v_before = run_cegar(sat1_find_candidate_baseline, label="BASE")

    # Classify rows (CARE/DC) from baseline
    row_class = classify_rows_by_flip(v_before)

    print_truth_table(v_before, "Truth table BEFORE (baseline)", row_class)
    dc_rows = {k for k, v in row_class.items() if v == "DC"}

    print("\n[RUN] CEGAR with subexpression constraint: enforce LUT(u,w)=u OR w on DC rows (00 and 11)")

    v_after = run_cegar(sat1_find_candidate_match_or_on_dc_rows, 50, "OR-DC", dc_rows)
    print_truth_table(v_after, "Truth table AFTER (with F=u OR w on DC rows)", row_class)

    # Show delta summary
    print("\n[SUMMARY] Changes per row (before -> after):")
    for u in (0, 1):
        for w in (0, 1):
            idx = row_idx(u, w)
            b = v_before[idx]
            a = v_after[idx]
            tag = row_class[(u, w)]
            changed = "CHANGED" if b != a else "same"
            print(f"  (u,w)=({u},{w}) idx={idx}: {b} -> {a}  [{tag}]  ({changed})")
