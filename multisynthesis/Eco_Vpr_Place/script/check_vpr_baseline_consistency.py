#!/usr/bin/env python3
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def fail(msg):
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg):
    print(f"[WARN] {msg}")


def ok(msg):
    print(f"[OK] {msg}")


def parse_place(path):
    placed = {}
    coords = {}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("#"):
                continue
            if line.startswith("Netlist_File:"):
                continue
            if line.startswith("Array size:"):
                continue

            parts = line.split()
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
                "raw": line,
            }

            key = (x, y, subblk, layer)
            coords.setdefault(key, []).append(name)

    return placed, coords


def parse_top_level_net_blocks(path):
    tree = ET.parse(path)
    root = tree.getroot()

    direct_blocks = {}
    for child in root:
        if child.tag == "block":
            name = child.attrib.get("name")
            instance = child.attrib.get("instance")
            if name:
                direct_blocks[name] = instance

    top_inputs = []
    top_outputs = []

    inputs_node = root.find("inputs")
    outputs_node = root.find("outputs")

    if inputs_node is not None and inputs_node.text:
        top_inputs = inputs_node.text.split()

    if outputs_node is not None and outputs_node.text:
        top_outputs = outputs_node.text.split()

    return direct_blocks, top_inputs, top_outputs


def parse_blif(path):
    model = None
    inputs = []
    outputs = []
    names_outputs = []
    names_blocks = []

    current_names = None

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue

            if s.startswith(".model"):
                parts = s.split()
                if len(parts) >= 2:
                    model = parts[1]

            elif s.startswith(".inputs"):
                inputs.extend(s.split()[1:])

            elif s.startswith(".outputs"):
                outputs.extend(s.split()[1:])

            elif s.startswith(".names"):
                parts = s.split()
                if len(parts) < 2:
                    fail(f"Ongeldige .names regel: {s}")
                out = parts[-1]
                names_outputs.append(out)
                names_blocks.append(parts[1:])

    return {
        "model": model,
        "inputs": inputs,
        "outputs": outputs,
        "names_outputs": names_outputs,
        "names_blocks": names_blocks,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--place", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    blif_path = Path(args.blif)
    net_path = Path(args.net)
    place_path = Path(args.place)

    for p in [blif_path, net_path, place_path]:
        if not p.exists() or p.stat().st_size == 0:
            fail(f"Bestand ontbreekt of is leeg: {p}")

    blif = parse_blif(blif_path)
    net_blocks, net_inputs, net_outputs = parse_top_level_net_blocks(net_path)
    placed, coords = parse_place(place_path)

    ok(f"BLIF gelezen: {blif_path}")
    ok(f"NET gelezen: {net_path}")
    ok(f"PLACE gelezen: {place_path}")

    if blif["model"] is None:
        fail("BLIF heeft geen .model")

    if not blif["inputs"]:
        fail("BLIF heeft geen .inputs")

    if not blif["outputs"]:
        fail("BLIF heeft geen .outputs")

    if not blif["names_outputs"]:
        fail("BLIF heeft geen .names blocks")

    ok(f"BLIF model = {blif['model']}")
    ok(f"BLIF inputs = {len(blif['inputs'])}")
    ok(f"BLIF outputs = {len(blif['outputs'])}")
    ok(f"BLIF .names blocks = {len(blif['names_outputs'])}")

    ok(f"NET top-level blocks = {len(net_blocks)}")
    ok(f"PLACE blocks = {len(placed)}")

    missing_place = sorted([b for b in net_blocks if b not in placed])
    extra_place = sorted([b for b in placed if b not in net_blocks])

    if missing_place:
        fail(f"Blocks in .net maar niet in .place: {missing_place[:20]}")

    if extra_place:
        warn(f"Blocks in .place maar niet als direct top-level .net block: {extra_place[:20]}")

    duplicate_coords = {
        str(k): v for k, v in coords.items()
        if len(v) > 1
    }

    if duplicate_coords:
        fail(f"Meerdere blocks op dezelfde x/y/subblk/layer: {duplicate_coords}")

    ok("Elke top-level .net block heeft een plaats in .place")
    ok("Geen dubbele fysieke locaties in .place")

    lut_blocks_net = sorted([b for b in net_blocks if re.match(r"^LUT_", b)])
    lut_blocks_place = sorted([b for b in placed if re.match(r"^LUT_", b)])
    lut_outputs_blif = sorted([o for o in blif["names_outputs"] if re.match(r"^LUT_", o)])

    missing_lut_in_blif = sorted(set(lut_blocks_net) - set(lut_outputs_blif))
    if missing_lut_in_blif:
        fail(f"LUT-blocks in .net maar geen LUT-output in BLIF: {missing_lut_in_blif[:20]}")

    ok(f"LUT blocks in NET = {len(lut_blocks_net)}")
    ok(f"LUT blocks in PLACE = {len(lut_blocks_place)}")
    ok(f"LUT outputs in BLIF = {len(lut_outputs_blif)}")

    report = {
        "status": "OK",
        "blif": str(blif_path),
        "net": str(net_path),
        "place": str(place_path),
        "blif_model": blif["model"],
        "num_blif_inputs": len(blif["inputs"]),
        "num_blif_outputs": len(blif["outputs"]),
        "num_blif_names": len(blif["names_outputs"]),
        "num_net_top_blocks": len(net_blocks),
        "num_place_blocks": len(placed),
        "num_lut_blocks_net": len(lut_blocks_net),
        "num_lut_blocks_place": len(lut_blocks_place),
        "num_lut_outputs_blif": len(lut_outputs_blif),
        "warnings": {
            "extra_place_blocks_not_direct_net_blocks": extra_place,
        },
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    ok(f"Report geschreven naar: {args.out}")


if __name__ == "__main__":
    main()
