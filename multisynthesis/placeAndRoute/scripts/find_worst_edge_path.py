#!/usr/bin/env python3
import json
import sys
import os

def load_timing_graph(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)
    nodes = data["nodes"]
    edges = data["edges"]
    # Zorg dat node keys strings zijn
    nodes_by_id = {str(nid): n for nid, n in nodes.items()}
    return nodes_by_id, edges

def main():
    if len(sys.argv) != 2:
        print(f"Gebruik: {sys.argv[0]} <timing_graph.place_final.echo.json>")
        sys.exit(1)

    json_path = sys.argv[1]
    if not os.path.isfile(json_path):
        print(f"Bestand niet gevonden: {json_path}")
        sys.exit(1)

    nodes, edges = load_timing_graph(json_path)

    worst_edge = None
    worst_delay = -1.0

    for e in edges:
        src_id = str(e["src"])
        dst_id = str(e["dst"])
        delay = float(e["delay"])

        src_node = nodes.get(src_id)
        dst_node = nodes.get(dst_id)

        if src_node is None or dst_node is None:
            continue

        # *** Hier filteren we: enkel LUT-achtige connecties OPIN -> IPIN ***
        if src_node.get("kind") == "OPIN" and dst_node.get("kind") == "IPIN":
            if delay > worst_delay:
                worst_delay = delay
                worst_edge = (e, src_node, dst_node)

    if worst_edge is None:
        print("Geen OPIN -> IPIN edges gevonden in de timing graph.")
        sys.exit(0)

    edge, src_node, dst_node = worst_edge
    e = edge

    print("Slechtste OPIN -> IPIN edge (op basis van delay):")
    print(
        f"  edge_id={e['edge_id']}  "
        f"{e['src']} ({src_node['kind']}) -> {e['dst']} ({dst_node['kind']})  "
        f"delay={worst_delay:.3e}s"
    )
    print()
    print("Bron-node (OPIN):")
    print(
        f"  Node {src_node['id']}: kind={src_node['kind']} "
        f"arrival={src_node['arrival']:.3e}  "
        f"required={src_node['required']:.3e}  "
        f"slack={src_node['slack']:.3e}"
    )
    print()
    print("Doel-node (IPIN):")
    print(
        f"  Node {dst_node['id']}: kind={dst_node['kind']} "
        f"arrival={dst_node['arrival']:.3e}  "
        f"required={dst_node['required']:.3e}  "
        f"slack={dst_node['slack']:.3e}"
    )

if __name__ == "__main__":
    main()
