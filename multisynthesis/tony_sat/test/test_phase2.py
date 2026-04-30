# test_phase2.py
from __future__ import annotations
from typing import Callable, Dict, List, Tuple

from pysat.solvers import Solver

from cnf_builder import CNFBuilder
from cnf_gates import gate_not, gate_and, gate_or, gate_xor, gate_mux
from cnf_lut import lut2


def pick_solver_name() -> str:
    # Robust: try a list and return the first that works.
    # Common PySAT names: "cadical", "glucose3", "glucose4", "minisat22", "minicard"
    candidates = ["cadical", "glucose4", "glucose3", "minisat22", "minicard"]
    for name in candidates:
        try:
            s = Solver(name=name)
            s.delete()
            return name
        except Exception:
            continue
    raise RuntimeError(
        "No SAT solver backend found in PySAT. Install e.g. python-sat with solvers."
    )


def solve_sat(cnf: CNFBuilder, assumptions: List[int]) -> bool:
    name = pick_solver_name()
    with Solver(name=name) as s:
        for cl in cnf.clauses:
            s.add_clause(cl)
        return s.solve(assumptions=assumptions)


def lit_for_value(var: int, value: int) -> int:
    return var if value == 1 else -var


def assert_gate_truth_table_1in(
    gate_builder: Callable[[CNFBuilder, int, int], None],
    truth: Dict[int, int],
    gate_name: str,
) -> None:
    cnf = CNFBuilder()
    x = cnf.new_var("x")
    y = cnf.new_var("y")
    gate_builder(cnf, x, y)

    for xv in [0, 1]:
        expected = truth[xv]
        # Check SAT for y != expected under x fixed
        sat = solve_sat(cnf, assumptions=[lit_for_value(x, xv), lit_for_value(y, 1 - expected)])
        if sat:
            raise AssertionError(f"{gate_name} failed for x={xv}: y can be {1-expected} but expected {expected}")


def assert_gate_truth_table_2in(
    gate_builder: Callable[[CNFBuilder, int, int, int], None],
    truth: Dict[Tuple[int, int], int],
    gate_name: str,
) -> None:
    cnf = CNFBuilder()
    x1 = cnf.new_var("x1")
    x2 = cnf.new_var("x2")
    y = cnf.new_var("y")
    gate_builder(cnf, x1, x2, y)

    for a in [0, 1]:
        for b in [0, 1]:
            expected = truth[(a, b)]
            sat = solve_sat(
                cnf,
                assumptions=[
                    lit_for_value(x1, a),
                    lit_for_value(x2, b),
                    lit_for_value(y, 1 - expected),
                ],
            )
            if sat:
                raise AssertionError(
                    f"{gate_name} failed for x1={a}, x2={b}: y can be {1-expected} but expected {expected}"
                )


def assert_mux_truth_table() -> None:
    cnf = CNFBuilder()
    s = cnf.new_var("s")
    t = cnf.new_var("t")
    f = cnf.new_var("f")
    y = cnf.new_var("y")
    gate_mux(cnf, s, t, f, y)

    for sv in [0, 1]:
        for tv in [0, 1]:
            for fv in [0, 1]:
                expected = tv if sv == 1 else fv
                sat = solve_sat(
                    cnf,
                    assumptions=[
                        lit_for_value(s, sv),
                        lit_for_value(t, tv),
                        lit_for_value(f, fv),
                        lit_for_value(y, 1 - expected),
                    ],
                )
                if sat:
                    raise AssertionError(
                        f"MUX failed for s={sv}, t={tv}, f={fv}: y can be {1-expected} but expected {expected}"
                    )


def assert_lut2_mapping() -> None:
    # Test several random LUT truth tables (deterministic set here)
    test_tables = [
        (0, 0, 0, 0),
        (1, 1, 1, 1),
        (0, 1, 1, 0),  # XOR
        (0, 0, 1, 1),  # y=c (since idx=2c+d)
        (0, 1, 0, 1),  # y=d
        (1, 0, 0, 1),  # XNOR? actually for cd:00->1,01->0,10->0,11->1
    ]

    for table in test_tables:
        cnf = CNFBuilder()
        c = cnf.new_var("c")
        d = cnf.new_var("d")
        v0 = cnf.new_var("v0")
        v1 = cnf.new_var("v1")
        v2 = cnf.new_var("v2")
        v3 = cnf.new_var("v3")
        y = cnf.new_var("y")
        lut2(cnf, c, d, [v0, v1, v2, v3], y)

        # Fix v bits
        assumptions_base = [
            lit_for_value(v0, table[0]),
            lit_for_value(v1, table[1]),
            lit_for_value(v2, table[2]),
            lit_for_value(v3, table[3]),
        ]

        for cv in [0, 1]:
            for dv in [0, 1]:
                idx = 2 * cv + dv
                expected = table[idx]
                sat = solve_sat(
                    cnf,
                    assumptions=assumptions_base
                    + [lit_for_value(c, cv), lit_for_value(d, dv), lit_for_value(y, 1 - expected)],
                )
                if sat:
                    raise AssertionError(
                        f"LUT2 mapping failed for table={table}, c={cv}, d={dv}: "
                        f"y can be {1-expected} but expected {expected} (idx={idx})"
                    )


def main():
    solver_name = pick_solver_name()
    print(f"[INFO] Using SAT solver backend: {solver_name}")

    # NOT
    assert_gate_truth_table_1in(
        gate_not,
        truth={0: 1, 1: 0},
        gate_name="NOT",
    )
    print("[OK] NOT")

    # AND
    assert_gate_truth_table_2in(
        gate_and,
        truth={(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1},
        gate_name="AND",
    )
    print("[OK] AND")

    # OR
    assert_gate_truth_table_2in(
        gate_or,
        truth={(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 1},
        gate_name="OR",
    )
    print("[OK] OR")

    # XOR
    assert_gate_truth_table_2in(
        gate_xor,
        truth={(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 0},
        gate_name="XOR",
    )
    print("[OK] XOR")

    # MUX
    assert_mux_truth_table()
    print("[OK] MUX")

    # LUT2
    assert_lut2_mapping()
    print("[OK] LUT2 mapping")

    print("\n[SUCCESS] Phase 2 CNF encodings validated.")


if __name__ == "__main__":
    main()
