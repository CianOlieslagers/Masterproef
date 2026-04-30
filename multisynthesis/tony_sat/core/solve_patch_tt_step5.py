#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from pysat.solvers import Solver


def bits_to_hex16(vbits: List[int]) -> str:
    val = 0
    for i, b in enumerate(vbits):
        val |= (int(b) & 1) << i
    return f"{val:04x}"


def mval(mset: set[int], var: int) -> int:
    return 1 if var in mset else 0


def lit(v: int, bit: int) -> int:
    return v if bit == 1 else -v


def sat_with(solver_name: str, cnf: List[List[int]], ass: List[int]) -> bool:
    ok, _ = solve_with_assumptions(solver_name, cnf, ass)
    return ok


def row_ass_from_bits(xs: List[int], r: int) -> List[int]:
    bits = [(r >> i) & 1 for i in range(4)]
    return [lit(x, b) for x, b in zip(xs, bits)]


def extract_ce_pi_assignment(name2var: Dict[str, int], model: List[int]) -> Dict[str, int]:
    mset = set(model)
    pis = sorted(k for k in name2var if k.startswith("S__pi"))
    ce: Dict[str, int] = {}
    for sk in pis:
        pin = sk[len("S__"):]
        ce[pin] = 1 if name2var[sk] in mset else 0
    return ce


def solve_with_assumptions(
    solver_name: str,
    cnf: List[List[int]],
    assumptions: List[int],
) -> Tuple[bool, Optional[List[int]]]:
    with Solver(name=solver_name) as s:
        for c in cnf:
            s.add_clause(c)
        ok = s.solve(assumptions=assumptions)
        return (ok, s.get_model()) if ok else (False, None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cnfjson", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-iters", type=int, default=1000)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--init-tt", default=None)
    args = ap.parse_args()

    j = json.loads(Path(args.cnfjson).read_text())
    cnf = j["clauses_dimacs"]
    diff = int(j["diff_or_var"])
    solver_name = j.get("solver", "glucose4")
    patch_luts = list(j.get("patch_luts") or [])
    cutpoints = list(j.get("cutpoints") or [])
    name2var: Dict[str, int] = j["name2var"]

    T = json.loads(Path(j["target"]).read_text())

    tt_vars = {
        lut: [int(name2var[f"TT__{lut}__{r}"]) for r in range(16)]
        for lut in patch_luts
    }

    xor_vars = {cp: int(name2var[f"xor__{cp}"]) for cp in cutpoints}

    locked: Dict[Tuple[str, int], int] = {}
    trail: List[List[Tuple[Tuple[str, int], Optional[int], int]]] = []
    tried: Dict[Tuple[str, int], int] = {}

    def tt_lock_assumptions():
        return [lit(tt_vars[l][r], b) for (l, r), b in locked.items()]

    def t_var(net: str) -> int:
        return int(name2var[f"T__{net}"])

    def trail_push_level():
        trail.append([])

    def trail_record_set(key, new):
        old = locked.get(key)
        trail[-1].append((key, old, new))
        locked[key] = new
        tried[key] = tried.get(key, 0) | (1 << new)

    def trail_pop_undo_level():
        if not trail:
            return []
        changes = trail.pop()
        for key, old, _ in reversed(changes):
            if old is None:
                locked.pop(key, None)
            else:
                locked[key] = old
        return changes

    def backtrack_one(reason, verbose=False):
        while True:
            changes = trail_pop_undo_level()
            if not changes:
                return False
            for key, _, new in reversed(changes):
                other = 1 - new
                if tried.get(key, 0) & (1 << other):
                    continue
                trail_push_level()
                trail_record_set(key, other)
                if verbose:
                    print(f"[BACKTRACK] {reason}: flip {key} -> {other}")
                return True

    it = 0
    seen_states = set()

    while True:
        it += 1
        if it > args.max_iters:
            raise SystemExit("Max iterations reached")

        ok_ce, m_ce = solve_with_assumptions(
            solver_name, cnf, [diff] + tt_lock_assumptions()
        )
        if not ok_ce:
            break

        mset_ce = set(m_ce)
        ce = extract_ce_pi_assignment(name2var, m_ce)

        bad_cp = next(cp for cp in cutpoints if xor_vars[cp] in mset_ce)

        pins = T["luts"][bad_cp]["netlist"]["lut_inputs_ordered"]
        xs = [t_var(n) for n in pins]
        r = sum(((x in mset_ce) << i) for i, x in enumerate(xs))

        sv_cp = int(name2var[f"S__{bad_cp}"])
        required = mval(mset_ce, sv_cp)

        repair_luts = [bad_cp] if bad_cp in tt_vars else [
            n for n in pins if n in tt_vars
        ]

        state = (bad_cp, required, tuple(repair_luts), tuple(sorted(locked.items())))
        if state in seen_states:
            if not backtrack_one("cycle", args.verbose):
                raise SystemExit("Stuck")
            continue
        seen_states.add(state)

        ass_base = [-diff] + tt_lock_assumptions()
        for pin, b in ce.items():
            ass_base += [
                lit(int(name2var[f"S__{pin}"]), b),
                lit(int(name2var[f"T__{pin}"]), b),
            ]

        ok_rep, m_rep = solve_with_assumptions(
            solver_name,
            cnf,
            ass_base + [lit(sv_cp, required), -xor_vars[bad_cp]],
        )

        if not ok_rep:
            if not backtrack_one("unsat", args.verbose):
                raise SystemExit("UNSAT")
            continue

        mset_rep = set(m_rep)
        ass_rows = []
        repair_rows = []

        for rlut in repair_luts:
            pins_rlut = T["luts"][rlut]["netlist"]["lut_inputs_ordered"]
            xs_rlut = [t_var(n) for n in pins_rlut]
            r_rlut = sum(((x in mset_rep) << i) for i, x in enumerate(xs_rlut))
            ass_rows += row_ass_from_bits(xs_rlut, r_rlut)
            repair_rows.append((rlut, r_rlut))

        ok_rep2, m_rep2 = solve_with_assumptions(
            solver_name,
            cnf,
            ass_base + ass_rows + [lit(sv_cp, required), -xor_vars[bad_cp]],
        )

        if not ok_rep2:
            if not backtrack_one("row-unsat", args.verbose):
                raise SystemExit("UNSAT")
            continue

        trail_push_level()
        mset_rep2 = set(m_rep2)
        for rlut, r_rlut in repair_rows:
            bit = 1 if tt_vars[rlut][r_rlut] in mset_rep2 else 0
            trail_record_set((rlut, r_rlut), bit)
            print(f"[LOCK] {rlut} row {r_rlut} := {bit}")

    out = {
        "iters": it - 1,
        "locked_bits": [
            {"lut": l, "row": r, "bit": b} for (l, r), b in locked.items()
        ],
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print("[OK] Wrote", args.out)


if __name__ == "__main__":
    main()
