#!/usr/bin/env python3
import json
import csv
import argparse
from pathlib import Path

def load_blocks(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)
    blocks = data["blocks"]

    coords = {}
    for name, info in blocks.items():
        coords[name] = (info["x"], info["y"])
    return coords

def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def is_lut_name(name):
    if name.startswith("pi"):
        return False
    if name.startswith("po"):
        return False
    if name.startswith("out:"):
        return False
    return True

def find_mid_luts(coords, top20_csv_path, min_gain=0):
    results = []

    with open(top20_csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = row["src"]
            dst = row["dst"]

            if src not in coords or dst not in coords:
                continue

            a = coords[src]
            b = coords[dst]
            d_ab = manhattan(a, b)

            if d_ab == 0:
                continue

            mid_candidates = []

            for name, c in coords.items():
                if name in (src, dst):
                    continue
                if not is_lut_name(name):
                    continue

                d_ac = manhattan(a, c)
                d_cb = manhattan(c, b)

                if d_ac != d_cb:
                    continue
                if d_ab != d_ac + d_cb:
                    continue

                cost_direct = d_ab ** 2
                cost_via_c = d_ac ** 2 + d_cb ** 2
                gain = cost_direct - cost_via_c

                if gain < min_gain:
                    continue

                mid_candidates.append({
                    "mid": name,
                    "coords": {"x": c[0], "y": c[1]},
                    "distances": {
                        "d_ac": d_ac,
                        "d_cb": d_cb,
                        "d_ab": d_ab
                    },
                    "costs": {
                        "direct": cost_direct,
                        "via_mid": cost_via_c,
                        "gain": gain
                    }
                })

            results.append({
                "src": src,
                "dst": dst,
                "src_coords": {"x": a[0], "y": a[1]},
                "dst_coords": {"x": b[0], "y": b[1]},
                "d_ab": d_ab,
                "midpoints": mid_candidates
            })

    return results

def main():
    parser = argparse.ArgumentParser(
        description="Zoek LUTs die gelijke manhattan afstand hebben van beide uiteinden."
    )
    parser.add_argument("--json", required=True, help="Path naar *.manhattan.json")
    parser.add_argument("--csv", required=True, help="Path naar *.top20_manhattan.csv")
    parser.add_argument("--out", type=str, default="mid_luts_results.json",
                        help="Output JSON-bestand")
    parser.add_argument("--min-gain", type=float, default=0.0,
                        help="Minimum winst (L^2 model) om te tonen")

    args = parser.parse_args()

    coords = load_blocks(args.json)
    results = find_mid_luts(coords, args.csv, min_gain=args.min_gain)

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)

    print(f"JSON resultaat geschreven naar: {args.out}")

if __name__ == "__main__":
    main()
