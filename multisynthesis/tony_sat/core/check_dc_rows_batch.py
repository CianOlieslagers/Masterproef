#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from pysat.solvers import Solver

from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_gates import gate_and, gate_xor
from tony_sat.core.cnf_lut import lut4

SolverName = "glucose4"


# ----------------------------
# Bit helpers
# ----------------------------
def hex16_to_bits(func_hex: str) -> List[int]:
    """Return 16 bits v[0..15], where v[i] is bit i (LSB-first)."""
    s = func_hex.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    val = int(s, 16)
    return [(val >> i) & 1 for i in range(16)]


def bits_to_hex16(vbits: List[int]) -> str:
    val = 0
    for i, b in enumerate(vbits):
        val |= (b & 1) << i
    return f"{val:04x}"


def idx_to_bits4(idx: int) -> Tuple[int, int, int, int]:
    # x0 MSB ... x3 LSB (consistent with lut4 idx = 8*x0 + 4*x1 + 2*x2 + x3)
    return ((idx >> 3) & 1, (idx >> 2) & 1, (idx >> 1) & 1, (idx >> 0) & 1)


# ----------------------------
# AIG literal to CNF literal
# ----------------------------
def cnf_lit_for_aig_lit(cnf: CNFBuilder, node_var: Dict[int, int], aig_lit: int, const_true_var: int) -> int:
    """
    AIGER literal semantics:
      - 0 = const0
      - 1 = const1
      - even = positive node (lit//2)
      - odd  = inverted node (lit//2) with negation
    Return a CNF literal (signed int).
    """
    if aig_lit == 0:
        return -const_true_var  # false
    if aig_lit == 1:
        return const_true_var   # true

    nid = aig_lit // 2
    inv = (aig_lit & 1) == 1

    # If this node wasn't listed in the cone set, treat it as a free boundary input.
    if nid not in node_var:
        node_var[nid] = cnf.new_var(f"n{nid}")

    v = node_var[nid]
    return -v if inv else v


# ----------------------------
# Build CNF for one pit cone equivalence check
# ----------------------------
def build_cone_miter_cnf(
    data: Dict[str, Any],
    pit_key: str,
    vbits_override: Optional[List[int]] = None,
) -> Tuple[CNFBuilder, int]:
    """
    Build CNF that asserts diff = 1 where:
      Y = AIG cone output at pit.lut_root
      L = LUT4(v, x0..x3) with x pins = pit.netlist.lut_inputs_ordered mapped to AIG node IDs
      diff = Y XOR L
    Returns (cnf, diff_var).

    Fix vs v1:
      - build a TRANSITIVE fanin-closure of lut_root using aig_graph["and"]
      - ensure LUT pin nodes (x_node_ids) are included (often PIs like node 6)
      - treat missing AND rows as free inputs (PIs / leaves)
    """

    luts = data["luts"]
    pit = luts[pit_key]
    aig = data["aig_graph"]

    # --- map LUT input nets -> AIG node ids (x0..x3 in correct order) ---
    netlist = pit.get("netlist", {}) or {}
    pins: List[str] = netlist.get("lut_inputs_ordered", []) or []
    if len(pins) != 4:
        raise RuntimeError(f"{pit_key}: expected 4 lut_inputs_ordered, got {len(pins)}")

    pi_name_to_node: Dict[str, int] = aig.get("pi_name_to_node", {}) or {}

    def net_to_node_id(net: str) -> int:
        if net.startswith("LUT_"):
            return int(net.split("_")[1])
        if net.startswith("pi"):
            if net not in pi_name_to_node:
                raise RuntimeError(
                    f"Missing PI mapping for net '{net}' (pi_name_to_node has {len(pi_name_to_node)} keys)"
                )
            return int(pi_name_to_node[net])
        # If you later see things like "open"/"gnd"/"vcc", handle them here.
        raise RuntimeError(f"Unknown net name format '{net}' in {pit_key}.netlist.lut_inputs_ordered")

    x_node_ids = [net_to_node_id(n) for n in pins]  # x0..x3 order

    # --- collect required cone nodes: transitive closure from lut_root + LUT pins ---
    lut_root = int(pit["lut_root"])
    ands: Dict[str, List[int]] = aig.get("and", {}) or {}

    required: Set[int] = set()
    required.update(x_node_ids)

    stack: List[int] = [lut_root]
    while stack:
        nid = stack.pop()
        if nid in required:
            continue
        required.add(nid)

        row = ands.get(str(nid))
        if row is None:
            # Not stored as AND => PI/leaf/free variable
            continue

        rhs0, rhs1 = int(row[0]), int(row[1])
        for lit in (rhs0, rhs1):
            if lit in (0, 1):
                continue  # const0/const1
            fin = lit // 2
            if fin not in required:
                stack.append(fin)

    cone_nodes = required

    # --- build CNF ---
    cnf = CNFBuilder()

    # const_true var (we represent const1 by this var, const0 by its negation)
    const_true = cnf.new_var("const_true")
    cnf.add_unit(const_true, True)
    # --- FIXPOINT: ensure closure covers *all* fanins of included AND nodes ---
    changed = True
    while changed:
        changed = False
        for nid in list(cone_nodes):
            row = ands.get(str(nid))
            if row is None:
                continue
            rhs0, rhs1 = int(row[0]), int(row[1])
            for lit in (rhs0, rhs1):
                if lit in (0, 1):
                    continue
                fin = lit // 2
                if fin not in cone_nodes:
                    cone_nodes.add(fin)
                    changed = True


    # CNF vars for each required node
    node_var = {nid: cnf.new_var(f"n{nid}") for nid in sorted(cone_nodes)}
    # Encode AND nodes (only for nodes we have AND definitions for)
    for nid in sorted(cone_nodes):
        row = ands.get(str(nid))
        if row is None:
            continue  # PI/leaf/free var

        rhs0, rhs1 = int(row[0]), int(row[1])
        a = cnf_lit_for_aig_lit(cnf, node_var, rhs0, const_true)
        b = cnf_lit_for_aig_lit(cnf, node_var, rhs1, const_true)
        y = node_var[nid]

        # y <-> (a & b) with literal-aware Tseitin
        cnf.add_clause([-y, a])
        cnf.add_clause([-y, b])
        cnf.add_clause([-a, -b, y])

    # Original cone output
    Y = node_var[lut_root]

    # LUT4 output L with programmable bits
    x_vars = [node_var[nid] for nid in x_node_ids]  # now guaranteed to exist

    # program bits v[0..15]
    if vbits_override is None:
        vbits = hex16_to_bits(pit["func_hex"])
    else:
        vbits = vbits_override

    v_vars = [cnf.new_var(f"v{i}") for i in range(16)]
    for i in range(16):
        cnf.add_unit(v_vars[i], bool(vbits[i]))

    L = cnf.new_var("L_out")
    lut4(cnf, x_vars, v_vars, L, prefix=f"{pit_key}_")

    diff = cnf.new_var("diff")
    gate_xor(cnf, Y, L, diff)

    return cnf, diff


def cone_diff_satisfiable(data: Dict[str, Any], pit_key: str, vbits: List[int]) -> bool:
    cnf, diff = build_cone_miter_cnf(data, pit_key, vbits_override=vbits)
    with Solver(name=SolverName) as s:
        for cl in cnf.clauses:
            s.add_clause(cl)
        # ask for a counterexample: diff == 1
        s.add_clause([diff])
        return s.solve()


# ----------------------------
# Batch driver
# ----------------------------
@dataclass
class DcResult:
    conn_id: Any
    dst: str
    pit: str
    dc_rows: List[int]
    care_rows: List[int]
    num_dc: int
    num_care: int
    func_hex_before: str
    notes: List[str]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="If >0, process only first N pitstop entries")
    args = ap.parse_args()

    data = json.loads(Path(args.json).read_text())
    conns = data.get("connections", []) or []

    results: List[DcResult] = []
    processed = 0

    for c in conns:
        conn_id = c.get("conn_id", None)
        dst_name = (c.get("dst", {}) or {}).get("lut_name", "?")
        pits = c.get("pitstops", []) or []

        for ps in pits:
            if args.limit and processed >= args.limit:
                break
            processed += 1

            pit_name = ps.get("lut_name")
            if not pit_name:
                continue

            notes: List[str] = []
            try:
                pit_lut = data["luts"][pit_name]
                v0 = hex16_to_bits(pit_lut["func_hex"])
            except Exception as e:
                results.append(DcResult(conn_id, dst_name, pit_name or "?", [], [], 0, 0, "????", [f"error_load:{e}"]))
                continue

            dc: List[int] = []
            care: List[int] = []

            for idx in range(16):
                v2 = v0.copy()
                v2[idx] ^= 1

                # SAT? => there exists assignment where cone differs => CARE
                sat = cone_diff_satisfiable(data, pit_name, v2)
                if sat:
                    care.append(idx)
                else:
                    dc.append(idx)

            results.append(
                DcResult(
                    conn_id=conn_id,
                    dst=dst_name,
                    pit=pit_name,
                    dc_rows=dc,
                    care_rows=care,
                    num_dc=len(dc),
                    num_care=len(care),
                    func_hex_before=pit_lut["func_hex"],
                    notes=notes,
                )
            )

        if args.limit and processed >= args.limit:
            break

    out = {
        "json": args.json,
        "solver": SolverName,
        "results": [asdict(r) for r in results],
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print("=== DC ROWS (cone-SAT) batch ===")
    print("Input :", args.json)
    print("Output:", args.out)
    print("Processed pitstop entries:", len(results))


if __name__ == "__main__":
    main()
