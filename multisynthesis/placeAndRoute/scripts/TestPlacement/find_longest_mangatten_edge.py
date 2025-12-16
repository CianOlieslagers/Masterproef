#!/usr/bin/env python3
import json
import argparse
import os
import csv


def is_pi_or_po(name: str) -> bool:
    """
    Geeft True terug als 'name' een primaire input of output lijkt.
    - PIs heten typisch 'pi0', 'pi1', ...
    - POs heten typisch 'out:po0', ...
    """
    if not name:
        return False
    name = str(name)
    return name.startswith("pi") or name.startswith("out:")


def main():
    parser = argparse.ArgumentParser(
        description="Vind de top-N langste Manhattan-verbindingen tussen blokken."
    )
    parser.add_argument(
        "--json",
        required=True,
        help="Pad naar *.manhattan.json (output van make_manhattan_json.py)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Aantal langste verbindingen dat je wil (default: 10)",
    )
    parser.add_argument(
        "--out-csv",
        help="Optioneel: pad naar CSV-bestand om de top-N in te schrijven",
    )

    args = parser.parse_args()

    json_path = os.path.abspath(args.json)
    if not os.path.isfile(json_path):
        raise SystemExit(f"Fout: JSON bestand niet gevonden: {json_path}")

    with open(json_path, "r") as f:
        data = json.load(f)

    blocks = data.get("blocks", {})
    conns = data.get("connections", [])

    if not conns:
        print(f"Geen connections gevonden in {json_path}")
        return

    # ---- Filter PI/PO + verbindingen zonder manhattan of coords ----
    filtered_conns = []
    for c in conns:
        src = c.get("src", "")
        dst = c.get("dst", "")

        # PI/PO skippen
        if is_pi_or_po(src) or is_pi_or_po(dst):
            continue

        manh = c.get("manhattan", None)
        if manh is None:
            # geen geldige manhattan afstand → skip
            continue

        src_block = blocks.get(src, {})
        dst_block = blocks.get(dst, {})
        sx, sy = src_block.get("x", None), src_block.get("y", None)
        dx_, dy_ = dst_block.get("x", None), dst_block.get("y", None)

        # als coords ontbreken, ook skippen
        if None in (sx, sy, dx_, dy_):
            continue

        # bewaar meteen alles wat we nodig hebben
        filtered_conns.append({
            "src": src,
            "dst": dst,
            "manhattan": manh,
            "dx": c.get("dx", None),
            "dy": c.get("dy", None),
            "src_x": sx,
            "src_y": sy,
            "dst_x": dx_,
            "dst_y": dy_,
        })

    if not filtered_conns:
        print("Na filtering (PI/PO + ontbrekende manhattan/coords) blijven er geen verbindingen over.")
        return

    # Sorteer op Manhattan distance (aflopend)
    conns_sorted = sorted(filtered_conns, key=lambda c: c["manhattan"], reverse=True)

    top_n = conns_sorted[: args.top]

    print(f"Top {len(top_n)} verbindingen op basis van Manhattan-distance (zonder PI/PO):")
    print("idx  manhattan  src          dst          (src_x,src_y) -> (dst_x,dst_y)")

    rows_for_csv = []

    for idx, c in enumerate(top_n, start=1):
        src = c["src"]
        dst = c["dst"]
        manh = c["manhattan"]
        dx = c["dx"]
        dy = c["dy"]
        sx = c["src_x"]
        sy = c["src_y"]
        dx_ = c["dst_x"]
        dy_ = c["dst_y"]

        print(
            f"{idx:>3}  {manh:>9}  {src:<10}  {dst:<10}  "
            f"({sx},{sy}) -> ({dx_},{dy_})  "
            f"dx={dx}, dy={dy}"
        )

        rows_for_csv.append({
            "rank": idx,
            "src": src,
            "dst": dst,
            "src_x": sx,
            "src_y": sy,
            "dst_x": dx_,
            "dst_y": dy_,
            "dx": dx,
            "dy": dy,
            "manhattan": manh,
        })

    # Optioneel: naar CSV schrijven
    if args.out_csv:
        csv_path = os.path.abspath(args.out_csv)
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)

        fieldnames = [
            "rank", "src", "dst",
            "src_x", "src_y",
            "dst_x", "dst_y",
            "dx", "dy",
            "manhattan",
        ]

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_for_csv)

        print(f"\nCSV geschreven naar: {csv_path}")


if __name__ == "__main__":
    main()
