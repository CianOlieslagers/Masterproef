# tony_sat/core/dc_blif.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

from pysat.solvers import Solver

from tony_sat.core.blif_parser import parse_blif, BlifDesign
from tony_sat.core.blif_to_cnf import build_cnf_from_blif
from tony_sat.core.miter_blif import build_miter


# Reuse the same solver selection style you already use elsewhere
SolverCandidates = ["cadical", "glucose4", "glucose3", "minisat22", "minicard"]


def pick_solver_name() -> str:
    for name in SolverCandidates:
        try:
            s = Solver(name=name)
            s.delete()
            return name
        except Exception:
            continue
    raise RuntimeError("No PySAT solver backend available (cadical/glucose/minisat).")


def find_lut_fanins(design: BlifDesign, lut_name: str) -> List[str]:
    for nb in design.names:
        if nb.output == lut_name:
            return list(nb.fanins)
    raise KeyError(f"LUT '{lut_name}' not found in BLIF (.names ... {lut_name}).")


def row_to_bits_lsb_first(row: int, k: int = 4) -> List[int]:
    """
    Return [b0,b1,b2,b3] where b0 is LSB.
    """
    return [(row >> i) & 1 for i in range(k)]


def add_row_constraints(
    clauses: List[List[int]],
    net2var: Dict[str, int],
    prefix: str,
    pit_fanins: List[str],
    row: int,
) -> None:
    """
    Add unit clauses to force pit fanins to match 'row'.
    Convention: pit_fanins are in BLIF order. We assume BLIF order corresponds
    to LSB->MSB used earlier in cube/tt16 matching.

    So: fanin[0] = bit0 (LSB), fanin[1] = bit1, ...
    """
    bits = row_to_bits_lsb_first(row, k=len(pit_fanins))
    for net, bit in zip(pit_fanins, bits):
        key = f"{prefix}{net}"
        if key not in net2var:
            raise KeyError(f"Net '{key}' not found in net2var (prefix mismatch?)")
        var = net2var[key]
        clauses.append([var if bit == 1 else -var])


@dataclass
class RowClassResult:
    status: str  # "UNREACHABLE" | "DONT_CARE" | "CARE"
    reachable: bool
    observable: bool
    model: Optional[Dict[str, int]] = None  # optional: assignment for pit fanins / inputs


def sat_check(clauses: List[List[int]], var_count: int) -> Tuple[bool, Optional[List[int]]]:
    solver_name = pick_solver_name()
    with Solver(name=solver_name) as s:
        for cl in clauses:
            s.add_clause(cl)
        sat = s.solve()
        if not sat:
            return False, None
        model = s.get_model()  # list of signed ints
        return True, model


def classify_row(
    blif_path: str,
    pit_lut: str,
    row: int,
) -> RowClassResult:
    design = parse_blif(blif_path)
    pit_fanins = find_lut_fanins(design, pit_lut)
    k = len(pit_fanins)
    if not (0 <= row < (1 << k)):
        raise ValueError(f"row must be in [0, { (1<<k)-1 }] for pit with {k} fanins, got {row}")

    # -------------------------
    # A) Reachability on ORIG
    # -------------------------
    orig = build_cnf_from_blif(design)

    reach_clauses = list(orig.cnf.clauses)
    add_row_constraints(reach_clauses, orig.cnf.name2var, prefix="", pit_fanins=pit_fanins, row=row)

    sat_reach, model_reach = sat_check(reach_clauses, orig.cnf.var_count)
    if not sat_reach:
        return RowClassResult(status="UNREACHABLE", reachable=False, observable=False, model=None)

    # -------------------------
    # B) Observability on MITER
    # diff=1 + pit inputs fixed
    # -------------------------
    mcnf, diff = build_miter(design, pit_lut=pit_lut, row=row)

    obs_clauses = list(mcnf.clauses)

    # Force pit inputs in BOTH circuits: o__ and m__
    add_row_constraints(obs_clauses, mcnf.name2var, prefix="o__", pit_fanins=pit_fanins, row=row)
    add_row_constraints(obs_clauses, mcnf.name2var, prefix="m__", pit_fanins=pit_fanins, row=row)

    # Force diff = 1
    obs_clauses.append([diff])

    sat_obs, model_obs = sat_check(obs_clauses, mcnf.var_count)
    if not sat_obs:
        return RowClassResult(status="DONT_CARE", reachable=True, observable=False, model=None)

    return RowClassResult(status="CARE", reachable=True, observable=True, model=None)


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    ap.add_argument("--pit", required=True)
    ap.add_argument("--row", required=True, type=int)
    args = ap.parse_args()

    res = classify_row(args.blif, args.pit, args.row)
    print(json.dumps({
        "pit": args.pit,
        "row": args.row,
        "status": res.status,
        "reachable": res.reachable,
        "observable": res.observable,
    }, indent=2))
