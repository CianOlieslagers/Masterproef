#!/usr/bin/env python3
import json
import argparse
from pathlib import Path

def load_lut_cones(path):
    with open(path, "r") as f:
        data = json.load(f)
    table = {}
    for entry in data["lut_cones"]:
        lut_root = entry["lut_root"]
        table[lut_root] = entry
    return table


def lutname_to_root(lut_name):
    # Example: "new_n40" → 40
    if lut_name.startswith("new_n"):
        return int(lut_name.replace("new_n", ""))
    elif lut_name.startswith("n"):
        return int(lut_name[1:])
    else:
        raise ValueError(f"Unexpected LUT name format: {lut_name}")


def map_lut(lut_name, cone_table):
    root = lutname_to_root(lut_name)
    if root not in cone_table:
        return {
            "lut_name": lut_name,
            "lut_root": root,
            "found": False,
            "aig_leaves": [],
            "aig_internal": []
        }
    entry = cone_table[root]
    return {
        "lut_name": lut_name,
        "lut_root": root,
        "found": True,
        "aig_leaves": entry.get("leaves", []),
        "aig_internal": entry.get("internal_nodes", [])
    }


def main():
    parser = argparse.ArgumentParser(description="Map mid-LUT geometry → AIG cones")
    parser.add_argument("--best-json", required=True,
        help="example_big_300.best_mid_luts.json")
    parser.add_argument("--cones-json", required=True,
        help="example_big_300.lut_cones.json")
    parser.add_argument("--out-json", required=True,
        help="Output JSON with AIG mapping")
    args = parser.parse_args()

    with open(args.best_json, "r") as f:
        best = json.load(f)

    cone_table = load_lut_cones(args.cones_json)

    result = []
    for entry in best:
        src = map_lut(entry["src"], cone_table)
        dst = map_lut(entry["dst"], cone_table)
        mid = map_lut(entry["mid"], cone_table)

        result.append({
            "src": src,
            "mid": mid,
            "dst": dst,
            "geometry": entry
        })

    with open(args.out_json, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Output written to {args.out_json}")


if __name__ == "__main__":
    main()

