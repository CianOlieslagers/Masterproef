#!/usr/bin/env python3
import re
import json
import argparse
import os
import sys


def parse_timing_graph(dot_path, json_path):
    with open(dot_path, "r", encoding="utf-8") as f:
        text = f.read()

    nodes = {}
    edges = []

    # === Nodes parsen ===
    # Voorbeeld node:
    # node6[label="{Node(6) (IPIN) | {DATA_ARRIVAL
    # Domain(0) ... time: 7.9977e-10} | {DATA_REQUIRED ... time: -2.9604e-09} | {SLACK ... time: -3.76017e-09}}"]
    node_pattern = re.compile(
        r'node(\d+)\[label="\{Node\(\d+\) \((.*?)\).*?DATA_ARRIVAL.*?time:\s*([0-9eE\+\-\.]+).*?DATA_REQUIRED.*?time:\s*([0-9eE\+\-\.]+).*?SLACK.*?time:\s*([0-9eE\+\-\.]+)',
        re.S
    )

    for match in node_pattern.findall(text):
        node_id, kind, arrival, required, slack = match
        nid = int(node_id)
        try:
            nodes[nid] = {
                "id": nid,
                "kind": kind,
                "arrival": float(arrival),
                "required": float(required),
                "slack": float(slack),
            }
        except ValueError:
            # Als er eens een rare "time: nan" of zo staat: skip of log
            print(f"Waarschuwing: kon timing niet parsen voor node {nid}", file=sys.stderr)

    # === Edges parsen ===
    # Voorbeeld edge:
    # node0 -> node6 [ label="Edge(0)\n7.9977e-10"];
    edge_pattern = re.compile(
        r'node(\d+)\s*->\s*node(\d+)\s*\[\s*label="Edge\((\d+)\)(?:\\n|\n)([0-9eE\+\-\.]+)"'
    )

    for match in edge_pattern.findall(text):
        src, dst, edge_id, delay = match
        edges.append({
            "src": int(src),
            "dst": int(dst),
            "edge_id": int(edge_id),
            "delay": float(delay),
        })

    out = {
        "nodes": nodes,
        "edges": edges,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)

    print(f"✓ Parsed timing graph")
    print(f"  Nodes : {len(nodes)}")
    print(f"  Edges : {len(edges)}")
    print(f"  Output: {json_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Parse VPR timing_graph.place_final.echo.dot naar JSON met nodes + edges."
    )
    parser.add_argument(
        "dot_file",
        help="Pad naar timing_graph.place_final.echo.dot"
    )
    parser.add_argument(
        "-o", "--output",
        help="Pad naar JSON-output. Default: zelfde naam maar met .json"
    )

    args = parser.parse_args()

    dot_path = os.path.abspath(args.dot_file)
    if not os.path.isfile(dot_path):
        print(f"Error: DOT-bestand niet gevonden: {dot_path}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        json_path = os.path.abspath(args.output)
    else:
        base, _ = os.path.splitext(dot_path)
        json_path = base + ".json"

    parse_timing_graph(dot_path, json_path)


if __name__ == "__main__":
    main()
