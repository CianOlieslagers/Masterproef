#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List


# ----------------------------
# Helpers: LUT resolving
# ----------------------------

_LUT_KEY_RE = re.compile(r"^LUT_(\d+)$", re.IGNORECASE)


def normalize_lut_key(s: str) -> Optional[str]:
    """
    If s looks like LUT_123 -> return canonical "LUT_123"
    else None
    """
    m = _LUT_KEY_RE.match(s.strip())
    if not m:
        return None
    return f"LUT_{int(m.group(1))}"


def parse_int_if_possible(s: str) -> Optional[int]:
    s2 = s.strip()
    if s2.isdigit():
        return int(s2)
    return None


def build_lutroot_index(luts: Dict[str, Any]) -> Dict[int, str]:
    """
    Build lut_root -> lut_key mapping.
    Assumes lut_root is unique.
    """
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


def resolve_lut(luts: Dict[str, Any], lutroot_index: Dict[int, str], user_id: str) -> Tuple[str, Dict[str, Any]]:
    """
    user_id can be:
      - "LUT_101" (lut key)
      - "101"     (lut_root)
    """
    # Case 1: LUT_###
    k = normalize_lut_key(user_id)
    if k is not None:
        if k not in luts:
            raise KeyError(f"LUT key not found in JSON: {k}")
        return k, luts[k]

    # Case 2: integer lut_root
    r = parse_int_if_possible(user_id)
    if r is not None:
        if r not in lutroot_index:
            raise KeyError(f"lut_root not found in JSON: {r}")
        key = lutroot_index[r]
        return key, luts[key]

    raise ValueError(f"Cannot parse LUT identifier '{user_id}'. Use LUT_### or numeric lut_root.")


# ----------------------------
# Sanity checks
# ----------------------------

@dataclass
class LutSummary:
    key: str
    lut_root: int
    k: int
    func_hex: str
    inputs_ordered: List[Any]
    rotation_map: Any
    output_net: Any
    leaves_n: int
    internal_n: int
    nodefunc_n: int


def summarize_lut(key: str, lut: Dict[str, Any]) -> LutSummary:
    lut_root = lut.get("lut_root")
    k = lut.get("K")
    func_hex = lut.get("func_hex")

    netlist = lut.get("netlist", {}) or {}
    inputs_ordered = netlist.get("lut_inputs_ordered", [])
    rotation_map = netlist.get("rotation_map", None)
    output_net = netlist.get("output_net", None)

    leaves = lut.get("leaves", []) or []
    internal_nodes = lut.get("internal_nodes", []) or []
    node_functions = lut.get("node_functions", []) or []

    if not isinstance(lut_root, int):
        raise ValueError(f"{key}: lut_root missing or not int")
    if not isinstance(k, int):
        raise ValueError(f"{key}: K missing or not int")
    if not isinstance(func_hex, str):
        raise ValueError(f"{key}: func_hex missing or not str")

    return LutSummary(
        key=key,
        lut_root=lut_root,
        k=k,
        func_hex=func_hex,
        inputs_ordered=list(inputs_ordered) if isinstance(inputs_ordered, list) else [inputs_ordered],
        rotation_map=rotation_map,
        output_net=output_net,
        leaves_n=len(leaves) if isinstance(leaves, list) else 0,
        internal_n=len(internal_nodes) if isinstance(internal_nodes, list) else 0,
        nodefunc_n=len(node_functions) if isinstance(node_functions, list) else 0,
    )


def assert_lut_ready(summary: LutSummary) -> None:
    if summary.k != 4:
        raise RuntimeError(f"{summary.key}: K={summary.k} (v1 supports only K=4)")
    if summary.internal_n == 0 or summary.nodefunc_n == 0:
        raise RuntimeError(
            f"{summary.key}: missing cone structure (internal_nodes={summary.internal_n}, node_functions={summary.nodefunc_n})"
        )


# ----------------------------
# Connection lookup (dst,pit)
# ----------------------------

def find_connection_and_pitlink(data: Dict[str, Any], dst_root: int, pit_root: int) -> Optional[Dict[str, Any]]:
    """
    Search data["connections"] for an entry where dst.lut.lut_root == dst_root
    and one pitstop has pit.lut.lut_root == pit_root.
    Return that pitstop dict (includes net_link) with some context, or None.
    """
    conns = data.get("connections", []) or []
    for conn in conns:
        try:
            dst = conn.get("dst", {})
            dst_lut = (dst.get("lut", {}) or {})
            if dst_lut.get("lut_root") != dst_root:
                continue

            pitstops = conn.get("pitstops", []) or []
            for ps in pitstops:
                pit = ps.get("pit", {})
                pit_lut = (pit.get("lut", {}) or {})
                if pit_lut.get("lut_root") == pit_root:
                    # Return enriched info
                    return {
                        "conn_id": conn.get("conn_id", None),
                        "dst_root": dst_root,
                        "pit_root": pit_root,
                        "net_link": ps.get("net_link", None),
                        "pitstop_entry": ps,
                    }
        except Exception:
            # Defensive: ignore malformed entries in v1
            continue
    return None


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="Path to example_big_300.super.sat.v2.json")
    ap.add_argument("--dst", required=True, help="Destination LUT: LUT_### or lut_root integer")
    ap.add_argument("--pit", required=True, help="Pitstop LUT: LUT_### or lut_root integer")
    args = ap.parse_args()

    p = Path(args.json)
    if not p.exists():
        raise FileNotFoundError(p)

    data = json.loads(p.read_text())

    luts = data.get("luts", None)
    if not isinstance(luts, dict):
        raise RuntimeError("JSON missing top-level 'luts' dict")

    lutroot_index = build_lutroot_index(luts)

    dst_key, dst = resolve_lut(luts, lutroot_index, args.dst)
    pit_key, pit = resolve_lut(luts, lutroot_index, args.pit)

    dst_sum = summarize_lut(dst_key, dst)
    pit_sum = summarize_lut(pit_key, pit)

    print("\n=== FEASIBILITY CHECK v1 (load + sanity) ===")
    print(f"JSON : {p}")
    print("\n[DESTINATION LUT]")
    print(dst_sum)
    print("\n[PITSTOP LUT]")
    print(pit_sum)

    # Hard readiness checks
    assert_lut_ready(dst_sum)
    assert_lut_ready(pit_sum)

    # Connection lookup (optional but useful)
    link = find_connection_and_pitlink(data, dst_sum.lut_root, pit_sum.lut_root)
    print("\n[CONNECTION / NET_LINK]")
    if link is None:
        print("No (dst,pit) pitstop link found in data['connections'] (OK for LUT-only sanity).")
    else:
        net_link = link.get("net_link", None)
        print(f"Found link in conn_id={link.get('conn_id')}")
        print(f"net_link = {net_link}")
        if isinstance(net_link, dict):
            if net_link.get("dst_input_pin") is None and net_link.get("dst_input_net") is None:
                print("WARNING: net_link has dst_input_pin/net = null (later mapping may fail).")

    print("\n[OK] v1 sanity passed. Ready for v2: cone-miter + DC rows + subexpr forcing.")


if __name__ == "__main__":
    main()
