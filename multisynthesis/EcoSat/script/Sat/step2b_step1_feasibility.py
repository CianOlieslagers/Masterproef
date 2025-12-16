#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List, Set


def load_json(path: str) -> Any:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"[FATAL] File not found: {path}")
    with open(path, "r") as f:
        return json.load(f)


def as_set_int(xs: Any) -> Set[int]:
    if xs is None:
        return set()
    if not isinstance(xs, list):
        return set()
    out = set()
    for x in xs:
        try:
            out.add(int(x))
        except Exception:
            pass
    return out


def get_lut_entry(lut_cones_db: Dict[str, Any], lut_name: str) -> Dict[str, Any]:
    """
    Supports two formats:
    - {"lut_cones":[{"lut_name":"LUT_11", ...}, ...]}
    - {"LUT_11": {...}, "LUT_12": {...}}
    """
    if "lut_cones" in lut_cones_db and isinstance(lut_cones_db["lut_cones"], list):
        for e in lut_cones_db["lut_cones"]:
            if e.get("lut_name") == lut_name:
                return e
        return {}
    # map-style
    if lut_name in lut_cones_db and isinstance(lut_cones_db[lut_name], dict):
        e = dict(lut_cones_db[lut_name])
        e.setdefault("lut_name", lut_name)
        return e
    return {}


def main():
    ap = argparse.ArgumentParser(description="Scenario 2B (optie A) - Stap 1 feasibility report per instance.")
    ap.add_argument("--instance", required=True, help="Path to *.eco_instance.json")
    ap.add_argument("--lut-cones", required=True, help="Path to <design>.lut_cones.json")
    ap.add_argument("--k", type=int, default=4, help="Max LUT input size K (default 4)")
    args = ap.parse_args()

    inst = load_json(args.instance)
    cones = load_json(args.lut_cones)

    if inst.get("format") != "eco_candidate:v1":
        raise ValueError(f"[FATAL] Unexpected instance format: {inst.get('format')}")

    pit = inst["pitstop"]
    dst = inst["dst"]
    src = inst["src"]

    pit_name = pit.get("lut_name")
    dst_name = dst.get("lut_name")
    src_name = src.get("lut_name")

    pit_leaves = as_set_int(pit.get("aig", {}).get("leaves", []))
    dst_leaves = as_set_int(dst.get("aig", {}).get("leaves", []))
    src_leaves = as_set_int(src.get("aig", {}).get("leaves", []))

    overlap_pit_dst = sorted(pit_leaves & dst_leaves)
    overlap_pit_src = sorted(pit_leaves & src_leaves)
    overlap_all = sorted(pit_leaves & dst_leaves & src_leaves)

    # Pull extra info from lut_cones DB (if present)
    pit_db = get_lut_entry(cones, pit_name) if pit_name else {}
    dst_db = get_lut_entry(cones, dst_name) if dst_name else {}

    pit_db_root = pit_db.get("lut_root")
    dst_db_root = dst_db.get("lut_root")

    pit_db_leaves = as_set_int(pit_db.get("leaves", [])) if pit_db else set()
    dst_db_leaves = as_set_int(dst_db.get("leaves", [])) if dst_db else set()

    # Candidate B choices (for optie A sanity)
    # 1) safest: B = current pit leaves (no rewiring needed)
    B0 = sorted(pit_leaves)
    # 2) if we want "shared" signals: B = intersection(pit, dst)
    B1 = overlap_pit_dst

    print("========================================")
    print("[INFO] Scenario 2B (optie A) - Stap 1 feasibility report")
    print("----------------------------------------")
    print(f"[INFO] instance : {args.instance}")
    print(f"[INFO] K        : {args.k}")
    print("----------------------------------------")
    print(f"[INFO] src LUT  : {src_name}")
    print(f"[INFO] dst LUT  : {dst_name}")
    print(f"[INFO] pit LUT  : {pit_name}")
    print("----------------------------------------")
    print(f"[INFO] pit leaves (from instance) (#={len(pit_leaves)}): {sorted(pit_leaves)}")
    print(f"[INFO] dst  leaves (from instance) (#={len(dst_leaves)}): {sorted(dst_leaves)}")
    print(f"[INFO] src leaves (from instance) (#={len(src_leaves)}): {sorted(src_leaves)}")
    print("----------------------------------------")
    print(f"[INFO] overlap pit∩dst (#={len(overlap_pit_dst)}): {overlap_pit_dst}")
    print(f"[INFO] overlap pit∩src (#={len(overlap_pit_src)}): {overlap_pit_src}")
    print(f"[INFO] overlap pit∩dst∩src (#={len(overlap_all)}): {overlap_all}")
    print("----------------------------------------")
    if pit_db:
        print(f"[INFO] pit lut_cones entry found. lut_root={pit_db_root}, leaves(#={len(pit_db_leaves)}): {sorted(pit_db_leaves)}")
    else:
        print("[WARN] pit not found in lut_cones DB (ok if instance already contains leaves/hex).")
    if dst_db:
        nf = dst_db.get("node_functions", {})
        nf_count = len(nf) if isinstance(nf, dict) else 0
        print(f"[INFO] dst lut_cones entry found. lut_root={dst_db_root}, leaves(#={len(dst_db_leaves)}): {sorted(dst_db_leaves)}")
        print(f"[INFO] dst node_functions entries: {nf_count}")
    else:
        print("[WARN] dst not found in lut_cones DB (ok if instance already contains leaves/hex).")

    print("========================================")
    print("[CHECK] Feasibility quick checks")
    ok = True

    if len(pit_leaves) == 0:
        print("[FAIL] pit leaves missing in instance → cannot define boundary B.")
        ok = False

    if len(pit_leaves) > args.k:
        print(f"[FAIL] pit has {len(pit_leaves)} inputs > K={args.k} → cannot patch without changing K or rewiring.")
        ok = False
    else:
        print(f"[OK] pit input count <= K ({len(pit_leaves)} <= {args.k})")

    if len(overlap_pit_dst) == 0:
        print("[WARN] pit∩dst overlap is empty. Optie A (reuse dst subfunction) will be hard without rewiring.")
    else:
        print("[OK] pit shares at least one signal with dst (good for optie A)")

    print("========================================")
    print("[SUGGEST] Candidate boundary B sets to try first")
    print(f"  B0 (no rewiring): {B0}")
    if B1:
        print(f"  B1 (shared pit∩dst): {B1}")
    else:
        print("  B1 (shared pit∩dst): <empty>")
    print("========================================")

    if ok:
        print("[RESULT] Feasible to proceed to Scenario 2B optie A step 2 (choose target function).")
    else:
        print("[RESULT] NOT feasible yet. Fix the FAIL items above first.")


if __name__ == "__main__":
    main()
