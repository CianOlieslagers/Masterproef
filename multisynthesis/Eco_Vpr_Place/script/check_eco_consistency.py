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


def ok(msg):
    print(f"[OK] {msg}")


def parse_place(path):
    blocks = {}
    occupied = {}

    with open(path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            s = line.strip()

            if not s:
                continue
            if s.startswith("#"):
                continue
            if s.startswith("Netlist_File:"):
                continue
            if s.startswith("Array size:"):
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
                fail(f"Ongeldige .place regel op lijn {idx}: {line.rstrip()}")

            if name in blocks:
                fail(f"Dubbele blocknaam in .place: {name}")

            key = (x, y, subblk, layer)
            if key in occupied:
                fail(f"Dubbele locatie in .place: {key}, blocks: {occupied[key]} en {name}")

            blocks[name] = {
                "x": x,
                "y": y,
                "subblk": subblk,
                "layer": layer,
                "line": idx,
            }
            occupied[key] = name

    return blocks


def parse_blif(path):
    blocks = {}
    names_count = 0
    inputs = []
    outputs = []

    with open(path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            s = line.strip()

            if not s or s.startswith("#"):
                continue

            if s.startswith(".inputs"):
                inputs.extend(s.split()[1:])
                continue

            if s.startswith(".outputs"):
                outputs.extend(s.split()[1:])
                continue

            if s.startswith(".names"):
                parts = s.split()
                if len(parts) < 2:
                    fail(f"Ongeldige .names regel op lijn {idx}: {s}")

                out = parts[-1]
                ins = parts[1:-1]

                if out in blocks:
                    fail(f"Dubbele .names-output in BLIF: {out}")

                blocks[out] = {
                    "inputs": ins,
                    "line": idx,
                    "raw": s,
                }
                names_count += 1

    return {
        "inputs": inputs,
        "outputs": outputs,
        "blocks": blocks,
        "names_count": names_count,
    }


def parse_net(path):
    tree = ET.parse(path)
    root = tree.getroot()

    top_blocks = {}

    for child in root:
        if child.tag != "block":
            continue

        name = child.attrib.get("name")
        instance = child.attrib.get("instance")

        if not name:
            fail("Top-level block zonder naam gevonden in .net")

        if name in top_blocks:
            fail(f"Dubbele top-level blocknaam in .net: {name}")

        inputs_I = []
        outputs_O = []

        inputs_node = child.find("inputs")
        if inputs_node is not None:
            for port in inputs_node.findall("port"):
                if port.attrib.get("name") == "I" and port.text:
                    inputs_I = port.text.split()

        outputs_node = child.find("outputs")
        if outputs_node is not None:
            for port in outputs_node.findall("port"):
                if port.attrib.get("name") == "O" and port.text:
                    outputs_O = port.text.split()

        primitive_outputs = []
        primitive_inputs = []

        for elem in child.iter("block"):
            if elem.attrib.get("instance") == "lut[0]":
                in_node = elem.find("inputs")
                out_node = elem.find("outputs")

                if in_node is not None:
                    for port in in_node.findall("port"):
                        if port.attrib.get("name") == "in" and port.text:
                            primitive_inputs = port.text.split()

                if out_node is not None:
                    for port in out_node.findall("port"):
                        if port.attrib.get("name") == "out" and port.text:
                            primitive_outputs = port.text.split()

        top_blocks[name] = {
            "instance": instance,
            "inputs_I": inputs_I,
            "outputs_O": outputs_O,
            "primitive_inputs": primitive_inputs,
            "primitive_outputs": primitive_outputs,
        }

    return top_blocks


def coords_equal(a, b):
    return (
        a["x"] == b["x"]
        and a["y"] == b["y"]
        and a["subblk"] == b["subblk"]
        and a["layer"] == b["layer"]
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)

    ap.add_argument("--baseline-blif", required=True)
    ap.add_argument("--baseline-net", required=True)
    ap.add_argument("--baseline-place", required=True)

    ap.add_argument("--patched-blif", required=True)
    ap.add_argument("--patched-net", required=True)
    ap.add_argument("--patched-place", required=True)

    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    paths = [
        args.candidate,
        args.baseline_blif,
        args.baseline_net,
        args.baseline_place,
        args.patched_blif,
        args.patched_net,
        args.patched_place,
    ]

    for p in paths:
        pp = Path(p)
        if not pp.exists() or pp.stat().st_size == 0:
            fail(f"Bestand ontbreekt of is leeg: {p}")

    with open(args.candidate, "r", encoding="utf-8") as f:
        cand = json.load(f)

    if cand.get("status") != "OK":
        fail("Candidate status is niet OK")

    source = cand["source_block"]
    sink = cand["sink_block"]
    old_net = cand["old_net"]
    buffer_block = cand["buffer_block"]
    buffer_net = cand["buffer_net"]

    baseline_blif = parse_blif(args.baseline_blif)
    patched_blif = parse_blif(args.patched_blif)

    baseline_net = parse_net(args.baseline_net)
    patched_net = parse_net(args.patched_net)

    baseline_place = parse_place(args.baseline_place)
    patched_place = parse_place(args.patched_place)

    # ----------------------------
    # Count checks
    # ----------------------------

    if patched_blif["names_count"] != baseline_blif["names_count"] + 1:
        fail("BLIF .names-count is niet exact +1")

    if len(patched_net) != len(baseline_net) + 1:
        fail("NET top-level block count is niet exact +1")

    if len(patched_place) != len(baseline_place) + 1:
        fail("PLACE block count is niet exact +1")

    ok("BLIF/NET/PLACE hebben elk exact één extra element")

    # ----------------------------
    # Existing blocks unchanged in PLACE
    # ----------------------------

    for block, base_loc in baseline_place.items():
        if block not in patched_place:
            fail(f"Baseline block ontbreekt in patched.place: {block}")

        if not coords_equal(base_loc, patched_place[block]):
            fail(
                f"Block is verplaatst in patched.place: {block} "
                f"baseline={base_loc}, patched={patched_place[block]}"
            )

    added_place_blocks = sorted(set(patched_place) - set(baseline_place))
    if added_place_blocks != [buffer_block]:
        fail(f"Onverwachte extra blocks in patched.place: {added_place_blocks}")

    ok("Alle bestaande blocks behouden exact dezelfde plaats")
    ok("Alleen buffer-block is toegevoegd aan PLACE")

    # ----------------------------
    # NET block checks
    # ----------------------------

    added_net_blocks = sorted(set(patched_net) - set(baseline_net))
    if added_net_blocks != [buffer_block]:
        fail(f"Onverwachte extra blocks in patched.net: {added_net_blocks}")

    if buffer_block not in patched_net:
        fail("Buffer block ontbreekt in patched.net")

    if source not in patched_net:
        fail("Source block ontbreekt in patched.net")

    if sink not in patched_net:
        fail("Sink block ontbreekt in patched.net")

    if old_net not in patched_net[buffer_block]["inputs_I"]:
        fail("Buffer gebruikt old_net niet als top-level I-input in patched.net")

    if patched_net[buffer_block]["primitive_outputs"] != [buffer_net]:
        fail(
            "Buffer primitive LUT output is niet correct: "
            f"{patched_net[buffer_block]['primitive_outputs']}"
        )

    if old_net in patched_net[sink]["inputs_I"]:
        fail("Sink gebruikt old_net nog rechtstreeks in patched.net")

    if buffer_net not in patched_net[sink]["inputs_I"]:
        fail("Sink gebruikt buffer_net niet in patched.net")

    ok("NET ECO-structuur klopt")

    # ----------------------------
    # BLIF checks
    # ----------------------------

    if buffer_net not in patched_blif["blocks"]:
        fail("Buffer net ontbreekt als .names-output in patched.blif")

    if patched_blif["blocks"][buffer_net]["inputs"] != [old_net]:
        fail(
            "Buffer BLIF-input is niet exact old_net: "
            f"{patched_blif['blocks'][buffer_net]['inputs']}"
        )

    if sink not in patched_blif["blocks"]:
        fail("Sink ontbreekt als .names-output in patched.blif")

    if old_net in patched_blif["blocks"][sink]["inputs"]:
        fail("Sink gebruikt old_net nog rechtstreeks in patched.blif")

    if buffer_net not in patched_blif["blocks"][sink]["inputs"]:
        fail("Sink gebruikt buffer_net niet in patched.blif")

    ok("BLIF ECO-structuur klopt")

    # ----------------------------
    # Cross-checks NET <-> PLACE
    # ----------------------------

    missing_place = sorted(set(patched_net) - set(patched_place))
    extra_place = sorted(set(patched_place) - set(patched_net))

    if missing_place:
        fail(f"Blocks in patched.net maar niet in patched.place: {missing_place}")

    if extra_place:
        fail(f"Blocks in patched.place maar niet in patched.net: {extra_place}")

    ok("patched.net en patched.place hebben dezelfde top-level blocks")

    report = {
        "status": "OK",
        "source_block": source,
        "sink_block": sink,
        "old_net": old_net,
        "buffer_block": buffer_block,
        "buffer_net": buffer_net,
        "counts": {
            "baseline_blif_names": baseline_blif["names_count"],
            "patched_blif_names": patched_blif["names_count"],
            "baseline_net_blocks": len(baseline_net),
            "patched_net_blocks": len(patched_net),
            "baseline_place_blocks": len(baseline_place),
            "patched_place_blocks": len(patched_place),
        },
        "buffer_place": patched_place[buffer_block],
        "patched_sink_blif_inputs": patched_blif["blocks"][sink]["inputs"],
        "patched_sink_net_inputs_I": patched_net[sink]["inputs_I"],
        "patched_buffer_net_inputs_I": patched_net[buffer_block]["inputs_I"],
        "patched_buffer_primitive_outputs": patched_net[buffer_block]["primitive_outputs"],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    ok(f"ECO consistency report geschreven naar: {out}")


if __name__ == "__main__":
    main()
