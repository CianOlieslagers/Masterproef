#!/usr/bin/env python3
import json
import re
import pydot


def _iter_nodes_recursive(graph):
    """Geef alle nodes uit graph + subgraphs."""
    for n in graph.get_nodes():
        yield n
    for sg in graph.get_subgraphs():
        yield from _iter_nodes_recursive(sg)


def _iter_edges_recursive(graph):
    """Geef alle edges uit graph + subgraphs."""
    for e in graph.get_edges():
        yield e
    for sg in graph.get_subgraphs():
        yield from _iter_edges_recursive(sg)


def dot_to_json(dot_path: str) -> dict:
    """
    Converteer een ABC-DOT bestand (write_dot) naar jouw JSON-structuur:
    {
      "inputs": ["a", "b", ...],
      "nodes": [
        {
          "id": "N5",
          "type": "AND",
          "inputs": [
            {"source_id": "a",  "inverted": false},
            {"source_id": "b",  "inverted": true}
          ]
        },
        ...
      ],
      "outputs": [
        {"id": "f", "source_id": "N9", "inverted": true}
      ]
    }
    """

    graphs = pydot.graph_from_dot_file(dot_path)
    if not graphs:
        raise RuntimeError(f"Kon geen DOT-grafiek vinden in {dot_path}")
    g = graphs[0]

    # nodes_map[name] = {"kind": "PI"|"AND"|"PO", "json_id": str, ...}
    nodes_map = {}
    input_ids = []
    and_nodes = {}
    po_nodes = {}

    # -------- PASS 1: nodes classificeren --------
    for node in _iter_nodes_recursive(g):
        name = node.get_name().strip('"')
        attrs = node.get_attributes()
        shape = attrs.get("shape", "").strip('"')
        label = attrs.get("label", "").strip('"')

        # pydot voegt soms een "node" meta-node toe, die negeren
        if name in ("node", "graph", "edge"):
            continue

        # Debug-tip (optioneel): print een paar ruwe nodes
        # print("NODE", name, "shape=", shape, "label=", label)

        if shape == "triangle":
            # Primaire input
            json_id = label  # bv. "a", "b", "c"
            nodes_map[name] = {"kind": "PI", "json_id": json_id}
            input_ids.append(json_id)

        elif shape == "ellipse":
            # AND-node
            # ID halen uit node-naam "Node5" of anders uit label "5\n"
            m = re.search(r"\d+", name)
            if m:
                num = m.group(0)
            else:
                m2 = re.search(r"\d+", label)
                num = m2.group(0) if m2 else label or name

            json_id = f"N{num}"
            info = {"kind": "AND", "json_id": json_id, "inputs": []}
            nodes_map[name] = info
            and_nodes[json_id] = info

        elif shape == "invtriangle":
            # Output-node
            json_id = label  # bv. "f"
            info = {"kind": "PO", "json_id": json_id, "fanin": []}
            nodes_map[name] = info
            po_nodes[name] = info

        else:
            # bv. LevelTitle1, title1, plaintext e.d. → negeren
            continue

    # -------- PASS 2: edges → fanin-relaties --------
    #
    # Globaal in jouw DOT staat:  edge [dir = back];
    # Dus: "NodeX -> NodeY" betekent dat Y de fanin is van X.
    #
    for edge in _iter_edges_recursive(g):
        u = edge.get_source().strip('"')
        v = edge.get_destination().strip('"')

        if u not in nodes_map or v not in nodes_map:
            # edges naar layout-nodes negeren
            continue

        attrs = edge.get_attributes()
        style = attrs.get("style", "solid")
        style = str(style).strip('"')
        inverted = (style == "dotted")

        sink_name = u   # NodeX in "NodeX -> NodeY"
        src_name = v    # NodeY in "NodeX -> NodeY"

        sink_info = nodes_map[sink_name]
        src_info = nodes_map[src_name]
        src_id = src_info["json_id"]

        if sink_info["kind"] == "AND":
            sink_info["inputs"].append(
                {"source_id": src_id, "inverted": inverted}
            )
        elif sink_info["kind"] == "PO":
            sink_info["fanin"].append(
                {"source_id": src_id, "inverted": inverted}
            )

    # -------- JSON opbouwen --------

    inputs_json = sorted(input_ids)

    nodes_json = []
    for name, info in nodes_map.items():
        if info["kind"] == "AND":
            nodes_json.append(
                {
                    "id": info["json_id"],
                    "type": "AND",
                    "inputs": info["inputs"],
                }
            )
    nodes_json.sort(key=lambda n: n["id"])

    outputs_json = []
    for po_name, info in po_nodes.items():
        fanins = info.get("fanin", [])
        if not fanins:
            continue
        # We gaan uit van één fanin per PO
        src = fanins[0]
        outputs_json.append(
            {
                "id": info["json_id"],
                "source_id": src["source_id"],
                "inverted": src["inverted"],
            }
        )

    result = {
        "inputs": inputs_json,
        "nodes": nodes_json,
        "outputs": outputs_json,
    }
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Converteer ABC write_dot output naar JSON-structuur."
    )
    parser.add_argument("dot_file", help="Input DOT bestand (write_dot output)")
    parser.add_argument("json_file", help="Output JSON bestand")
    args = parser.parse_args()

    data = dot_to_json(args.dot_file)
    with open(args.json_file, "w") as f:
        json.dump(data, f, indent=2)
