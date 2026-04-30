#!/usr/bin/env python3
import argparse
import copy
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom


def fail(msg):
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg):
    print(f"[OK] {msg}")


def find_direct_top_block(root, name):
    for child in root:
        if child.tag == "block" and child.attrib.get("name") == name:
            return child
    return None


def find_child_port(block, section_name, port_name):
    section = block.find(section_name)
    if section is None:
        return None

    for port in section.findall("port"):
        if port.attrib.get("name") == port_name:
            return port

    return None


def get_port_tokens(block, section_name, port_name):
    port = find_child_port(block, section_name, port_name)
    if port is None or port.text is None:
        return []
    return port.text.split()


def set_port_tokens(block, section_name, port_name, tokens):
    port = find_child_port(block, section_name, port_name)
    if port is None:
        fail(f"Port niet gevonden: {section_name}/{port_name} in block {block.attrib.get('name')}")
    port.text = " ".join(tokens)


def find_nested_blocks_by_name(block, name):
    result = []
    for elem in block.iter("block"):
        if elem.attrib.get("name") == name:
            result.append(elem)
    return result


def get_next_clb_instance(root):
    max_idx = -1
    for child in root:
        if child.tag != "block":
            continue
        inst = child.attrib.get("instance", "")
        m = re.match(r"clb\[(\d+)\]", inst)
        if m:
            max_idx = max(max_idx, int(m.group(1)))
    return f"clb[{max_idx + 1}]"


def rename_all_nested_blocks(block, new_name):
    for elem in block.iter("block"):
        elem.attrib["name"] = new_name


def configure_buffer_block(block, buffer_block, old_net, buffer_net, new_instance):
    """
    Maakt van een bestaande LUT/CLB-template een 1-input buffer-LUT.

    Structuur wordt:
      top clb I-port: old_net open open open
      inner lut4 input: clb.I[0]->direct1 open open open
      primitive lut input: lut4.in[0]->direct:lut4 open open open
      primitive lut output: buffer_net
    """

    block.attrib["name"] = buffer_block
    block.attrib["instance"] = new_instance

    rename_all_nested_blocks(block, buffer_block)

    # Top-level CLB
    set_port_tokens(block, "inputs", "I", [old_net, "open", "open", "open"])

    # Output routing inside the clb remains architecture-specific direct wire.
    set_port_tokens(block, "outputs", "O", ["lut4[0].out[0]->direct2"])

    clk_port = find_child_port(block, "clocks", "clk")
    if clk_port is not None:
        clk_port.text = "open"

    # Find lut4 and primitive lut blocks.
    lut4_block = None
    primitive_lut_block = None

    for elem in block.iter("block"):
        inst = elem.attrib.get("instance", "")
        if inst == "lut4[0]":
            lut4_block = elem
        elif inst == "lut[0]":
            primitive_lut_block = elem

    if lut4_block is None:
        fail("Kon nested lut4[0] block niet vinden in template")

    if primitive_lut_block is None:
        fail("Kon nested lut[0] block niet vinden in template")

    # Internal lut4 wrapper.
    set_port_tokens(
        lut4_block,
        "inputs",
        "in",
        ["clb.I[0]->direct1", "open", "open", "open"]
    )

    set_port_tokens(
        lut4_block,
        "outputs",
        "out",
        ["lut[0].out[0]->direct:lut4"]
    )

    # Primitive LUT.
    set_port_tokens(
        primitive_lut_block,
        "inputs",
        "in",
        ["lut4.in[0]->direct:lut4", "open", "open", "open"]
    )

    # port_rotation_map moet overeenkomen met één gebruikte logische input.
    inputs_node = primitive_lut_block.find("inputs")
    if inputs_node is None:
        fail("Primitive LUT heeft geen inputs-node")

    prm = None
    for elem in inputs_node.findall("port_rotation_map"):
        if elem.attrib.get("name") == "in":
            prm = elem
            break

    if prm is None:
        prm = ET.SubElement(inputs_node, "port_rotation_map", {"name": "in"})

    prm.text = "0"

    set_port_tokens(
        primitive_lut_block,
        "outputs",
        "out",
        [buffer_net]
    )


def pretty_write_xml(root, out_path):
    raw = ET.tostring(root, encoding="utf-8")
    parsed = minidom.parseString(raw)
    pretty = parsed.toprettyxml(indent="\t")

    # Verwijder lege whitespace-only regels.
    lines = [line for line in pretty.splitlines() if line.strip()]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-net", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out-net", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    in_net = Path(args.in_net)
    cand_path = Path(args.candidate)
    out_net = Path(args.out_net)
    report_path = Path(args.report)

    if not in_net.exists() or in_net.stat().st_size == 0:
        fail(f"Input .net ontbreekt of is leeg: {in_net}")

    if not cand_path.exists() or cand_path.stat().st_size == 0:
        fail(f"Candidate JSON ontbreekt of is leeg: {cand_path}")

    with open(cand_path, "r", encoding="utf-8") as f:
        cand = json.load(f)

    if cand.get("status") != "OK":
        fail("Candidate status is niet OK")

    source_block = cand["source_block"]
    sink_block = cand["sink_block"]
    old_net = cand["old_net"]
    buffer_block = cand["buffer_block"]
    buffer_net = cand["buffer_net"]

    tree = ET.parse(in_net)
    root = tree.getroot()

    source_elem = find_direct_top_block(root, source_block)
    sink_elem = find_direct_top_block(root, sink_block)
    existing_buffer = find_direct_top_block(root, buffer_block)

    if source_elem is None:
        fail(f"source_block niet gevonden als top-level block in .net: {source_block}")

    if sink_elem is None:
        fail(f"sink_block niet gevonden als top-level block in .net: {sink_block}")

    if existing_buffer is not None:
        fail(f"buffer_block bestaat al in .net: {buffer_block}")

    sink_inputs_before = get_port_tokens(sink_elem, "inputs", "I")

    if old_net not in sink_inputs_before:
        fail(f"old_net {old_net} zit niet in sink I-port van {sink_block}")

    if sink_inputs_before.count(old_net) != 1:
        fail(f"old_net {old_net} komt niet exact één keer voor in sink I-port")

    # Vervang in sink-inputs enkel deze directe verbinding.
    sink_inputs_after = [
        buffer_net if token == old_net else token
        for token in sink_inputs_before
    ]

    set_port_tokens(sink_elem, "inputs", "I", sink_inputs_after)

    # Maak nieuw bufferblock door een bestaande LUT/CLB-template te kopiëren.
    # We gebruiken source_elem als template omdat dat zeker een geldige LUT-CLB structuur heeft.
    buffer_elem = copy.deepcopy(source_elem)
    new_instance = get_next_clb_instance(root)

    configure_buffer_block(
        buffer_elem,
        buffer_block=buffer_block,
        old_net=old_net,
        buffer_net=buffer_net,
        new_instance=new_instance,
    )

    # Voeg de buffer toe net voor de sink, zodat de XML logisch leesbaar blijft.
    children = list(root)
    sink_index = children.index(sink_elem)
    root.insert(sink_index, buffer_elem)

    # Checks na patch.
    buffer_check = find_direct_top_block(root, buffer_block)
    if buffer_check is None:
        fail("Bufferblock niet aanwezig na patch")

    sink_check = find_direct_top_block(root, sink_block)
    sink_inputs_final = get_port_tokens(sink_check, "inputs", "I")

    if old_net in sink_inputs_final:
        fail("old_net zit nog steeds rechtstreeks in sink I-port na patch")

    if buffer_net not in sink_inputs_final:
        fail("buffer_net zit niet in sink I-port na patch")

    buffer_inputs = get_port_tokens(buffer_check, "inputs", "I")
    buffer_outputs = get_port_tokens(buffer_check, "outputs", "O")

    if buffer_inputs[0] != old_net:
        fail("Buffer input[0] is niet old_net")

    primitive_lut = None
    for elem in buffer_check.iter("block"):
        if elem.attrib.get("instance") == "lut[0]":
            primitive_lut = elem
            break

    if primitive_lut is None:
        fail("Primitive lut[0] niet gevonden in bufferblock")

    primitive_outputs = get_port_tokens(primitive_lut, "outputs", "out")
    if primitive_outputs != [buffer_net]:
        fail(f"Primitive LUT output fout: {primitive_outputs}")

    out_net.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    pretty_write_xml(root, out_net)

    top_blocks = [c.attrib.get("name") for c in root if c.tag == "block"]

    report = {
        "status": "OK",
        "input_net": str(in_net),
        "output_net": str(out_net),
        "candidate": str(cand_path),
        "source_block": source_block,
        "sink_block": sink_block,
        "old_net": old_net,
        "buffer_block": buffer_block,
        "buffer_net": buffer_net,
        "new_buffer_instance": new_instance,
        "sink_inputs_before": sink_inputs_before,
        "sink_inputs_after": sink_inputs_after,
        "buffer_top_inputs_I": buffer_inputs,
        "buffer_top_outputs_O": buffer_outputs,
        "buffer_primitive_output": primitive_outputs,
        "num_top_blocks_after": len(top_blocks),
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    ok(f".net gepatcht: {out_net}")
    ok(f"Report geschreven: {report_path}")
    ok(f"Sink voor patch: {' '.join(sink_inputs_before)}")
    ok(f"Sink na patch  : {' '.join(sink_inputs_after)}")
    ok(f"Buffer block   : {buffer_block} instance {new_instance}")
    ok(f"Buffer input   : {old_net}")
    ok(f"Buffer output  : {buffer_net}")


if __name__ == "__main__":
    main()
