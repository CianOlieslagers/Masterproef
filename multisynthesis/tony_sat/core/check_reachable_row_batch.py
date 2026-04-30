#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from pysat.solvers import Solver

from tony_sat.core.cnf_builder import CNFBuilder

SolverName = "glucose4"


# ----------------------------
# Small helpers
# ----------------------------

def idx_to_bits4(idx: int) -> Tuple[int, int, int, int]:
    # x0 MSB ... x3 LSB, consistent with lut4 index = 8*x0 + 4*x1 + 2*x2 + x3
    return ((idx >> 3) & 1, (idx >> 2) & 1, (idx >> 1) & 1, (idx >> 0) & 1)


def cnf_lit_for_aig_lit(node_var: Dict[int, int], aig_lit: int, const_true: int) -> int:
    """
    AIG literal encoding:
      lit=0 => const False
      lit=1 => const True
      lit=2*n     => node n
      lit=2*n + 1 => ~node n
    We implement const True by CNF var const_true fixed to True.
    """
    if aig_lit == 0:
        return -const_true
    if aig_lit == 1:
        return const_true
    nid = aig_lit // 2
    base = node_var[nid]  # must exist
    return base if (aig_lit % 2 == 0) else -base


def build_lutroot_index(luts: Dict[str, Any]) -> Dict[int, str]:
    idx: Dict[int, str] = {}
    for k, v in luts.items():
        if not isinstance(v, dict):
            continue
        r = v.get("lut_root", None)
        if isinstance(r, int):
            if r in idx and idx[r] != k:
                raise ValueError(f"Duplicate lut_root {r}: {idx[r]} and {k}")
            idx[r] = k
    return idx


# ----------------------------
# Mapping: net name -> AIG node id
# ----------------------------

def net_to_node_id(net: str, pi_name_to_node: Dict[str, int]) -> int:
    if net.startswith("LUT_"):
        return int(net.split("_")[1])
    if net.startswith("pi"):
        if net not in pi_name_to_node:
            raise RuntimeError(
                f"Missing PI mapping for '{net}'. "
                f"Known pi_name_to_node keys: {sorted(pi_name_to_node.keys())}"
            )
        return int(pi_name_to_node[net])
    raise RuntimeError(f"Unknown net name format '{net}' (expected LUT_<id> or pi<k>)")


# ----------------------------
# AIG closure for reachability of pit input nets
# ----------------------------

def fanin_closure_for_targets(
    ands: Dict[str, List[int]],
    target_nodes: List[int],
) -> Set[int]:
    """
    Compute transitive fanin closure (node ids) for the given target node ids.
    Includes target nodes, plus all fanins of AND nodes recursively.
    Nodes with no AND row are treated as leaves (stop recursion).
    """
    closure: Set[int] = set(target_nodes)
    stack: List[int] = list(target_nodes)

    while stack:
        nid = stack.pop()
        row = ands.get(str(nid))
        if row is None:
            continue  # leaf / PI / pruned-away node => stop
        rhs0, rhs1 = int(row[0]), int(row[1])
        for lit in (rhs0, rhs1):
            if lit in (0, 1):
                continue
            fin = lit // 2
            if fin not in closure:
                closure.add(fin)
                stack.append(fin)
    return closure


def build_reachability_cnf(
    data: Dict[str, Any],
    pit_key: str,
) -> Tuple[CNFBuilder, List[int], Dict[int, int]]:
    """
    Build CNF for the upstream logic that determines the 4 pit LUT input signals.
    Returns: (cnf, x_vars_in_order, node_var)
      - x_vars_in_order: [x0,x1,x2,x3] CNF vars corresponding to pit.lut_inputs_ordered nets
    """
    luts = data["luts"]
    pit = luts[pit_key]
    aig = data["aig_graph"]

    ands: Dict[str, List[int]] = aig.get("and", {}) or {}
    pi_name_to_node: Dict[str, int] = aig.get("pi_name_to_node", {}) or {}

    netlist = pit.get("netlist", {}) or {}
    pins: List[str] = netlist.get("lut_inputs_ordered", []) or []
    if len(pins) != 4:
        raise RuntimeError(f"{pit_key}: expected 4 lut_inputs_ordered, got {len(pins)}")

    x_node_ids = [net_to_node_id(n, pi_name_to_node) for n in pins]  # x0..x3 node ids

    # Closure of all logic needed to produce these x_node_ids
    nodes = fanin_closure_for_targets(ands, x_node_ids)

    cnf = CNFBuilder()

    const_true = cnf.new_var("const_true")
    cnf.add_unit(const_true, True)

    # Allocate CNF var for every node in closure
    node_var: Dict[int, int] = {}
    for nid in sorted(nodes):
        node_var[nid] = cnf.new_var(f"n{nid}")

    # Encode AND nodes (literal-aware Tseitin)
    for nid in sorted(nodes):
        row = ands.get(str(nid))
        if row is None:
            continue
        rhs0, rhs1 = int(row[0]), int(row[1])

        a = cnf_lit_for_aig_lit(node_var, rhs0, const_true)
        b = cnf_lit_for_aig_lit(node_var, rhs1, const_true)
        y = node_var[nid]

        # y <-> (a & b) with a,b possibly literals
        cnf.add_clause([-y, a])
        cnf.add_clause([-y, b])
        cnf.add_clause([-a, -b, y])

    x_vars = [node_var[nid] for nid in x_node_ids]
    return cnf, x_vars, node_var


def row_reachable(
    base_solver: Solver,
    x_vars: List[int],
    row_idx: int,
) -> bool:
    b0, b1, b2, b3 = idx_to_bits4(row_idx)
    bits = [b0, b1, b2, b3]
    assumptions: List[int] = []
    for v, b in zip(x_vars, bits):
        assumptions.append(v if b == 1 else -v)
    return base_solver.solve(assumptions=assumptions)


# ----------------------------
# Reporting
# ----------------------------

@dataclass
class ReachResult:
    conn_id: Any
    dst: str
    pit: str
    reachable_rows: List[int]
    dc_rows: List[int]          # unreachable rows
    num_reachable: int
    num_dc: int
    func_hex_before: str
    notes: List[str]


# ----------------------------
# Main batch
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="Path to example_big_300.super.sat.v2.json")
    ap.add_argument("--out", required=True, help="Output JSON path")
    ap.add_argument("--limit", type=int, default=0, help="Process only N pitstops (0 = all)")
    args = ap.parse_args()

    p = Path(args.json)
    data = json.loads(p.read_text())

    conns = data.get("connections", []) or []
    if not isinstance(conns, list):
        raise RuntimeError("JSON: 'connections' is not a list")

    results: List[ReachResult] = []
    processed = 0

    for conn in conns:
        conn_id = conn.get("conn_id", None)
        dst_name = (conn.get("dst", {}) or {}).get("lut_name", None)
        if not dst_name:
            continue

        pitstops = conn.get("pitstops", []) or []
        if not isinstance(pitstops, list):
            continue

        for ps in pitstops:
            pit_name = ps.get("lut_name", None)
            if not pit_name:
                continue

            # stop if limit
            if args.limit and processed >= args.limit:
                break

            # Build reachability CNF only for this pit
            notes: List[str] = []
            try:
                cnf, x_vars, _ = build_reachability_cnf(data, pit_name)
            except Exception as e:
                results.append(
                    ReachResult(
                        conn_id=conn_id,
                        dst=str(dst_name),
                        pit=str(pit_name),
                        reachable_rows=[],
                        dc_rows=list(range(16)),
                        num_reachable=0,
                        num_dc=16,
                        func_hex_before=(data["luts"].get(pit_name, {}) or {}).get("func_hex", ""),
                        notes=[f"FAILED_BUILD_CNF: {type(e).__name__}: {e}"],
                    )
                )
                processed += 1
                continue

            # Solve all 16 rows under same base CNF
            reachable: List[int] = []
            with Solver(name=SolverName) as solver:
                for cl in cnf.clauses:
                    solver.add_clause(cl)

                for r in range(16):
                    if row_reachable(solver, x_vars, r):
                        reachable.append(r)

            dc_rows = [r for r in range(16) if r not in set(reachable)]

            pit_func = (data["luts"].get(pit_name, {}) or {}).get("func_hex", "")

            results.append(
                ReachResult(
                    conn_id=conn_id,
                    dst=str(dst_name),
                    pit=str(pit_name),
                    reachable_rows=reachable,
                    dc_rows=dc_rows,
                    num_reachable=len(reachable),
                    num_dc=len(dc_rows),
                    func_hex_before=str(pit_func),
                    notes=notes,
                )
            )

            processed += 1

        if args.limit and processed >= args.limit:
            break

    out_obj = {
        "json": str(p),
        "solver": SolverName,
        "results": [asdict(r) for r in results],
    }

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out_obj, indent=2))

    print("=== REACHABLE/DC ROWS (contextual reachability) batch ===")
    print(f"Input : {p}")
    print(f"Output: {outp}")
    print(f"Processed pitstop entries: {processed}")


if __name__ == "__main__":
    main()
