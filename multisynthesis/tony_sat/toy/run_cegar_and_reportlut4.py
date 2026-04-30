# run_cegar_and_report_lut4.py
from __future__ import annotations
from typing import List, Optional, Tuple, Dict, Set

from pysat.solvers import Solver

from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_gates import gate_xor

from tony_sat.toy.toy_circuit import (
    build_spec,
    build_target_contextual_lut4,
    add_conditional_not_equal,
    enforce_when_row,
)
from tony_sat.core.cnf_gates import gate_or


SolverName = "glucose4"


def bits_to_hex16(vbits: List[int]) -> str:
    val = 0
    for i, b in enumerate(vbits):  # v[0] is LSB in this hex view
        val |= (b & 1) << i
    return hex(val)


def model_val(model_set: Set[int], var: int) -> int:
    return 1 if var in model_set else 0


def idx_to_bits4(idx: int) -> tuple[int, int, int, int]:
    # x0 MSB ... x3 LSB (consistent met lut4 idx = 8*x0 + 4*x1 + 2*x2 + x3)
    return ((idx >> 3) & 1, (idx >> 2) & 1, (idx >> 1) & 1, (idx >> 0) & 1)


def f_subexpr(x0: int, x1: int, x2: int, x3: int) -> int:
    # Voor later steering: F = x0 OR x1
    return 1 if (x0 or x1) else 0


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

    # LUT4 truth table bits fixed
    v_vars = [cnf.new_var(f"v{i}") for i in range(16)]
    for i in range(16):
        cnf.add_unit(v_vars[i], bool(vbits[i]))

    # SPEC
    S, g = build_spec(cnf, a, b, c, d, prefix="m_")

    # TARGET (LUT4 PoC)
    T, _, _ = build_target_contextual_lut4(cnf, g, c, d, v_vars, prefix="m_")

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


def sat1_find_candidate_baseline(W: List[Tuple[int, int, int, int]]) -> Optional[List[int]]:
    """
    SAT-1 baseline: find v such that for all patterns in W: T(v,x)=S(x).
    """
    cnf = CNFBuilder()

    # existential LUT bits (shared across all patterns)
    v_vars = [cnf.new_var(f"v{i}") for i in range(16)]

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
        T, _, _ = build_target_contextual_lut4(cnf, g, c, d, v_vars, prefix=prefix)

        eq = cnf.new_var(f"{prefix}eq")
        gate_xor(cnf, S, T, eq)
        cnf.add_unit(eq, False)

    with Solver(name=SolverName) as solver:
        for cl in cnf.clauses:
            solver.add_clause(cl)

        if not solver.solve():
            return None

        model = set(solver.get_model())
        return [model_val(model, vv) for vv in v_vars]

def sat1_find_candidate_steer_on_dc_rows(
    W: List[Tuple[int, int, int, int]],
    dc_idx: Set[int],
) -> Optional[List[int]]:
    """
    SAT-1 with steering:
    For all idx in dc_idx: force v[idx] = F(x0,x1,x2,x3) where F = x0 OR x1.
    Only DC rows are constrained.
    """
    cnf = CNFBuilder()

    # existential LUT bits (shared across all patterns)
    v_vars = [cnf.new_var(f"v{i}") for i in range(16)]

    # --- Steering constraints on DC rows only ---
    for idx in dc_idx:
        x0, x1, x2, x3 = idx_to_bits4(idx)
        cnf.add_unit(v_vars[idx], bool(f_subexpr(x0, x1, x2, x3)))  # F = x0 OR x1

    # Usual CEGAR pattern constraints
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
        T, _, _ = build_target_contextual_lut4(cnf, g, c, d, v_vars, prefix=prefix)

        eq = cnf.new_var(f"{prefix}eq")
        gate_xor(cnf, S, T, eq)
        cnf.add_unit(eq, False)

    with Solver(name=SolverName) as solver:
        for cl in cnf.clauses:
            solver.add_clause(cl)

        if not solver.solve():
            return None

        model = set(solver.get_model())
        return [model_val(model, vv) for vv in v_vars]




def run_cegar(sat1_fn, max_iters: int = 50, label: str = "", *args) -> List[int]:
    W: List[Tuple[int, int, int, int]] = []

    for it in range(max_iters):
        v = sat1_fn(W, *args)
        if v is None:
            raise RuntimeError(f"[{label}] SAT-1 UNSAT: no candidate v exists.")

        ce = sat2_find_counterexample(v)
        print(f"[{label} ITER {it}] |W|={len(W)}  hex={bits_to_hex16(v)}")

        if ce is None:
            print(f"[{label} DONE] SAT-2 UNSAT: no counterexample. v is correct.")
            return v

        print(f"[{label}] counterexample a,b,c,d = {ce}")
        if ce in W:
            raise RuntimeError(f"[{label}] CEGAR stuck: repeated counterexample.")
        W.append(ce)

    raise RuntimeError(f"[{label}] CEGAR did not converge within {max_iters} iterations.")

def classify_rows_by_flip(v_ref: List[int]) -> Dict[int, str]:
    """
    For each LUT row idx (0..15), flip v[idx] and see if equivalence remains.
    If flip keeps equivalence => DC row, else CARE row.
    Returns dict idx -> "DC"/"CARE".
    """
    cls: Dict[int, str] = {}
    for idx in range(16):
        v2 = v_ref.copy()
        v2[idx] ^= 1
        cls[idx] = "DC" if sat2_is_equivalent(v2) else "CARE"
    return cls


def print_truth_table(v: List[int], title: str, cls: Dict[int, str]) -> None:
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)
    print(" x0 x1 x2 x3 | idx | v[idx] | F=x0 OR x1 | row-type")
    print("-------------+-----+--------+------------+---------")
    for idx in range(16):
        x0, x1, x2, x3 = idx_to_bits4(idx)
        print(
            f"  {x0}  {x1}  {x2}  {x3}  | {idx:>3} |   {v[idx]}    |     {f_subexpr(x0,x1,x2,x3)}      | {cls[idx]}"
        )
    print(f"hex = {bits_to_hex16(v)}")

def print_delta_summary(v_before: List[int], v_after: List[int], cls: Dict[int, str]) -> None:
    print("\n[SUMMARY] Changes per row (before -> after):")
    for idx in range(16):
        b = v_before[idx]
        a = v_after[idx]
        tag = cls[idx]
        changed = "CHANGED" if b != a else "same"
        x0, x1, x2, x3 = idx_to_bits4(idx)
        print(f"  idx={idx:2} ({x0}{x1}{x2}{x3}): {b} -> {a}  [{tag}]  ({changed})")




if __name__ == "__main__":
    print("[RUN] Baseline CEGAR (LUT4, no steering)")
    v_before = run_cegar(sat1_find_candidate_baseline, max_iters=100, label="LUT4-BASE")
    print("\n[RESULT] v_before =", bits_to_hex16(v_before))

    row_class = classify_rows_by_flip(v_before)
    print_truth_table(v_before, "Truth table BEFORE (baseline LUT4)", row_class)

    dc_idx = {idx for idx, t in row_class.items() if t == "DC"}
    n_dc = len(dc_idx)
    n_care = 16 - n_dc
    print(f"\n[INFO] Row classification: DC={n_dc}, CARE={n_care}")

    print("\n[RUN] CEGAR with steering on DC rows: enforce v[idx] = (x0 OR x1) for DC rows")
    v_after = run_cegar(
    sat1_find_candidate_steer_on_dc_rows,
    100,
    "LUT4-OR-DC",
    dc_idx,
    )

    print("\n[RESULT] v_after  =", bits_to_hex16(v_after))

    # Print AFTER using the same CARE/DC classification derived from baseline
    print_truth_table(v_after, "Truth table AFTER (with F=x0 OR x1 on DC rows)", row_class)

    print_delta_summary(v_before, v_after, row_class)
