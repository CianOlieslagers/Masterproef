#!/usr/bin/env python3
import argparse, json, sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lut-cones", required=True)
    ap.add_argument("--lut-name", required=True)  # bv LUT_120
    args = ap.parse_args()

    with open(args.lut_cones, "r") as f:
        data = json.load(f)

    cones = data.get("lut_cones")
    if not isinstance(cones, list):
        raise SystemExit("ERROR: JSON heeft geen lijst 'lut_cones'.")

    for c in cones:
        if c.get("lut_name") == args.lut_name:
            root = c.get("lut_root")
            if root is None:
                raise SystemExit("ERROR: lut gevonden maar 'lut_root' ontbreekt.")
            print(root)
            return

    raise SystemExit(f"ERROR: {args.lut_name} niet gevonden in lut_cones.json")

if __name__ == "__main__":
    main()
