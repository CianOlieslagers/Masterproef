#!/usr/bin/env python3
import argparse
import csv
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def fail(msg):
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg):
    print(f"[OK] {msg}")


def parse_place(path):
    placed = {}
    occupied = set()
    array_size = None

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue

            if s.startswith("Array size:"):
                # Example: Array size: 103 x 103 logic blocks
                m = re.search(r"Array size:\s+(\d+)\s+x\s+(\d+)", s)
                if m:
                    array_size = (int(m.group(1)), int(m.group(2)))
                continue

            if s.startswith("#") or s.startswith("Netlist_File:"):
                continue

            parts = s.split()
            if len(parts) < 5:
                continue

            name = parts[0]
            try:
                x = int(parts[1])
                y = int(parts[2])
                subblk = int(parts[3])
                layer = int(parts[4])
            except ValueError:
                continue

            placed[name] = {
                "x": x,
                "y": y,
                "subblk": subblk,
                "layer": layer,
                "raw": line.rstrip("\n"),
            }
            occupied.add((x, y, subblk, layer))

    if array_size is None:
        fail("Kon Array size niet lezen uit .place")

    return placed, occupied, array_size


def parse_blif_names(path):
    """
    Returns:
      blocks[output_net] = [input_net_0, input_net_1, ...]
    """
    blocks = {}
    primary_inputs = []
    primary_outputs = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue

            if s.startswith(".inputs"):
                primary_inputs.extend(s.split()[1:])
                continue

            if s.startswith(".outputs"):
                primary_outputs.extend(s.split()[1:])
                continue

            if s.startswith(".names"):
                parts = s.split()
                if len(parts) < 2:
                    fail(f"Ongeldige .names regel: {s}")
                output = parts[-1]
                inputs = parts[1:-1]
                blocks[output] = inputs

    return blocks, primary_inputs, primary_outputs


def parse_net_top_blocks(path):
    """
    Reads only top-level clb blocks.
    Returns:
      top_blocks[name] = {
        "instance": "...",
        "inputs_I": [...],
        "outputs_O": [...]
      }
    """
    tree = ET.parse(path)
    root = tree.getroot()

    top_blocks = {}

    for child in root:
        if child.tag != "block":
            continue

        name = child.attrib.get("name")
        instance = child.attrib.get("instance")

        inputs_I = []
        outputs_O = []

        inputs_node = child.find("inputs")
        if inputs_node is not None:
            for port in inputs_node.findall("port"):
                if port.attrib.get("name") == "I":
                    if port.text:
                        inputs_I = port.text.split()

        outputs_node = child.find("outputs")
        if outputs_node is not None:
            for port in outputs_node.findall("port"):
                if port.attrib.get("name") == "O":
                    if port.text:
                        outputs_O = port.text.split()

        if name:
            top_blocks[name] = {
                "instance": instance,
                "inputs_I": inputs_I,
                "outputs_O": outputs_O,
            }

    return top_blocks


def read_top_csv(path, max_rows):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            if len(rows) >= max_rows:
                break
    return rows


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def find_free_buffer_location(src_xy, dst_xy, occupied, array_size, max_extra_distance=4):
    """
    Finds a free location close to the midpoint.
    We avoid y=0 because your IOs are placed there.
    We use subblk=0, layer=0 for now, because your current LUTs all use that.
    """
    width, height = array_size

    direct = manhattan(src_xy, dst_xy)
    mid_x = round((src_xy[0] + dst_xy[0]) / 2)
    mid_y = round((src_xy[1] + dst_xy[1]) / 2)

    candidates = []

    # Search a reasonable region around the source/sink box.
    min_x = max(1, min(src_xy[0], dst_xy[0]) - 8)
    max_x = min(width - 2, max(src_xy[0], dst_xy[0]) + 8)
    min_y = max(1, min(src_xy[1], dst_xy[1]) - 8)
    max_y = min(height - 2, max(src_xy[1], dst_xy[1]) + 8)

    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            key = (x, y, 0, 0)
            if key in occupied:
                continue

            buf_xy = (x, y)
            d1 = manhattan(src_xy, buf_xy)
            d2 = manhattan(buf_xy, dst_xy)
            total = d1 + d2
            extra = total - direct
            balance = abs(d1 - d2)
            mid_dist = manhattan(buf_xy, (mid_x, mid_y))

            if extra <= max_extra_distance:
                candidates.append({
                    "x": x,
                    "y": y,
                    "subblk": 0,
                    "layer": 0,
                    "source_to_buffer_manhattan": d1,
                    "buffer_to_sink_manhattan": d2,
                    "split_total_manhattan": total,
                    "direct_manhattan": direct,
                    "extra_manhattan": extra,
                    "balance": balance,
                    "midpoint_distance": mid_dist,
                })

    if not candidates:
        return None

    # Prefer:
    # 1. little extra distance
    # 2. close to midpoint
    # 3. balanced source-buffer and buffer-sink distances
    candidates.sort(key=lambda c: (
        c["extra_manhattan"],
        c["midpoint_distance"],
        c["balance"],
        c["x"],
        c["y"],
    ))

    return candidates[0]


def validate_row(row, placed, blif_blocks, top_blocks):
    src = row["src"]
    dst = row["dst"]

    reasons = []

    if not src.startswith("LUT_"):
        reasons.append("source is geen LUT")
    if not dst.startswith("LUT_"):
        reasons.append("sink is geen LUT")

    if src not in placed:
        reasons.append("source niet in .place")
    if dst not in placed:
        reasons.append("sink niet in .place")

    if src not in blif_blocks:
        reasons.append("source output niet als .names-output in BLIF")
    if dst not in blif_blocks:
        reasons.append("sink output niet als .names-output in BLIF")
    else:
        if src not in blif_blocks[dst]:
            reasons.append("sink gebruikt source-net niet in BLIF")

    if src not in top_blocks:
        reasons.append("source niet als top-level block in .net")
    if dst not in top_blocks:
        reasons.append("sink niet als top-level block in .net")
    else:
        if src not in top_blocks[dst]["inputs_I"]:
            reasons.append("sink gebruikt source-net niet in .net top-level I-port")

    return reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="top20_manhattan.csv")
    ap.add_argument("--blif", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--place", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-rows", type=int, default=20)
    args = ap.parse_args()

    for p in [args.csv, args.blif, args.net, args.place]:
        if not Path(p).exists() or Path(p).stat().st_size == 0:
            fail(f"Bestand ontbreekt of is leeg: {p}")

    placed, occupied, array_size = parse_place(args.place)
    blif_blocks, primary_inputs, primary_outputs = parse_blif_names(args.blif)
    top_blocks = parse_net_top_blocks(args.net)
    rows = read_top_csv(args.csv, args.max_rows)

    considered = []

    for row in rows:
        src = row["src"]
        dst = row["dst"]

        reasons = validate_row(row, placed, blif_blocks, top_blocks)

        item = {
            "rank": int(row["rank"]),
            "src": src,
            "dst": dst,
            "csv_manhattan": int(row["manhattan"]),
            "valid": len(reasons) == 0,
            "reject_reasons": reasons,
        }

        if reasons:
            considered.append(item)
            continue

        src_xy = (placed[src]["x"], placed[src]["y"])
        dst_xy = (placed[dst]["x"], placed[dst]["y"])

        loc = find_free_buffer_location(
            src_xy=src_xy,
            dst_xy=dst_xy,
            occupied=occupied,
            array_size=array_size,
        )

        if loc is None:
            item["valid"] = False
            item["reject_reasons"] = ["geen vrije bufferlocatie gevonden"]
            considered.append(item)
            continue

        buffer_block = f"ECO_BUF_{src}_TO_{dst}"
        buffer_net = buffer_block

        candidate = {
            "status": "OK",
            "design": Path(args.blif).stem.replace(".mapped", ""),
            "source_block": src,
            "sink_block": dst,
            "old_net": src,
            "buffer_block": buffer_block,
            "buffer_net": buffer_net,
            "source": {
                "x": src_xy[0],
                "y": src_xy[1],
                "subblk": placed[src]["subblk"],
                "layer": placed[src]["layer"],
            },
            "sink": {
                "x": dst_xy[0],
                "y": dst_xy[1],
                "subblk": placed[dst]["subblk"],
                "layer": placed[dst]["layer"],
            },
            "buffer_location": loc,
            "blif": {
                "sink_inputs_before": blif_blocks[dst],
                "source_output_exists": src in blif_blocks,
                "sink_uses_old_net": src in blif_blocks[dst],
            },
            "net": {
                "sink_inputs_I_before": top_blocks[dst]["inputs_I"],
                "sink_uses_old_net": src in top_blocks[dst]["inputs_I"],
                "source_instance": top_blocks[src]["instance"],
                "sink_instance": top_blocks[dst]["instance"],
            },
            "selection": {
                "rank": int(row["rank"]),
                "csv_direct_manhattan": int(row["manhattan"]),
                "note": "First valid LUT-to-LUT candidate from top Manhattan CSV with a free nearby buffer location."
            },
            "considered_candidates": considered + [item],
        }

        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(candidate, f, indent=2)

        ok(f"Kandidaat gekozen: {src} -> {dst}")
        ok(f"old_net      = {src}")
        ok(f"buffer_block = {buffer_block}")
        ok(f"buffer_net   = {buffer_net}")
        ok(f"buffer loc   = ({loc['x']}, {loc['y']}, subblk={loc['subblk']}, layer={loc['layer']})")
        ok(f"direct manhattan = {loc['direct_manhattan']}")
        ok(f"split manhattan  = {loc['split_total_manhattan']}")
        ok(f"Report geschreven naar: {args.out}")
        return

    report = {
        "status": "FAIL",
        "reason": "Geen geldige kandidaat gevonden",
        "considered_candidates": considered,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    fail(f"Geen geldige kandidaat gevonden. Zie {args.out}")


if __name__ == "__main__":
    main()
