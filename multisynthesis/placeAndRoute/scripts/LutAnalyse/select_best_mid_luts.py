#!/usr/bin/env python3
import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser(
        description="Selecteer de beste mid-LUT combinaties op basis van gain."
    )
    ap.add_argument(
        "--mid-luts-json",
        required=True,
        help="Pad naar example_big_300.mid_luts.json (output van mid-LUT analyse).",
    )
    ap.add_argument(
        "--top",
        type=int,
        default=5,
        help="Aantal beste combinaties dat je wil bewaren (default: 5).",
    )
    ap.add_argument(
        "--out-json",
        required=True,
        help="Outputbestand voor de beste combinaties (JSON).",
    )

    args = ap.parse_args()

    in_path = os.path.abspath(args.mid_luts_json)
    out_path = os.path.abspath(args.out_json)

    if not os.path.isfile(in_path):
        raise SystemExit(f"Fout: input JSON niet gevonden: {in_path}")

    with open(in_path, "r") as f:
        entries = json.load(f)

    candidates = []

    # entries = lijst van {src, dst, d_ab, midpoints: [ ... ]}
    for pair_idx, entry in enumerate(entries):
        src = entry.get("src")
        dst = entry.get("dst")
        d_ab = entry.get("d_ab")
        src_coords = entry.get("src_coords", {})
        dst_coords = entry.get("dst_coords", {})

        for mid in entry.get("midpoints", []):
            mid_name = mid.get("mid")
            coords = mid.get("coords", {})
            distances = mid.get("distances", {})
            costs = mid.get("costs", {})

            gain = costs.get("gain", 0)
            direct = costs.get("direct", None)
            via_mid = costs.get("via_mid", None)

            # Alleen interessante gevallen met positieve gain
            if gain is None or gain <= 0:
                continue

            candidates.append({
                "src": src,
                "dst": dst,
                "mid": mid_name,
                "src_coords": src_coords,
                "mid_coords": coords,
                "dst_coords": dst_coords,
                "distances": distances,
                "costs": {
                    "direct": direct,
                    "via_mid": via_mid,
                    "gain": gain,
                },
                "edge_index": pair_idx,
                "d_ab": d_ab,
            })

    if not candidates:
        print("Geen kandidaten met positieve gain gevonden.")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump([], f, indent=2)
        print(f"Leeg resultaat geschreven naar: {out_path}")
        return

    # Sorteer: eerst op gain (aflopend), dan eventueel op oorspronkelijke d_ab
    candidates_sorted = sorted(
        candidates,
        key=lambda c: (c["costs"]["gain"], c.get("d_ab", 0)),
        reverse=True,
    )

    top_n = candidates_sorted[: args.top]

    # Rank toevoegen
    for rank, c in enumerate(top_n, start=1):
        c["rank"] = rank

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(top_n, f, indent=2)

    print(f"{len(top_n)} beste mid-LUT combinaties geschreven naar: {out_path}")


if __name__ == "__main__":
    main()
