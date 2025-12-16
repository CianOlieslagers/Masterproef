#!/usr/bin/env python3
import json
import argparse

# === INSTELBARE VARIABELE BOVENAAN ===
# Hoeveel langste paden wil je tonen?
TOP_N = 10


def load_lut_graph(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_pi_or_po_net(name: str) -> bool:
    """
    Geeft True terug als de net-naam overeenkomt met een primaire input of output.
    - PIs: 'pi0', 'pi1', ...
    - POs: 'out:po0', ...
    """
    if not name:
        return False
    name = str(name)
    return name.startswith("pi") or name.startswith("out:")


def collect_branches(data):
    """
    Haalt alle unieke branches op uit data["luts"][*]["outgoing"].

    Elke branch heeft velden:
      net, branch_index, source_lut, source_coord, sink_lut, sink_coord,
      chan_hops, chanx_hops, chany_hops, manhattan
    We filteren hier nets die PI/PO zijn.
    """
    branches = []

    luts = data.get("luts", {})
    for lut_id, info in luts.items():
        for rec in info.get("outgoing", []):
            net_name = rec.get("net", "")
            if is_pi_or_po_net(net_name):
                # PI/PO-net → skip (bv. pi0, pi1, out:po0)
                continue
            branches.append(rec)

    return branches


def main():
    global TOP_N

    ap = argparse.ArgumentParser(
        description="Zoek de langste paden (Manhattan distance) tussen LUTs."
    )
    ap.add_argument("json", help="Pad naar lut_phys_graph.json")
    ap.add_argument(
        "-n", "--top",
        type=int,
        help="Aantal langste paden (overschrijft TOP_N hierboven)"
    )
    args = ap.parse_args()

    if args.top is not None:
        TOP_N = args.top

    data = load_lut_graph(args.json)
    branches = collect_branches(data)

    if not branches:
        print("Geen branches gevonden in JSON na filtering van PI/PO-nets.")
        return

    # Sorteer op manhattan afstand (aflopend), dan eventueel op chan_hops
    branches_sorted = sorted(
        branches,
        key=lambda b: (b.get("manhattan", 0), b.get("chan_hops", 0)),
        reverse=True,
    )

    top = branches_sorted[:TOP_N]

    print(f"Langste {len(top)} paden op basis van Manhattan distance (zonder PI/PO-nets):\n")

    for i, b in enumerate(top, 1):
        print(f"=== Pad #{i} ===")
        print(f"  Net           : {b.get('net')}")
        print(f"  Branch index  : {b.get('branch_index')}")
        print(f"  Source LUT    : {b.get('source_lut')}  @ {b.get('source_coord')}")
        print(f"  Sink   LUT    : {b.get('sink_lut')}    @ {b.get('sink_coord')}")
        print(f"  Manhattan dist: {b.get('manhattan')}")
        print(f"  CHAN hops     : {b.get('chan_hops')} "
              f"(CHANX={b.get('chanx_hops')}, CHANY={b.get('chany_hops')})")
        print()


if __name__ == "__main__":
    main()
