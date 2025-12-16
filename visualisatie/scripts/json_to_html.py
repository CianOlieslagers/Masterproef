#!/usr/bin/env python3
import json
from pyvis.network import Network


def compute_depths(data):
    """
    Bepaal depth (level) voor inputs, AND-nodes en outputs.
    inputs: depth = 0
    node:  depth = 1 + max(depth(inputs))
    output: depth = depth(source) + 1
    """
    inputs = data.get("inputs", [])
    nodes = data.get("nodes", [])
    outputs = data.get("outputs", [])

    # start: alle inputs op depth 0
    depth = {inp: 0 for inp in inputs}

    # handig om nodes snel terug te vinden
    node_by_id = {n["id"]: n for n in nodes}

    # topologisch diepte berekenen voor alle AND-nodes
    remaining = set(node_by_id.keys())
    while remaining:
        progressed = False
        for nid in list(remaining):
            node = node_by_id[nid]
            src_ids = [i["source_id"] for i in node.get("inputs", [])]

            # check: hebben we voor alle bronnen al een depth?
            if all(src in depth for src in src_ids):
                if src_ids:
                    depth[nid] = 1 + max(depth[src] for src in src_ids)
                else:
                    depth[nid] = 1  # zou niet moeten gebeuren in een AIG
                remaining.remove(nid)
                progressed = True

        if not progressed:
            # fallback voor rare gevallen (cycles / onbekende bronnen)
            for nid in remaining:
                depth.setdefault(nid, 1)
            break

    # outputs één level lager dan hun bron
    for out in outputs:
        src = out["source_id"]
        src_d = depth.get(src, 0)
        depth[out["id"]] = src_d + 1

    return depth


def json_to_html(json_path, html_path):
    # JSON inladen
    with open(json_path) as f:
        data = json.load(f)

    # levels berekenen
    depth = compute_depths(data)

    # PyVis network – DIRECTED + hierarchische layout
    net = Network(
        height="800px",
        width="100%",
        directed=True,
        layout=None,
        bgcolor="#ffffff",
        font_color="black",
    )

    # HIERARCHICAL LAYOUT – geldige JSON-string
    net.set_options(
        """
    {
      "layout": {
        "hierarchical": {
          "enabled": true,
          "direction": "UD",
          "sortMethod": "directed",
          "levelSeparation": 150,
          "nodeSpacing": 200
        }
      },
      "nodes": {
        "shape": "box",
        "margin": 10,
        "widthConstraint": { "minimum": 80 },
        "heightConstraint": { "minimum": 40 },
        "color": {
          "background": "#ffffff",
          "border": "#333333"
        },
        "font": { "size": 22 }
      },
      "edges": {
        "smooth": false,
        "arrows": {
          "to": { "enabled": true, "scaleFactor": 0.7 }
        }
      },
      "physics": { "enabled": false }
    }
    """
    )

    # -------- NODES --------
    # Inputs bovenaan (depth al 0)
    for inp in data.get("inputs", []):
        net.add_node(
            inp,
            label=inp.upper(),
            color="#ffcc00",
            level=depth.get(inp, 0),
            shape="triangle",
            size=30,
        )

    # AND-nodes (levels volgens depth)
        # AND-nodes (levels volgens depth, met rol-kleuren)
    for node in data.get("nodes", []):
        nid = node["id"]
        role = node.get("role", "normal")

        if role == "src":
            color = "#ff3333"   # FEL ROOD
        elif role == "dst":
            color = "#33cc33"   # FEL GROEN
        elif role == "pitstop":
            color = "#aa33ff"   # PAARS
        else:
            color = "#88c4ff"   # standaard blauw

        net.add_node(
            nid,
            label=nid,
            color=color,
            level=depth.get(nid, 1),
            shape="box",
            size=35,
            title=f"{nid} ({role})"
        )

    # Outputs onderaan (depth via compute_depths)
    for out in data.get("outputs", []):
        oid = out["id"]
        net.add_node(
            oid,
            label=oid,
            color="#ff8888",
            level=depth.get(oid, depth.get(out["source_id"], 2) + 1),
            shape="diamond",
            size=30,
        )

    # -------- EDGES --------
    def add_edge(src: str, dst: str, inverted: bool, kind: str):
        """
        src → dst edge toevoegen.
        kind: "AND-input" of "OUTPUT" enkel voor tooltip.
        """
        label = "¬" if inverted else ""
        color = "#ff0000" if inverted else "#000000"
        dashes = bool(inverted)

        net.add_edge(
            src,
            dst,
            color=color,
            label=label,
            title=f"{src} → {dst} ({'inverted' if inverted else 'non-inverted'}) [{kind}]",
            dashes=dashes,
        )

    # 1) AND-node inputs
    for node in data.get("nodes", []):
        nid = node["id"]
        for inp in node.get("inputs", []):
            src = inp["source_id"]
            inv = inp.get("inverted", False)
            add_edge(src, nid, inv, kind="AND-input")

    # 2) Outputs
    for out in data.get("outputs", []):
        src = out["source_id"]
        dst = out["id"]
        inv = out.get("inverted", False)
        add_edge(src, dst, inv, kind="OUTPUT")

    # -------- HTML genereren --------
    net.write_html(html_path, notebook=False, open_browser=False)
    print(f"Visualisatie geschreven naar {html_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Converteer AIG-JSON naar interactieve HTML-visualisatie."
    )
    parser.add_argument("json_file", help="Input JSON-bestand")
    parser.add_argument("html_file", help="Output HTML-bestand")
    args = parser.parse_args()

    json_to_html(args.json_file, args.html_file)
