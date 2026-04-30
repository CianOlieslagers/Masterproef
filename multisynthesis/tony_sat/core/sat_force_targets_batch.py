#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import deque
from typing import Dict, Iterable, List, Set

from pysat.solvers import Solver

from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_gates import gate_xor
from tony_sat.core.cnf_lut import lut4

SolverName = "glucose4"


# ----------------------------
# Logging helpers
# ----------------------------
def log(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg)

def compute_cone_closure_bounded(
    ands: Dict[str, List[int]],
    roots: List[int],
    stop_nodes: Set[int],
) -> Set[int]:
    """
    Like compute_cone_closure, but do NOT traverse fanins of stop_nodes.
    This is essential for LUT-cones: leaves are boundary inputs, even if they are AND nodes.
    """
    seen: Set[int] = set()
    q = deque(int(r) for r in roots)

    while q:
        nid = q.popleft()
        if nid in seen:
            continue
        seen.add(nid)

        # Boundary: do not expand below leaves
        if nid in stop_nodes:
            continue

        row = ands.get(str(nid))
        if row is None:
            continue

        for lit in row:
            cid = int(lit) // 2
            # Only traverse further if that child is an AND node
            if str(cid) in ands:
                q.append(cid)

    return seen
# ----------------------------
# Hex / bits helpers
# ----------------------------
def hex16_to_bits(h: str) -> List[int]:
    hs = h.lower().strip()
    if hs.startswith("0x"):
        hs = hs[2:]
    val = int(hs, 16)
    return [(val >> i) & 1 for i in range(16)]  # v[0] = LSB


def bits_to_hex16(vbits: List[int]) -> str:
    val = 0
    for i, b in enumerate(vbits):
        val |= (int(b) & 1) << i
    return f"{val:04x}"


def idx_to_bits4(idx: int) -> Tuple[int, int, int, int]:
    # Canon: x0 = LSB ... x3 = MSB
    # idx = x0 + 2*x1 + 4*x2 + 8*x3
    return ((idx >> 0) & 1, (idx >> 1) & 1, (idx >> 2) & 1, (idx >> 3) & 1)


# ----------------------------
# AIG literal -> CNF literal
# ----------------------------
def cnf_lit_for_aig_lit(
    cnf: CNFBuilder,
    node_var: Dict[int, int],
    aig_lit: int,
    const_true_var: int
) -> int:
    if aig_lit == 0:
        return -const_true_var  # false
    if aig_lit == 1:
        return const_true_var   # true

    nid = aig_lit // 2
    inv = (aig_lit & 1) == 1

    if nid not in node_var:
        node_var[nid] = cnf.new_var(f"n{nid}")

    v = node_var[nid]
    return -v if inv else v


# ----------------------------
# Cone CNF build
# ----------------------------
def aig_lit_to_nid(aig_lit: int) -> Optional[int]:
    if aig_lit in (0, 1):
        return None
    return int(aig_lit // 2)


def compute_cone_closure(aig_and: Dict[str, List[int]], roots: List[int]) -> Set[int]:
    seen: Set[int] = set()
    stack: List[int] = list(roots)

    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)

        row = aig_and.get(str(n))
        if row is None:
            continue

        rhs0, rhs1 = int(row[0]), int(row[1])
        for lit in (rhs0, rhs1):
            nid = aig_lit_to_nid(lit)
            if nid is not None and nid not in seen:
                stack.append(nid)

    return seen


def build_pit_cone_cnf(
    data: Dict[str, Any],
    pit_key: str
) -> Tuple[CNFBuilder, Dict[int, int], List[int], int, List[int], int]:
    """
    Returns:
      cnf, node_var, x_vars, Y, x_node_ids, lut_root
    """
    luts = data["luts"]
    pit = luts[pit_key]
    aig = data["aig_graph"]

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
                raise RuntimeError(f"Missing PI mapping for net '{net}'")
            return int(pi_name_to_node[net])
        raise RuntimeError(f"Unknown net name format '{net}' in {pit_key}.netlist.lut_inputs_ordered")

    # x0..x3 node IDs in EXACT pin order
    x_node_ids = [net_to_node_id(n) for n in pins]

    lut_root = int(pit["lut_root"])
    leaves = [int(n) for n in pit.get("leaves", [])]

    ands: Dict[str, List[int]] = aig.get("and", {}) or {}

    # LUT boundary: do not expand below leaves
    stop_nodes = set(leaves)

    # ✅ STRICT: closure ONLY from lut_root, bounded by leaves
    closure = compute_cone_closure_bounded(
        ands,
        roots=[lut_root],
        stop_nodes=stop_nodes,
    )

    # ✅ STRICT cone nodes = closure + leaves + root
    cone_nodes = set(closure) | set(leaves) | {lut_root}

    cnf = CNFBuilder()

    const_true = cnf.new_var("const_true")
    cnf.add_unit(const_true, True)

    node_var: Dict[int, int] = {}
    for nid in sorted(cone_nodes):
        node_var[nid] = cnf.new_var(f"n{nid}")

    # Encode AND nodes, but never constrain leaves (=boundary inputs)
    for nid in sorted(cone_nodes):
        if nid in stop_nodes:
            continue

        row = ands.get(str(nid))
        if row is None:
            continue

        rhs0, rhs1 = int(row[0]), int(row[1])
        a = cnf_lit_for_aig_lit(cnf, node_var, rhs0, const_true)
        b = cnf_lit_for_aig_lit(cnf, node_var, rhs1, const_true)
        y = node_var[nid]
        cnf.add_clause([-y, a])
        cnf.add_clause([-y, b])
        cnf.add_clause([-a, -b, y])

    # Ensure x vars exist (they should be leaves or PIs)
    for nid in x_node_ids:
        if nid not in node_var:
            node_var[nid] = cnf.new_var(f"n{nid}")
    x_vars = [node_var[nid] for nid in x_node_ids]

    if lut_root not in node_var:
        node_var[lut_root] = cnf.new_var(f"n{lut_root}")
    Y = node_var[lut_root]

    return cnf, node_var, x_vars, Y, x_node_ids, lut_root


def solve_sat(cnf: CNFBuilder, assumptions: List[int]) -> bool:
    with Solver(name=SolverName) as s:
        for cl in cnf.clauses:
            s.add_clause(cl)
        return s.solve(assumptions=assumptions)

def get_super_lut_entry(S: dict, lut_name: str, lut_root: int | None = None) -> dict:
    luts = S.get("luts")
    if isinstance(luts, dict):
        if lut_name in luts and isinstance(luts[lut_name], dict):
            return luts[lut_name]
        if lut_root is not None:
            for v in luts.values():
                if isinstance(v, dict) and v.get("lut_root") == lut_root:
                    return v
    elif isinstance(luts, list):
        # oude/andere format fallback
        for v in luts:
            if isinstance(v, dict) and (v.get("lut_name") == lut_name or (lut_root is not None and v.get("lut_root") == lut_root)):
                return v
    raise KeyError(f"Could not find LUT entry for {lut_name} (root={lut_root}) in super json")


def funcbit_direct(func_hex: str, row: int) -> int:
    tt = int(func_hex, 16) & 0xFFFF
    return (tt >> row) & 1



def cone_row_info_split(
    cnf: CNFBuilder,
    x_vars: List[int],
    Y: int
) -> Tuple[List[int], List[int], List[int], Dict[int, int], List[str]]:
    """
    Returns:
      reachable_rows,
      dc_unreach_rows,
      dc_x_rows,
      care_value[idx] (only for CARE),
      notes
    """
    reachable: List[int] = []
    dc_unreach: List[int] = []
    dc_x: List[int] = []
    care_value: Dict[int, int] = {}
    notes: List[str] = []

    for idx in range(16):
        b0, b1, b2, b3 = idx_to_bits4(idx)
        ass = [
            (x_vars[0] if b0 else -x_vars[0]),
            (x_vars[1] if b1 else -x_vars[1]),
            (x_vars[2] if b2 else -x_vars[2]),
            (x_vars[3] if b3 else -x_vars[3]),
        ]

        if not solve_sat(cnf, ass):
            dc_unreach.append(idx)
            continue

        reachable.append(idx)

        sat1 = solve_sat(cnf, ass + [Y])
        sat0 = solve_sat(cnf, ass + [-Y])

        if sat1 and sat0:
            dc_x.append(idx)
            continue

        if (not sat1) and (not sat0):
            notes.append(f"row {idx}: ERROR reachable-but-Y-inconsistent")
            continue

        care_value[idx] = 1 if sat1 else 0

    return reachable, dc_unreach, dc_x, care_value, notes


def dump_row_table(
    pit: str,
    pit_pins: List[str],
    func_bits: List[int],
    care_value: Dict[int, int],
    dc_unreach: List[int],
    dc_x: List[int],
    verbose: bool
) -> None:
    if not verbose:
        return
    print(f"[DBG] Row table for {pit} pins={pit_pins}")
    print(" idx | x0x1x2x3 | type      | coneY | funcBit | mismatch")
    print("-----+----------+-----------+-------+---------+---------")
    for idx in range(16):
        x0, x1, x2, x3 = idx_to_bits4(idx)
        if idx in dc_unreach:
            rtype = "DC_unreach"
            coneY = "-"
        elif idx in dc_x:
            rtype = "DC_x"
            coneY = "X"
        elif idx in care_value:
            rtype = "CARE"
            coneY = str(care_value[idx])
        else:
            rtype = "???"
            coneY = "?"
        fb = func_bits[idx]
        mm = ""
        if idx in care_value and fb != care_value[idx]:
            mm = "YES"
        print(f" {idx:>3} |  {x0}{x1}{x2}{x3}   | {rtype:<9} | {coneY:<5} |   {fb:<5} | {mm}")
    print("")


# ----------------------------
# Target evaluation
# ----------------------------
def target_bit_for_pit_row(
    target_func_hex: str,
    dst_pins: List[str],
    support_nets: List[str],
    pit_pins: List[str],
    pit_row_idx: int,
) -> int:
    tt = hex16_to_bits(target_func_hex)
    pit_bits = idx_to_bits4(pit_row_idx)

    dst_bits = [0, 0, 0, 0]
    for i, dst_net in enumerate(dst_pins):
        if dst_net not in support_nets:
            dst_bits[i] = 0
            continue
        j = pit_pins.index(dst_net)
        dst_bits[i] = pit_bits[j]

    idx = dst_bits[0] + 2*dst_bits[1] + 4*dst_bits[2] + 8*dst_bits[3]    
    return int(tt[idx])


# ----------------------------
# Miter validate
# ----------------------------
def miter_diff_sat(data: Dict[str, Any], pit_key: str, vbits: List[int]) -> bool:
    cnf, node_var, x_vars, Y, _, _ = build_pit_cone_cnf(data, pit_key)

    v_vars = [cnf.new_var(f"v{i}") for i in range(16)]
    for i in range(16):
        cnf.add_unit(v_vars[i], bool(vbits[i]))

    L = cnf.new_var("L_out")
    lut4(cnf, x_vars, v_vars, L, prefix=f"{pit_key}_")

    diff = cnf.new_var("diff")
    gate_xor(cnf, Y, L, diff)

    with Solver(name=SolverName) as s:
        for cl in cnf.clauses:
            s.add_clause(cl)
        return s.solve(assumptions=[diff])  # SAT => counterexample exists


# ----------------------------
# I/O
# ----------------------------
def load_json(p: str) -> Any:
    return json.loads(Path(p).read_text())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--super", required=True)
    ap.add_argument("--targets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-per-combo", type=int, default=10)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--debug-pit", default=None, help="Only dump row table for this pit (e.g. LUT_11)")
    args = ap.parse_args()

    data = load_json(args.super)
    targets = load_json(args.targets)

    combos = targets.get("results") if isinstance(targets, dict) else targets
    if not isinstance(combos, list):
        raise RuntimeError("targets file must contain a list or a dict with key 'results'")

    if args.verbose:
        print("[INFO] === SAT FORCE TARGETS (debugged) ===")
        print(f"[INFO] Super   : {args.super}")
        print(f"[INFO] Targets : {args.targets}")
        print(f"[INFO] Solver  : {SolverName}")
        print(f"[INFO] Combos  : {len(combos)}")

    out_results: List[Dict[str, Any]] = []
    ok = 0

    for idx_combo, c in enumerate(combos, start=1):
        dst = c.get("dst")
        pit = c.get("pit")

        net_link = c.get("net_link") or {}
        dst_input_pin = net_link.get("dst_input_pin") if isinstance(net_link, dict) else None

        entry: Dict[str, Any] = {
            "dst": dst,
            "pit": pit,
            "dst_input_pin": dst_input_pin,
            "success": False,
            "reason": None,
            "chosen_target": None,
            "patched_hex": None,
            "stats": {},
            "notes": [],
        }

        if args.verbose:
            print(f"[INFO] [{idx_combo}/{len(combos)}] combo dst={dst} pit={pit}")

        if not isinstance(dst, str) or not isinstance(pit, str):
            entry["reason"] = "missing_dst_or_pit"
            out_results.append(entry)
            continue

        pit_lut = (data.get("luts") or {}).get(pit) or {}
        dst_lut = (data.get("luts") or {}).get(dst) or {}
        pit_pins = ((pit_lut.get("netlist") or {}).get("lut_inputs_ordered") or [])
        dst_pins = ((dst_lut.get("netlist") or {}).get("lut_inputs_ordered") or [])

        if len(pit_pins) != 4 or len(dst_pins) != 4:
            entry["reason"] = "missing_or_bad_pin_lists"
            out_results.append(entry)
            continue

        log(f"[INFO]   pins pit={pit_pins} dst={dst_pins} dst_input_pin={dst_input_pin}", args.verbose)

        # Build cone and row info
        try:
            cnf_cone, node_var, x_vars, Y, x_node_ids, lut_root = build_pit_cone_cnf(data, pit)
            reachable, dc_unreach, dc_x, care_value, notes = cone_row_info_split(cnf_cone, x_vars, Y)
            entry["notes"].extend(notes)
        except Exception as e:
            entry["reason"] = f"cone_build_or_query_failed: {e}"
            out_results.append(entry)
            continue

        entry["stats"] = {
            "reachable": len(reachable),
            "care": len(care_value),
            "dc_unreach": len(dc_unreach),
            "dc_x": len(dc_x),
        }
        log(f"[INFO]   rows: CARE={len(care_value)} DC_unreach={len(dc_unreach)} DC_x={len(dc_x)}", args.verbose)

        # Compare original func_hex on CARE rows (diagnostic)
        orig_hex = str(pit_lut.get("func_hex", "0000"))
        orig_bits = hex16_to_bits(orig_hex)

        mism = [r for r, val in care_value.items() if orig_bits[r] != val]
        if mism:
            log(f"[WARN] {pit}: original func_hex mismatches CARE rows at {mism}", True)
            # Dump table for debug pits or if verbose
            if args.debug_pit is None or args.debug_pit == pit:
                dump_row_table(pit, pit_pins, orig_bits, care_value, dc_unreach, dc_x, True)

            # This is a fundamental inconsistency -> skip forcing for now
            entry["reason"] = "orig_func_hex_mismatch_care_rows (indexing/pin-order/model issue)"
            out_results.append(entry)
            continue

        # Start vbits from original
        vbits = orig_bits.copy()

        # Enforce cone-correctness on CARE rows (should already match now)
        for r, val in care_value.items():
            vbits[r] = int(val)

        # Choose a target
        target_list = c.get("targets") or c.get("subexpr_targets") or c.get("target_subexprs") or []
        if not isinstance(target_list, list) or len(target_list) == 0:
            entry["reason"] = "no_targets_for_combo"
            out_results.append(entry)
            continue

        chosen = None
        tried = 0

        for t in target_list:
            if tried >= args.max_per_combo:
                break
            tried += 1

            node = t.get("node")
            func_hex = t.get("func_hex")
            support_pin_idx = t.get("support_pin_idx") or []
            support_nets = t.get("support_nets") or []

            if node is None or not isinstance(func_hex, str):
                continue
            if not isinstance(support_pin_idx, list) or not isinstance(support_nets, list):
                continue

            # Anti-cycle filter
            if isinstance(dst_input_pin, int) and dst_input_pin in support_pin_idx:
                continue

            # All support nets must exist on pit pins
            if any(n not in pit_pins for n in support_nets):
                continue

            chosen = {
                "node": node,
                "func_hex": func_hex,
                "support_pin_idx": support_pin_idx,
                "support_nets": support_nets,
            }
            break

        if chosen is None:
            entry["reason"] = "no_target_passed_filters"
            out_results.append(entry)
            continue

        # PAPER-SAFE forcing: ONLY on unreachable rows (dc_unreach)
        # (dc_x is likely inflated by free boundary vars in cone model)
        try:
            for r in dc_unreach:
                b = target_bit_for_pit_row(
                    target_func_hex=chosen["func_hex"],
                    dst_pins=dst_pins,
                    support_nets=chosen["support_nets"],
                    pit_pins=pit_pins,
                    pit_row_idx=r,
                )
                vbits[r] = b
        except Exception as e:
            entry["reason"] = f"target_eval_failed: {e}"
            out_results.append(entry)
            continue

        # Validate equivalence with miter
        try:
            diff_sat = miter_diff_sat(data, pit, vbits)
        except Exception as e:
            entry["reason"] = f"miter_failed: {e}"
            out_results.append(entry)
            continue

        if diff_sat:
            entry["reason"] = "miter_found_counterexample(diff=1)"
            out_results.append(entry)
            continue

        entry["success"] = True
        entry["chosen_target"] = chosen
        entry["patched_hex"] = bits_to_hex16(vbits)
        ok += 1
        out_results.append(entry)

    out_obj = {
        "super": args.super,
        "targets": args.targets,
        "solver": SolverName,
        "total": len(combos),
        "success": ok,
        "failed": len(combos) - ok,
        "results": out_results,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_obj, indent=2))

    print("[INFO] === DONE ===")
    print(f"[INFO] Output  : {out_path}")
    print(f"[INFO] Total   : {len(combos)}")
    print(f"[INFO] Success : {ok}")
    print(f"[INFO] Failed  : {len(combos) - ok}")


if __name__ == "__main__":
    main()
