#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List, Tuple


def load_json(path: str) -> Any:
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"[FATAL] File not found: {path}")
    with open(path, "r") as f:
        return json.load(f)


def hex_to_truth_bits(func_hex: str, n_inputs: int) -> List[int]:
    """
    Zet hex om naar truth table bits (LSB = input assignment 0...0).
    Voor n_inputs=4 verwacht je 16 bits.
    """
    func_hex = func_hex.strip().lower().replace("0x", "")
    table_size = 1 << n_inputs
    val = int(func_hex, 16)

    bits = []
    for a in range(table_size):
        bits.append((val >> a) & 1)  # LSB = assignment a
    return bits


def support_from_bits(bits: List[int], n_inputs: int) -> List[int]:
    """
    Variabele i zit in support als er een assignment bestaat waarbij flip(i) output verandert.
    We gebruiken assignment index a (0..2^n-1). Flip bit i => a ^ (1<<i).
    """
    table_size = 1 << n_inputs
    support_vars = []
    for i in range(n_inputs):
        mask = 1 << i
        depends = False
        for a in range(table_size):
            b = a ^ mask
            if bits[a] != bits[b]:
                depends = True
                break
        if depends:
            support_vars.append(i)
    return support_vars


def main():
    ap = argparse.ArgumentParser(
        description="Scenario 2B optie A - Stap 3: support per target bepalen via func_hex truth table."
    )
    ap.add_argument("--targets", required=True, help="Pad naar scen2b_targets_*.json")
    ap.add_argument("--out", required=True, help="Output JSON met support-info")
    args = ap.parse_args()

    data = load_json(args.targets)

    dst = data["dst"]
    dst_leaves: List[int] = dst["leaves"]
    n_inputs = len(dst_leaves)

    targets = data["targets"]

    print("========================================")
    print("[INFO] Scenario 2B (optie A) - Stap 3 support report")
    print("----------------------------------------")
    print(f"[INFO] targets file : {args.targets}")
    print(f"[INFO] dst leaves   : {dst_leaves}  (n_inputs={n_inputs})")
    print("========================================")

    out_targets = []
    for t in targets:
        node = int(t["node"])
        func_hex = t.get("func_hex")
        if func_hex is None:
            print(f"[WARN] node={node} heeft func_hex=None -> skip")
            continue

        bits = hex_to_truth_bits(func_hex, n_inputs)
        supp_vars = support_from_bits(bits, n_inputs)
        supp_leaves = [dst_leaves[i] for i in supp_vars]

        out_targets.append({
            "node": node,
            "func_hex": func_hex,
            "support_vars": supp_vars,
            "support_leaves": supp_leaves,
        })

        print(f"[TARGET] node={node:<4} hex={func_hex:<4}  support_vars={supp_vars}  support_leaves={supp_leaves}")

    out = {
        "format": "eco_support_report:v1",
        "src": data.get("instance"),
        "dst": dst,
        "targets": out_targets,
        "notes": [
            "support_vars indexeert dst.leaves volgorde uit targets.json",
            "support_leaves zijn AIG-leaf IDs (zoals in lut_cones)",
        ],
    }

    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    print("========================================")
    print(f"[OK] support report geschreven → {os.path.abspath(args.out)}")
    print("========================================")


if __name__ == "__main__":
    main()
