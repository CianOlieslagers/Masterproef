#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# -------------------------
# Helpers
# -------------------------

def load_json(path: str) -> Any:
    return json.loads(Path(path).read_text())

def norm_hex16(h: str) -> str:
    hs = str(h).lower().strip()
    if hs.startswith("0x"):
        hs = hs[2:]
    # tolerate shorter
    return f"{int(hs,16):04x}"

def bits_to_hex16(tt_bits_idx: List[int]) -> str:
    """tt_bits_idx: list length 16, where index = 8*x0+4*x1+2*x2+x3"""
    val = 0
    for idx, b in enumerate(tt_bits_idx):
        val |= (int(b) & 1) << idx
    return f"{val:04x}"

def idx_to_bits4(idx: int) -> Tuple[int,int,int,int]:
    return ((idx>>3)&1, (idx>>2)&1, (idx>>1)&1, (idx>>0)&1)

def lit_to_nid(aig_lit: int) -> Optional[int]:
    if aig_lit in (0,1):
        return None
    return int(aig_lit // 2)

def compute_closure(andtab: Dict[str, List[int]], root: int) -> Set[int]:
    seen: Set[int] = set()
    stack = [root]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        row = andtab.get(str(n))
        if row is None:
            continue
        rhs0, rhs1 = map(int, row)
        for lit in (rhs0, rhs1):
            nid = lit_to_nid(lit)
            if nid is not None and nid not in seen:
                stack.append(nid)
    return seen

# -------------------------
# BLIF parsing
# -------------------------

def parse_blif_names_blocks(blif_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Returns dict: out_name -> { "inputs": [...], "cubes": [(pat,val), ...] }
    Only stores .names blocks.
    """
    lines = Path(blif_path).read_text().splitlines()
    blocks: Dict[str, Dict[str, Any]] = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("#"):
            i += 1
            continue
        if line.startswith(".names"):
            parts = line.split()
            ins = parts[1:-1]
            out = parts[-1]
            cubes: List[Tuple[str,str]] = []
            i += 1
            while i < len(lines):
                l = lines[i].strip()
                if not l or l.startswith("#"):
                    i += 1
                    continue
                if l.startswith("."):
                    break
                # cube line: pattern value
                sp = l.split()
                if len(sp) == 1:
                    # constant format like: ".names new_n0" then "0" or "1"
                    # treat as pattern "" with val sp[0]
                    cubes.append(("", sp[0]))
                else:
                    cubes.append((sp[0], sp[1]))
                i += 1
            blocks[out] = {"inputs": ins, "cubes": cubes}
            continue
        i += 1
    return blocks

def eval_blif_block_to_hex(inputs: List[str], cubes: List[Tuple[str,str]]) -> str:
    """
    Evaluate a .names block (SOP with don't cares) into 16-bit hex.
    Assumes len(inputs)==4.
    Indexing: idx = 8*x0 + 4*x1 + 2*x2 + x3 where x0=inputs[0] ...
    """
    if len(inputs) != 4:
        raise ValueError("only LUT4 supported in this checker")

    def match(pat: str, bits: Tuple[int,int,int,int]) -> bool:
        if pat == "":
            return True
        for ch, b in zip(pat, bits):
            if ch == "-":
                continue
            if int(ch) != b:
                return False
        return True

    tt = [0]*16
    for idx, bits in enumerate(itertools.product([0,1],[0,1],[0,1],[0,1])):
        y = 0
        for pat, val in cubes:
            if val == "1" and match(pat, bits):
                y = 1
                break
            if val == "0" and match(pat, bits):
                y = 0
                break
        tt[idx] = y
    return bits_to_hex16(tt)

# -------------------------
# Main checks
# -------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--super", required=True)
    ap.add_argument("--lut-cones", required=True)
    ap.add_argument("--connections", required=True)
    ap.add_argument("--targets", required=True)
    ap.add_argument("--blif", required=True)
    ap.add_argument("--only-luts", default="", help="comma-separated LUT names to focus (e.g. LUT_11,LUT_36)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    only = set([s.strip() for s in args.only_luts.split(",") if s.strip()])

    superj = load_json(args.super)
    conesj = load_json(args.lut_cones)
    connj = load_json(args.connections)
    targj = load_json(args.targets)
    blif_blocks = parse_blif_names_blocks(args.blif)

    super_luts: Dict[str, Any] = superj.get("luts", {}) or {}
    andtab: Dict[str, List[int]] = (superj.get("aig_graph", {}) or {}).get("and", {}) or {}

    # lut_cones list -> dict by lut_name
    cones_map: Dict[str, Any] = {}
    for e in conesj.get("lut_cones", []) or []:
        cones_map[str(e.get("lut_name"))] = e

    # connections: try to tolerate several formats
    conn_list = connj.get("connections") or connj.get("results") or connj
    if not isinstance(conn_list, list):
        raise RuntimeError("connections file must contain a list or have key 'connections'/'results'")

    conn_pairs = set()
    for e in conn_list:
        dst = e.get("dst") or e.get("dst_lut") or e.get("dst_name")
        pit = e.get("pit") or e.get("pit_lut") or e.get("pit_name")
        if isinstance(dst, str) and isinstance(pit, str):
            conn_pairs.add((dst, pit))

    # targets file
    combos = targj.get("results") if isinstance(targj, dict) else targj
    if not isinstance(combos, list):
        raise RuntimeError("targets file must be list or dict with 'results'")
    targ_pairs = set()
    for c in combos:
        dst = c.get("dst")
        pit = c.get("pit")
        if isinstance(dst, str) and isinstance(pit, str):
            targ_pairs.add((dst, pit))

    print("=== CHECK FLOW CONSISTENCY ===")
    print("super      :", args.super)
    print("lut_cones  :", args.lut_cones)
    print("connections:", args.connections)
    print("targets    :", args.targets)
    print("blif       :", args.blif)
    print("")

    # Check A: combo agreement
    miss_in_conn = sorted(targ_pairs - conn_pairs)
    miss_in_targ = sorted(conn_pairs - targ_pairs)

    print("[A] Combo consistency")
    print(f"  targets combos: {len(targ_pairs)}")
    print(f"  conn combos   : {len(conn_pairs)}")
    print(f"  in targets not in connections: {len(miss_in_conn)}")
    print(f"  in connections not in targets: {len(miss_in_targ)}")
    if args.verbose and miss_in_conn[:10]:
        print("   examples miss_in_conn:", miss_in_conn[:10])
    if args.verbose and miss_in_targ[:10]:
        print("   examples miss_in_targ:", miss_in_targ[:10])
    print("")

    # Check B + C per LUT
    print("[B/C] LUT-level consistency (super vs lut_cones vs blif)")
    problems = 0
    checked = 0

    for lut_name, lut in super_luts.items():
        if only and lut_name not in only:
            continue
        checked += 1

        # ---- super fields
        sup_root = int(lut.get("lut_root", -1))
        sup_hex  = norm_hex16(lut.get("func_hex", "0"))
        sup_pins = ((lut.get("netlist") or {}).get("lut_inputs_ordered") or [])

        sup_leaves = set(map(int, lut.get("leaves", []) or []))
        sup_internal = set(map(int, lut.get("internal_nodes", []) or []))
        sup_seed = sup_leaves | sup_internal | {sup_root}

        # ---- cones fields
        cone = cones_map.get(lut_name)
        cone_ok = cone is not None
        cone_m = []
        if cone_ok:
            cone_root = int(cone.get("lut_root", -2))
            cone_hex  = norm_hex16(cone.get("func_hex", "0"))
            cone_leaves = set(map(int, cone.get("leaves", []) or []))
            cone_internal = set(map(int, cone.get("internal_nodes", []) or []))

            if cone_root != sup_root: cone_m.append("root")
            if cone_hex  != sup_hex : cone_m.append("func_hex")
            if cone_leaves != sup_leaves: cone_m.append("leaves")
            if cone_internal != sup_internal: cone_m.append("internal_nodes")
        else:
            cone_m.append("missing_in_lut_cones")

        # ---- closure / boundary
        closure = compute_closure(andtab, sup_root) if sup_root >= 0 else set()
        extra = sorted(list(closure - sup_seed))
        seed_not_in_closure = sorted(list(sup_seed - closure))

        # boundary fanins = nodes that appear as fanin but have no AND row
        boundary = set()
        for n in closure:
            row = andtab.get(str(n))
            if row is None:
                continue
            a,b = map(int,row)
            for lit in (a,b):
                nid = lit_to_nid(lit)
                if nid is None:
                    continue
                if str(nid) not in andtab:
                    boundary.add(nid)

        # ---- BLIF check
        blif_m = []
        bl = blif_blocks.get(lut_name)
        if bl is None:
            blif_m.append("missing_in_blif")
            blif_inputs = []
            blif_hex = None
        else:
            blif_inputs = bl["inputs"]
            try:
                blif_hex = norm_hex16(eval_blif_block_to_hex(blif_inputs, bl["cubes"]))
            except Exception:
                blif_hex = None
                blif_m.append("blif_eval_failed")

            if blif_inputs != sup_pins:
                blif_m.append("pins_order")
            if blif_hex is not None and blif_hex != sup_hex:
                blif_m.append("func_hex")

        # ---- reporting per LUT if issues
        has_issue = bool(cone_m or blif_m or extra or seed_not_in_closure or boundary)
        if has_issue:
            problems += 1
            print(f"\n--- {lut_name} ---")
            print(f" super: root={sup_root} hex={sup_hex} pins={sup_pins}")
            if cone_ok:
                print(f" cones: root={cone_root} hex={cone_hex} leaves={len(cone_leaves)} internal={len(cone_internal)} mism={cone_m}")
            else:
                print(f" cones: MISSING  mism={cone_m}")

            if bl is not None:
                print(f" blif : inputs={blif_inputs} hex={blif_hex} mism={blif_m}")
            else:
                print(f" blif : MISSING mism={blif_m}")

            print(f" closure size={len(closure)} seed size={len(sup_seed)}")
            if extra:
                print(f"  [!] closure has EXTRA nodes not in (leaves+internal+root): {extra[:20]}{'...' if len(extra)>20 else ''}")
            if seed_not_in_closure:
                print(f"  [!] seed nodes not reached from root closure: {seed_not_in_closure[:20]}{'...' if len(seed_not_in_closure)>20 else ''}")
            if boundary:
                # also show which are not among pins/leaves
                not_in_pins = [n for n in sorted(boundary) if f"n{n}" not in []]
                print(f"  [!] boundary fanin nodes (no AND row): {sorted(boundary)[:20]}{'...' if len(boundary)>20 else ''}")
                # highlight if boundary contains nodes not in leaves/pins
                # (pins are nets; we can only compare to leaves IDs)
                boundary_not_in_leaves = sorted(list(boundary - sup_leaves))
                if boundary_not_in_leaves:
                    print(f"      boundary NOT in leaves: {boundary_not_in_leaves[:20]}{'...' if len(boundary_not_in_leaves)>20 else ''}")

    print("\n=== SUMMARY ===")
    print(f"checked LUTs : {checked}")
    print(f"problem LUTs : {problems}")
    print("If many LUTs report 'boundary NOT in leaves' or BLIF mismatch, your AIG->cone extraction/pin mapping is inconsistent.")
    print("If combos mismatch, your viable-options / selector is out of sync with lut_connections_full.")


if __name__ == "__main__":
    main()

