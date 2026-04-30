#!/usr/bin/env python3
import json
import argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--super", required=True)
    ap.add_argument("--lut", required=True, help="bv LUT_120")
    args = ap.parse_args()

    data = json.load(open(args.super, "r"))

    lut = data["luts"].get(args.lut)
    if lut is None:
        raise SystemExit(f"LUT niet gevonden in super-json: {args.lut}")

    leaves = lut.get("leaves", [])
    pins = lut.get("netlist", {}).get("lut_inputs_ordered", [])
    outnet = lut.get("netlist", {}).get("output_net", None)

    print(f"=== {args.lut} ===")
    print("lut_root:", lut.get("lut_root"))
    print("leaves  :", leaves)
    print("pins    :", pins)
    print("output  :", outnet)

if __name__ == "__main__":
    main()
