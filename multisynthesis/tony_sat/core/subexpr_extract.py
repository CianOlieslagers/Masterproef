#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Optional


# ----------------------------
# Data structs
# ----------------------------

@dataclass
class SubExpr:
    node: int
    func_hex: str
    support_leaf_ids: List[int]
    support_pin_idx: List[int]
    support_nets: List[str]
    support_size: int


@dataclass
class DstSubExprReport:
    dst: str
    lut_root: int
    leaves: List[int]
    pins: List[str]
    subexprs: List[SubExpr]
    notes: List[str]


# ----------------------------
# Helpers
# ----------------------------

def load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())

def build_nodefunc_map(node_functions: Any) -> Dict[int, str]:
    """
    node_functions is expected: [{"node": <int>, "func_hex": <str>}, ...]
    """
    m: Dict[int, str] = {}
    if not isinstance(node_functions, list):
        return m
    for e in node_functions:
        if not isinstance(e, dict):
            continue
        n = e.get("node")
        h = e.get("func_hex")
        if isinstance(n, int) and isinstance(h, str):
            m[n] = h
    return m

def lit_node_id(lit: int) -> int:
    # AIGER literal -> node id
    return abs(int(lit)) // 2

def compute_support(
    aig_and: Dict[str, List[int]],
    root_node: int,
    leaf_set: Set[int],
) -> Set[int]:
    """
    Return set of leaf node IDs reachable from root_node in the cone.
    Traversal uses aig_and mapping for AND nodes. If a node is in leaf_set: stop.
    If node has no AND entry and is not a leaf: we stop as 'unknown primary' (shouldn’t happen if cones are consistent).
    """
    supp: Set[int] = set()
    stack = [root_node]
    seen: Set[int] = set()

    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)

        if n in leaf_set:
            supp.add(n)
            continue

        row = aig_and.get(str(n))
        if row is None:
            # Not an AND node in stored graph (could be a leaf we missed, or constant/PI not in leaf_set)
            # We don't add it to support because it’s not one of the 4 LUT leaves.
            continue

        rhs0, rhs1 = row
        stack.append(lit_node_id(rhs0))
        stack.append(lit_node_id(rhs1))

    return supp


def extract_subexprs_for_dst(data: Dict[str, Any], dst_key: str, include_root: bool = True) -> DstSubExprReport:
    luts = data["luts"]
    aig = data["aig_graph"]
    aig_and: Dict[str, List[int]] = aig.get("and", {}) or {}

    dst = luts[dst_key]
    lut_root = int(dst["lut_root"])
    leaves = [int(x) for x in (dst.get("leaves") or [])]
    leaf_set = set(leaves)

    netlist = (dst.get("netlist") or {})
    pins = (netlist.get("lut_inputs_ordered") or [])
    if not isinstance(pins, list) or len(pins) != 4:
        pins = []
    # pin index = position in pins list (x0..x3)

    nodefunc = build_nodefunc_map(dst.get("node_functions"))

    # Candidate nodes: internal_nodes (+ optionally root)
    internal = [int(x) for x in (dst.get("internal_nodes") or [])]
    candidates = internal[:]
    if include_root and lut_root not in candidates:
        candidates.append(lut_root)

    subexprs: List[SubExpr] = []
    notes: List[str] = []

    for n in sorted(candidates):
        h = nodefunc.get(n)
        if h is None:
            # If this happens: your node_functions list is incomplete for this dst cone.
            notes.append(f"missing_func_hex_for_node:{n}")
            continue

        supp_leaf_ids = sorted(compute_support(aig_and, n, leaf_set))
        # Map leaf IDs to pin indices based on position in dst.leaves list
        # ASSUMPTION: dst.leaves order corresponds to dst truth table variable order (same order used by node_functions).
        pin_idx = [leaves.index(x) for x in supp_leaf_ids if x in leaf_set]

        supp_nets: List[str] = []
        if pins:
            for i in pin_idx:
                if 0 <= i < len(pins):
                    supp_nets.append(str(pins[i]))

        subexprs.append(
            SubExpr(
                node=n,
                func_hex=h,
                support_leaf_ids=supp_leaf_ids,
                support_pin_idx=pin_idx,
                support_nets=supp_nets,
                support_size=len(supp_leaf_ids),
            )
        )

    return DstSubExprReport(
        dst=dst_key,
        lut_root=lut_root,
        leaves=leaves,
        pins=pins,
        subexprs=subexprs,
        notes=notes,
    )


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only-dsts-in-connections", action="store_true",
                    help="Only extract for dst LUTs that appear in data['connections']")
    args = ap.parse_args()

    data = load_json(args.json)

    luts = data.get("luts")
    if not isinstance(luts, dict):
        raise RuntimeError("JSON missing top-level 'luts' dict")

    dst_keys: Set[str] = set()
    if args.only_dsts_in_connections:
        conns = data.get("connections") or []
        for c in conns:
            dst = (c.get("dst") or {}).get("lut_name")
            if isinstance(dst, str) and dst in luts:
                dst_keys.add(dst)
    else:
        # all LUTs
        dst_keys = set(luts.keys())

    reports: List[Dict[str, Any]] = []
    for dst_key in sorted(dst_keys):
        rep = extract_subexprs_for_dst(data, dst_key, include_root=True)
        reports.append(asdict(rep))

    out_obj = {
        "json": args.json,
        "reports": reports,
    }
    Path(args.out).write_text(json.dumps(out_obj, indent=2))
    print("=== SUBEXPR EXTRACT (dst cones) ===")
    print("Input :", args.json)
    print("Output:", args.out)
    print("DSTs  :", len(reports))

if __name__ == "__main__":
    main()
