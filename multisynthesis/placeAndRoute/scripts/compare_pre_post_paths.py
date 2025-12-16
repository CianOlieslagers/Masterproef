#!/usr/bin/env python3
import argparse
import csv
import json
import os
from collections import namedtuple


PreEdge = namedtuple(
    "PreEdge",
    ["src", "dst", "sx", "sy", "dx", "dy", "rank", "manhattan"],
)

PostEdge = namedtuple(
    "PostEdge",
    ["net", "branch", "sx", "sy", "dx", "dy", "manhattan",
     "chanx", "chany", "chan_hops", "rank"],
)


def load_pre_edges(pre_csv_path):
    """
    Leest de Top-N preRouting edges uit de CSV
    (output van find_longest_manhatten_edge.py).

    Verwacht header:
    rank,src,dst,src_x,src_y,dst_x,dst_y,dx,dy,manhattan
    """
    pre_edges_by_coord = {}
    pre_edges_list = []

    with open(pre_csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rank = int(row["rank"])
            except ValueError:
                # als er rare rijen zouden staan, sla die dan over
                continue

            src = row["src"]
            dst = row["dst"]
            sx = int(row["src_x"])
            sy = int(row["src_y"])
            dx = int(row["dst_x"])
            dy = int(row["dst_y"])
            manhattan = int(row["manhattan"])

            edge = PreEdge(
                src=src,
                dst=dst,
                sx=sx,
                sy=sy,
                dx=dx,
                dy=dy,
                rank=rank,
                manhattan=manhattan,
            )
            key = (sx, sy, dx, dy)

            # rank 1 is belangrijker dan rank 20 → bewaar de "beste" (laagste rank)
            if key not in pre_edges_by_coord or rank < pre_edges_by_coord[key].rank:
                pre_edges_by_coord[key] = edge

            pre_edges_list.append(edge)

    return pre_edges_by_coord, pre_edges_list


def load_post_edges(post_json_path, top_n):
    """
    Leest de volledige route_lut_graph.json in
    en selecteert de Top-N branches op basis van:
      - manhattan (aflopend)
      - chan_hops (aflopend)

    Alleen nets die geen PI/PO zijn (dus niet beginnen met 'pi' of 'po').
    """
    with open(post_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    luts = data.get("luts", {})
    branches = []

    for lut_id, info in luts.items():
        for rec in info.get("outgoing", []):
            net_name = rec.get("net", "")

            # filter PI/PO nets weg
            low = net_name.lower()
            if low.startswith("pi") or low.startswith("po"):
                continue

            (sx, sy) = rec.get("source_coord", [None, None])
            (dx, dy) = rec.get("sink_coord", [None, None])

            if sx is None or dx is None:
                continue

            manhattan = int(rec.get("manhattan", 0))
            chanx = int(rec.get("chanx_hops", 0))
            chany = int(rec.get("chany_hops", 0))
            chan_hops = int(rec.get("chan_hops", chanx + chany))

            branches.append({
                "net": net_name,
                "branch": int(rec.get("branch_index", 0)),
                "sx": sx,
                "sy": sy,
                "dx": dx,
                "dy": dy,
                "manhattan": manhattan,
                "chanx": chanx,
                "chany": chany,
                "chan_hops": chan_hops,
            })

    if not branches:
        return {}, []

    # Sorteer op: manhattan desc, dan chan_hops desc
    branches_sorted = sorted(
        branches,
        key=lambda b: (b["manhattan"], b["chan_hops"]),
        reverse=True,
    )

    # Top-N nemen (zelfde N als pre)
    branches_top = branches_sorted[:top_n]

    post_by_coord = {}
    post_list = []
    for idx, b in enumerate(branches_top, start=1):
        sx, sy, dx, dy = b["sx"], b["sy"], b["dx"], b["dy"]
        manhattan = b["manhattan"]
        chanx = b["chanx"]
        chany = b["chany"]
        chan_hops = b["chan_hops"]

        edge = PostEdge(
            net=b["net"],
            branch=b["branch"],
            sx=sx,
            sy=sy,
            dx=dx,
            dy=dy,
            manhattan=manhattan,
            chanx=chanx,
            chany=chany,
            chan_hops=chan_hops,
            rank=idx,
        )
        key = (sx, sy, dx, dy)

        # idem: als dezelfde coord-combo meerdere keren voorkomt,
        # bewaren we de beste (laagste rank)
        if key not in post_by_coord or idx < post_by_coord[key].rank:
            post_by_coord[key] = edge

        post_list.append(edge)

    return post_by_coord, post_list


def write_csv_and_summary(
    design,
    pre_map,
    pre_list,
    post_map,
    post_list,
    out_csv,
    out_txt,
):
    # Verzamel alle keys (coördinaatkoppels)
    pre_keys = set(pre_map.keys())
    post_keys = set(post_map.keys())
    all_keys = sorted(pre_keys | post_keys)

    # Overlap stats
    overlap_keys = pre_keys & post_keys
    n_pre = len(pre_keys)
    n_post = len(post_keys)
    n_overlap = len(overlap_keys)
    overlap_vs_pre = (n_overlap / n_pre * 100) if n_pre > 0 else 0.0
    overlap_vs_post = (n_overlap / n_post * 100) if n_post > 0 else 0.0

    # Gemiddelde manhattan (pre / post)
    avg_pre_man = sum(e.manhattan for e in pre_map.values()) / n_pre if n_pre else 0.0
    avg_post_man = sum(e.manhattan for e in post_map.values()) / n_post if n_post else 0.0

    # Gemiddelde stretch en chan-hops op overlap
    stretch_values = []
    chan_hops_values = []

    for key in overlap_keys:
        pre_e = pre_map[key]
        post_e = post_map[key]
        if pre_e.manhattan > 0:
            stretch = post_e.chan_hops / pre_e.manhattan
            stretch_values.append(stretch)
            chan_hops_values.append(post_e.chan_hops)

    avg_stretch = (sum(stretch_values) / len(stretch_values)) if stretch_values else 0.0
    avg_overlap_chan = (sum(chan_hops_values) / len(chan_hops_values)) if chan_hops_values else 0.0

    # ---- CSV schrijven ----
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)

    fieldnames = [
        "row_type",
        "src_lut",
        "dst_lut",
        "pre_in_top",
        "pre_rank",
        "pre_manhattan",
        "post_in_top",
        "post_rank",
        "post_manhattan",
        "post_chanx",
        "post_chany",
        "post_chan_hops",
        "post_stretch",
        "post_net",
        "post_branch",
        "metric",
        "value",
        "notes",
    ]

    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        # Edge-rijen
        for key in all_keys:
            sx, sy, dx, dy = key
            pre_e = pre_map.get(key)
            post_e = post_map.get(key)

            row = {
                "row_type": "edge",
                "src_lut": pre_e.src if pre_e else "",
                "dst_lut": pre_e.dst if pre_e else "",
                "pre_in_top": 1 if pre_e else 0,
                "pre_rank": pre_e.rank if pre_e else "",
                "pre_manhattan": pre_e.manhattan if pre_e else "",
                "post_in_top": 1 if post_e else 0,
                "post_rank": post_e.rank if post_e else "",
                "post_manhattan": post_e.manhattan if post_e else "",
                "post_chanx": post_e.chanx if post_e else "",
                "post_chany": post_e.chany if post_e else "",
                "post_chan_hops": post_e.chan_hops if post_e else "",
                "post_stretch": "",
                "post_net": post_e.net if post_e else "",
                "post_branch": post_e.branch if post_e else "",
                "metric": "",
                "value": "",
                "notes": "",
            }

            if pre_e and post_e and pre_e.manhattan > 0:
                stretch = post_e.chan_hops / pre_e.manhattan
                row["post_stretch"] = f"{stretch:.3f}"

            writer.writerow(row)

        # Summary-rijen
        summary_rows = [
            ("n_pre_edges", n_pre, "Unieke (src,dst) in preRouting topN"),
            ("n_post_edges", n_post, "Unieke (src,dst) in postRouting topN"),
            ("n_overlap", n_overlap, "Edges in beide top-lijsten"),
            ("overlap_pct_vs_pre", f"{overlap_vs_pre:.1f}%", "n_overlap / n_pre"),
            ("overlap_pct_vs_post", f"{overlap_vs_post:.1f}%", "n_overlap / n_post"),
            ("avg_pre_manhattan", f"{avg_pre_man:.3f}", ""),
            ("avg_post_manhattan", f"{avg_post_man:.3f}", ""),
            ("avg_overlap_chan_hops", f"{avg_overlap_chan:.3f}", ""),
            ("avg_overlap_stretch", f"{avg_stretch:.3f}", "gemiddelde (chan_hops / manhattan) op overlap-edges"),
        ]

        for metric, value, notes in summary_rows:
            writer.writerow({
                "row_type": "summary",
                "metric": metric,
                "value": value,
                "notes": notes,
            })

    # ---- Mooie TXT summary ----
    os.makedirs(os.path.dirname(out_txt), exist_ok=True)
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(f"Design: {design}\n")
        f.write("=" * (8 + len(design)) + "\n\n")

        f.write("OVERALL STATS\n")
        f.write("-------------\n")
        f.write(f"  # preRouting edges (TopN) : {n_pre}\n")
        f.write(f"  # postRouting edges (TopN): {n_post}\n")
        f.write(f"  Overlap (count)          : {n_overlap}\n")
        f.write(f"  Overlap vs preRouting    : {overlap_vs_pre:.1f}%\n")
        f.write(f"  Overlap vs postRouting   : {overlap_vs_post:.1f}%\n")
        f.write(f"  Avg pre manhattan        : {avg_pre_man:.3f}\n")
        f.write(f"  Avg post manhattan       : {avg_post_man:.3f}\n")
        f.write(f"  Avg overlap chan hops    : {avg_overlap_chan:.3f}\n")
        f.write(f"  Avg overlap stretch      : {avg_stretch:.3f}\n")
        f.write("\n")

        if overlap_keys:
            f.write("OVERLAP EDGES (in beide TopN)\n")
            f.write("-----------------------------\n")
            # sorteer op pre-rank
            overlap_edges = []
            for key in overlap_keys:
                pre_e = pre_map[key]
                post_e = post_map[key]
                if pre_e.manhattan > 0:
                    stretch = post_e.chan_hops / pre_e.manhattan
                else:
                    stretch = 0.0
                overlap_edges.append((pre_e.rank, pre_e, post_e, stretch))

            overlap_edges.sort(key=lambda t: t[0])

            for pre_rank, pre_e, post_e, stretch in overlap_edges:
                f.write(
                    f"- Edge {pre_e.src} -> {pre_e.dst} "
                    f"({pre_e.sx},{pre_e.sy}) → ({pre_e.dx},{pre_e.dy})\n"
                )
                f.write(
                    f"    pre: rank={pre_e.rank}, manhattan={pre_e.manhattan}\n"
                )
                f.write(
                    f"    post: rank={post_e.rank}, net={post_e.net}, "
                    f"branch={post_e.branch}, manhattan={post_e.manhattan}, "
                    f"CHAN hops={post_e.chan_hops} "
                    f"(CHANX={post_e.chanx}, CHANY={post_e.chany})\n"
                )
                f.write(f"    stretch = post_chan_hops / pre_manhattan = {stretch:.3f}\n\n")
        else:
            f.write("Geen overlap tussen preRouting en postRouting TopN edges.\n")

    print(f"CSV geschreven naar: {out_csv}")
    print(f"TXT summary geschreven naar: {out_txt}")


def main():
    ap = argparse.ArgumentParser(
        description="Vergelijk preRouting TopN manhattan-edges met postRouting route-lut-graph."
    )
    ap.add_argument("--design", required=True, help="Design naam (bv. example_big_300)")
    ap.add_argument("--pre-csv", required=True, help="Pad naar preRouting TopN CSV (manhattan-edges)")
    ap.add_argument("--post-json", required=True, help="Pad naar postRouting route_lut_graph.json")
    ap.add_argument("--out-csv", required=True, help="Output CSV (analyse)")
    ap.add_argument("--out-txt", required=True, help="Output TXT summary")

    args = ap.parse_args()

    pre_map, pre_list = load_pre_edges(args.pre_csv)
    if not pre_list:
        raise SystemExit(f"Geen preRouting edges gevonden in {args.pre_csv}")

    top_n = len(pre_map)  # zelfde N voor postRouting
    post_map, post_list = load_post_edges(args.post_json, top_n)
    if not post_list:
        raise SystemExit(f"Geen postRouting edges gevonden in {args.post_json}")

    write_csv_and_summary(
        design=args.design,
        pre_map=pre_map,
        pre_list=pre_list,
        post_map=post_map,
        post_list=post_list,
        out_csv=args.out_csv,
        out_txt=args.out_txt,
    )


if __name__ == "__main__":
    main()
