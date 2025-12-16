#!/usr/bin/env python3
import re, json, argparse
from collections import defaultdict

RX_ARRAY = re.compile(r"Array size:\s+(\d+)\s+x\s+(\d+)")
RX_NET   = re.compile(r"^Net\s+(\d+)\s+\(([^)]+)\)")
RX_NODE  = re.compile(
    r"^Node:\s+(\d+)\s+(\w+)\s+\((\d+),(\d+),(\d+)\)"
)

def lut_id(x, y):
    return f"CLB_{x}_{y}"

def parse_route(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    grid_w = grid_h = None
    for ln in lines:
        m = RX_ARRAY.search(ln)
        if m:
            grid_w, grid_h = int(m.group(1)), int(m.group(2))
            break

    luts = {}  # lut_id -> {"coord":[x,y], "incoming":[], "outgoing":[]}

    def ensure_lut(x, y):
        lid = lut_id(x, y)
        if lid not in luts:
            luts[lid] = {
                "coord": [x, y],
                "incoming": [],
                "outgoing": [],
            }
        return lid

    nets = []  # alleen als je later per-net iets wilt
    cur_net = None

    source_coord = None
    source_lut = None

    # branch state
    branch_index = 0
    chanx_hops = 0
    chany_hops = 0
    sink_coord = None

    def finish_branch():
        nonlocal chanx_hops, chany_hops, sink_coord, branch_index
        if source_coord is None or sink_coord is None:
            return
        (xs, ys) = source_coord
        (xd, yd) = sink_coord
        src_id = ensure_lut(xs, ys)
        dst_id = ensure_lut(xd, yd)
        chan_hops = chanx_hops + chany_hops
        manhattan = abs(xs - xd) + abs(ys - yd)

        rec = {
            "net": cur_net["name"],
            "branch_index": branch_index,
            "source_lut": src_id,
            "source_coord": [xs, ys],
            "sink_lut": dst_id,
            "sink_coord": [xd, yd],
            "chan_hops": chan_hops,
            "chanx_hops": chanx_hops,
            "chany_hops": chany_hops,
            "manhattan": manhattan,
        }

        luts[src_id]["outgoing"].append(rec)
        luts[dst_id]["incoming"].append(rec)

        branch_index += 1
        chanx_hops = 0
        chany_hops = 0
        sink_coord = None

    for ln in lines:
        ln = ln.rstrip("\n")

        # Net header?
        m_net = RX_NET.match(ln)
        if m_net:
            # sluit lopende branch af (veiligheid)
            if cur_net is not None:
                finish_branch()
            net_id = int(m_net.group(1))
            net_name = m_net.group(2)
            cur_net = {"id": net_id, "name": net_name}
            nets.append(cur_net)

            # reset net-brede state
            source_coord = None
            source_lut = None
            branch_index = 0
            chanx_hops = 0
            chany_hops = 0
            sink_coord = None
            continue

        if cur_net is None:
            continue  # nog niet in een Net-block

        # Node line?
        m_node = RX_NODE.match(ln)
        if not m_node:
            continue

        node_id = int(m_node.group(1))
        node_type = m_node.group(2)   # SOURCE, OPIN, CHANX, CHANY, IPIN, SINK
        x = int(m_node.group(3))
        y = int(m_node.group(4))
        # z = int(m_node.group(5))     # altijd 0 bij jouw arch

        if node_type == "SOURCE":
            source_coord = (x, y)
            source_lut = ensure_lut(x, y)
            # nieuwe net → nieuwe branches, maar niet finish_branch hier
        elif node_type in ("CHANX", "CHANY"):
            # tel hops; bij length=1 segments is iedere overgang 1 tile
            # (we gebruiken de route-file in volgorde, dus we kunnen ook dx/dy doen)
            # Hier doen we gewoon +1 per CHAN-node als simplificatie:
            if node_type == "CHANX":
                chanx_hops += 1
            else:
                chany_hops += 1
        elif node_type == "IPIN":
            sink_coord = (x, y)
        elif node_type == "SINK":
            # branch klaar
            finish_branch()
        # OPIN hoeven we hier niet expliciet te gebruiken; hij markeert enkel begin van een tak

    # safety op einde file
    if cur_net is not None:
        finish_branch()

    return {
        "grid": {"width": grid_w, "height": grid_h},
        "luts": luts,
        "nets_parsed": len(nets),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", required=True, help=".mapped.route bestand")
    ap.add_argument("--out", required=True, help="output JSON pad")
    args = ap.parse_args()

    data = parse_route(args.route)
    out = {
        "format": "lut_phys_graph:v1",
        "circuit": None,  # kan je later invullen als je wilt
        "grid": data["grid"],
        "luts": data["luts"],
        "meta": {
            "source_route": args.route,
            "nets_parsed": data["nets_parsed"],
        }
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"JSON → {args.out}")
    print(f"LUTs  : {len(data['luts'])}")
    print(f"Nets  : {data['nets_parsed']}")

if __name__ == "__main__":
    main()
