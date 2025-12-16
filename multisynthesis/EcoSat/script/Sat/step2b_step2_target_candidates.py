#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List, Optional


def load_json(path: str) -> Any:
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"[FATAL] File not found: {path}")
    with open(path, "r") as f:
        return json.load(f)


def find_lut_cones_entry(lut_cones_db: Any, lut_name: str) -> Optional[Dict[str, Any]]:
    """
    lut_cones.json kan 2 vormen hebben:
      1) {"lut_cones":[ {...}, {...} ]}
      2) [ {...}, {...} ]  (soms)
    """
    if isinstance(lut_cones_db, dict):
        items = lut_cones_db.get("lut_cones", [])
    elif isinstance(lut_cones_db, list):
        items = lut_cones_db
    else:
        items = []

    for e in items:
        if isinstance(e, dict) and e.get("lut_name") == lut_name:
            return e
    return None


def node_functions_to_map(node_functions: Any) -> Dict[int, str]:
    """
    Verwacht node_functions als:
      [{"node":101,"func_hex":"a251"}, ...]
    Geeft dict {101:"a251", ...}
    """
    m: Dict[int, str] = {}
    if not node_functions:
        return m

    if isinstance(node_functions, list):
        for item in node_functions:
            if not isinstance(item, dict):
                continue
            n = item.get("node", None)
            h = item.get("func_hex", None)
            if n is None or h is None:
                continue
            try:
                m[int(n)] = str(h)
            except Exception:
                continue
    elif isinstance(node_functions, dict):
        # fallback: als het ooit toch dict is
        for k, v in node_functions.items():
            try:
                m[int(k)] = str(v)
            except Exception:
                continue

    return m


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Scenario 2B (optie A) - Stap 2: target candidate functies (G) uit dst internal_nodes halen."
    )
    ap.add_argument("--instance", required=True, help="Pad naar *.eco_instance.json")
    ap.add_argument("--lut-cones", required=True, help="Pad naar <design>.lut_cones.json")
    ap.add_argument(
        "--include-dst-root",
        action="store_true",
        help="Neem ook dst.lut_root op als target (naast internal_nodes).",
    )
    ap.add_argument(
        "--out",
        default="targets.json",
        help="Output JSON (default: targets.json in huidige map).",
    )
    args = ap.parse_args()

    inst = load_json(args.instance)
    lut_cones_db = load_json(args.lut_cones)

    if inst.get("format") != "eco_candidate:v1":
        print(f"[WARN] Onverwacht instance format: {inst.get('format')}")

    dst = inst.get("dst", {})
    dst_name = dst.get("lut_name")
    dst_root = dst.get("lut_root")

    if not dst_name:
        raise ValueError("[FATAL] instance.dst.lut_name ontbreekt")
    if dst_root is None:
        raise ValueError("[FATAL] instance.dst.lut_root ontbreekt")

    dst_entry = find_lut_cones_entry(lut_cones_db, dst_name)
    if not dst_entry:
        raise ValueError(f"[FATAL] dst LUT niet gevonden in lut_cones.json: {dst_name}")

    internal_nodes: List[int] = []
    for x in (dst_entry.get("internal_nodes", []) or []):
        internal_nodes.append(int(x))

    node_func_map = node_functions_to_map(dst_entry.get("node_functions", []))
    # sanity: dst_root moet meestal ook in node_functions zitten
    dst_root_hex = node_func_map.get(int(dst_entry.get("lut_root", dst_root)))

    print("========================================")
    print("[INFO] Scenario 2B (optie A) - Stap 2 target candidates")
    print("----------------------------------------")
    print(f"[INFO] instance   : {args.instance}")
    print(f"[INFO] dst LUT    : {dst_name}")
    print(f"[INFO] dst root   : {dst_root} (hex in node_functions: {dst_root_hex})")
    print(f"[INFO] internal_nodes (#={len(internal_nodes)}): {internal_nodes}")
    print(f"[INFO] node_functions entries (#={len(node_func_map)}): {len(node_func_map)}")
    print("========================================")

    # Kandidatenlijst bouwen
    targets: List[Dict[str, Any]] = []

    def add_target(node_id: int) -> None:
        hx = node_func_map.get(int(node_id))
        targets.append(
            {
                "node": int(node_id),
                "func_hex": hx,  # kan None zijn, dan weten we dat we later support/func moeten reconstrueren
                "source": "internal_node" if int(node_id) != int(dst_root) else "dst_root",
            }
        )

    for n in internal_nodes:
        add_target(n)

    if args.include_dst_root:
        add_target(int(dst_root))

    # Output schrijven
    out_obj = {
        "format": "eco_targets:v1",
        "instance": args.instance,
        "dst": {
            "lut_name": dst_name,
            "lut_root": int(dst_root),
            "leaves": dst_entry.get("leaves", []),
        },
        "targets": targets,
        "notes": [
            "targets zijn kandidaat G-nodes uit de dst cone (internal_nodes).",
            "func_hex kan None zijn als node_functions die node niet bevat.",
            "volgende stap: per target support bepalen (via ABC cone + support of via AIG traversal).",
        ],
    }

    with open(args.out, "w") as f:
        json.dump(out_obj, f, indent=2)

    # Print targets kort
    print("[TARGETS]")
    for t in targets:
        print(f"  - node={t['node']:<4} func_hex={t['func_hex']} ({t['source']})")

    print("========================================")
    print(f"[OK] targets geschreven → {os.path.abspath(args.out)}")
    print("========================================")


if __name__ == "__main__":
    main()
