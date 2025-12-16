#!/usr/bin/env python3
import argparse
import json
import os
import xml.etree.ElementTree as ET

# -------------------------------------
# .place parser: block -> (x, y, subtile, type)
# -------------------------------------
def parse_place(path):
    blocks = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if (not line or
                line.startswith("#") or
                line.startswith("Netlist_File") or
                line.startswith("Array size")):
                continue

            parts = line.split()
            # Verwacht: name x y subblk layer blocknr
            if len(parts) < 6:
                continue

            name, x, y, subtile, layer, _blocknr = parts[:6]
            try:
                blocks[name] = {
                    "x": int(x),
                    "y": int(y),
                    "subtile": int(subtile),
                    "type": layer
                }
            except ValueError:
                # safety: als er eens een rare lijn tussenstaat, gewoon skippen
                continue

    return blocks

# -------------------------------------
# XML .mapped.net parser
# we lezen enkel de CLB-niveau <block> nodes
# en pakken hun <inputs><port name="I"> ... </port>
# -------------------------------------
def parse_net_xml(path):
    tree = ET.parse(path)
    root = tree.getroot()

    # net -> set(block_name)
    net_drivers = {}
    net_sinks = {}

    # Alle CLB-level blocks zijn directe children van root
    for clb in root.findall("block"):
        clb_name = clb.get("name")
        if not clb_name:
            continue

        # ---- 1) SINKS: nets die naar dit CLB gaan via port I ----
        inputs = clb.find("inputs")
        if inputs is not None:
            for port in inputs.findall("port"):
                if port.get("name") != "I":
                    continue
                text = (port.text or "").strip()
                if not text:
                    continue

                for token in text.split():
                    if token == "open":
                        continue
                    net_name = token  # bv. "pi2", "po126", "new_n300"
                    net_sinks.setdefault(net_name, set()).add(clb_name)

        # ---- 2) DRIVERS: nets die door dit CLB gedreven worden ----
        lut_leaf = None

        # Eerst: clb -> lut4[...] -> lut[...]
        for child in clb.findall("block"):
            inst_child = child.get("instance", "")
            if inst_child.startswith("lut4["):
                for gchild in child.findall("block"):
                    inst_gchild = gchild.get("instance", "")
                    if inst_gchild.startswith("lut["):
                        lut_leaf = gchild
                        break
            if lut_leaf is not None:
                break

        # Fallback: zoek eender welke descendant met instance "lut["
        if lut_leaf is None:
            for sub in clb.iter("block"):
                if sub is clb:
                    continue
                inst_sub = sub.get("instance", "")
                if inst_sub.startswith("lut["):
                    lut_leaf = sub
                    break

        if lut_leaf is None:
            # Geen LUT in deze CLB (zou zeldzaam moeten zijn)
            continue

        outputs = lut_leaf.find("outputs")
        if outputs is None:
            continue

        for port in outputs.findall("port"):
            if port.get("name") != "out":
                continue
            text = (port.text or "").strip()
            if not text:
                continue

            for token in text.split():
                if token == "open":
                    continue
                net_name = token  # bv. "po1", "po126", "new_nXYZ"
                net_drivers.setdefault(net_name, set()).add(clb_name)

    # ---- 3) bouw CLB->CLB verbindingen ----
    connections = []
    net_names = set()

    for net, drivers in net_drivers.items():
        sinks = net_sinks.get(net, set())
        if not sinks:
            continue  # bv. net gaat enkel naar top-level PO, geen CLB-sinks

        net_names.add(net)

        for src_blk in drivers:
            for dst_blk in sinks:
                if src_blk == dst_blk:
                    continue  # geen self-loop
                connections.append({
                    "src": src_blk,
                    "dst": dst_blk,
                    "net": net,
                })

    return connections, net_names

# -------------------------------------
# main
# -------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", required=True, help="VPR .place bestand")
    ap.add_argument("--net", required=True, help="VPR .mapped.net (XML)")
    ap.add_argument("--out", required=True, help="Output JSON pad")
    ap.add_argument("--design", required=True, help="Designnaam")
    args = ap.parse_args()

    place_path = os.path.abspath(args.place)
    net_path = os.path.abspath(args.net)
    out_path = os.path.abspath(args.out)

    # 1) blocks uit .place
    blocks = parse_place(place_path)

    # 2) connecties uit XML netlist
    raw_conns, net_names = parse_net_xml(net_path)

    # 3) Manhattan distances erbij hangen waar mogelijk
    connections = []
    for c in raw_conns:
        src = c["src"]
        dst = c["dst"]

        b_src = blocks.get(src)
        b_dst = blocks.get(dst)

        if b_src is not None and b_dst is not None:
            dx = b_dst["x"] - b_src["x"]
            dy = b_dst["y"] - b_src["y"]
            manhattan = abs(dx) + abs(dy)
        else:
            dx = None
            dy = None
            manhattan = None

        connections.append({
            "src": src,
            "dst": dst,
            "dx": dx,
            "dy": dy,
            "manhattan": manhattan,
        })

    data = {
        "design": args.design,
        "place_file": place_path,
        "net_file": net_path,
        "num_blocks": len(blocks),
        # 'num_nets' is hier "ongeveer": uniek aantal signaaltokens
        "num_nets": len(net_names),
        "num_connections": len(connections),
        "blocks": blocks,
        "connections": connections,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Geschreven naar {out_path}")
    print(f"  blocks: {len(blocks)}, nets(approx): {len(net_names)}, connections: {len(connections)}")

if __name__ == "__main__":
    main()
