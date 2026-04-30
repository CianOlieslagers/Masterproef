#!/usr/bin/env python3
from __future__ import annotations
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import argparse


# ----------------------------
# Helpers
# ----------------------------
def load_json(p: str) -> Any:
    return json.loads(Path(p).read_text())


def safe_int_list_from_text(txt: Optional[str]) -> List[int]:
    """
    Parse whitespace-separated ints but ignore non-integers (e.g., 'open').
    """
    if not txt:
        return []
    out: List[int] = []
    for tok in txt.strip().split():
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return out


# ----------------------------
# BLIF parsing
# ----------------------------
def parse_blif_lut_input_order(blif_path: str) -> Dict[str, List[str]]:
    """
    Parse mapped BLIF and return: LUT_OUTPUT -> [inputs...] in the exact .names order.

    Example:
      .names pi6 LUT_76 LUT_97 LUT_116 LUT_120
    gives:
      LUT_120 -> ["pi6", "LUT_76", "LUT_97", "LUT_116"]
    """
    lut_inputs: Dict[str, List[str]] = {}

    names_re = re.compile(r"^\s*\.names\s+(.*)\s*$")
    with open(blif_path, "r") as f:
        for line in f:
            m = names_re.match(line)
            if not m:
                continue
            toks = m.group(1).split()
            if len(toks) < 2:
                continue
            out_net = toks[-1]
            in_nets = toks[:-1]

            if re.fullmatch(r"LUT_\d+", out_net):
                lut_inputs[out_net] = in_nets

    return lut_inputs


def parse_blif_inputs(blif_path: str) -> List[str]:
    """
    Parse BLIF file and return ordered primary input names as they appear in '.inputs'.
    Supports multi-line '.inputs ... \\' continuation.
    """
    lines = Path(blif_path).read_text().splitlines()
    inputs: List[str] = []
    collecting = False

    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue

        if s.startswith(".inputs"):
            collecting = True
            s = s[len(".inputs"):].strip()

        if collecting:
            if s.endswith("\\"):
                s = s[:-1].strip()
                inputs.extend(s.split())
                continue
            else:
                inputs.extend(s.split())
                collecting = False

    return [x.strip() for x in inputs if x.strip()]


def build_pi_name_maps_from_blif_and_aag(
    blif_inputs: List[str],
    aag_pi_literals: List[int],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Given ordered BLIF PI names and ordered AAG PI literals, build:
      - pi_name_to_node: name -> node_id (lit//2)
      - pi_name_to_lit : name -> literal
    Assumes both lists correspond positionally.
    """
    if len(blif_inputs) != len(aag_pi_literals):
        raise ValueError(
            f"PI count mismatch: BLIF has {len(blif_inputs)} inputs, AAG has {len(aag_pi_literals)} PIs"
        )

    pi_name_to_node: Dict[str, int] = {}
    pi_name_to_lit: Dict[str, int] = {}

    for name, lit in zip(blif_inputs, aag_pi_literals):
        if lit <= 0:
            raise ValueError(f"Unexpected PI literal {lit} for PI '{name}'")
        node_id = lit // 2
        pi_name_to_node[name] = node_id
        pi_name_to_lit[name] = lit

    return pi_name_to_node, pi_name_to_lit


# ----------------------------
# Parse mapped.net (XML)
# ----------------------------
def parse_mapped_net(net_path: str, mapped_blif_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Parse VPR mapped.net (XML) to extract per LUT:
      - clb input nets (port name="I")
      - port_rotation_map for LUT input pins (port_rotation_map name="in")
      - LUT output net name (inner block lut[0] outputs/port name="out")

    IMPORTANT:
      Prefer pin order from mapped BLIF (.names ... LUT_X) if provided.
      If not available, fall back to rotation_map + clb_inputs.

    Returns: lut_name -> {
        "clb_inputs": [...],
        "rotation_map": [...],
        "lut_inputs_ordered": [...],
        "output_net": "...",
    }
    """
    blif_order: Dict[str, List[str]] = {}
    if mapped_blif_path:
        blif_order = parse_blif_lut_input_order(mapped_blif_path)

    tree = ET.parse(net_path)
    root = tree.getroot()

    lut_map: Dict[str, Any] = {}

    # We want LUT blocks at CLB level (instance starts with "clb[")
    for blk in root.findall(".//block"):
        name = blk.attrib.get("name", "")
        inst = blk.attrib.get("instance", "")

        if not name.startswith("LUT_"):
            continue
        if not inst.startswith("clb["):
            continue

        # CLB input port I
        clb_inputs: List[str] = []
        inputs_node = blk.find("./inputs")
        if inputs_node is not None:
            for port in inputs_node.findall("./port"):
                if port.attrib.get("name") == "I":
                    txt = (port.text or "").strip()
                    clb_inputs = [t for t in txt.split() if t]
                    break

        # rotation map (logical pin -> index in clb_inputs)
        prm = blk.find(".//port_rotation_map[@name='in']")
        rotation_map = safe_int_list_from_text(prm.text if prm is not None else None)

        # LUT output net (inside inner block lut[0])
        out_port = blk.find(".//block[@instance='lut[0]']/outputs/port[@name='out']")
        output_net = (out_port.text or "").strip() if out_port is not None else ""

        # Input order
        if name in blif_order:
            lut_inputs_ordered = blif_order[name][:]
        else:
            if rotation_map and len(clb_inputs) >= len(rotation_map):
                lut_inputs_ordered = [clb_inputs[idx] for idx in rotation_map]
            else:
                lut_inputs_ordered = clb_inputs[:]

        lut_map[name] = {
            "clb_inputs": clb_inputs,
            "rotation_map": rotation_map,
            "lut_inputs_ordered": lut_inputs_ordered,
            "output_net": output_net,
        }

    return lut_map


# ----------------------------
# Parse AIGER ASCII (.aag)
# ----------------------------
def parse_aag(aag_path: str, keep_nodes: Optional[Set[int]] = None) -> Dict[str, Any]:
    """
    Minimal ASCII AIGER parser for AND nodes and PI/PO literals.
    Stores AND fanins as literals (may be complemented).
    Node id = lit//2.

    If keep_nodes provided: only store AND rows whose output node id is in keep_nodes.
    """
    lines = Path(aag_path).read_text().splitlines()
    if not lines or not lines[0].startswith("aag "):
        raise ValueError(f"Not an .aag file: {aag_path}")

    header = lines[0].split()
    if len(header) < 6:
        raise ValueError(f"Bad .aag header: {lines[0]}")

    M = int(header[1])
    I = int(header[2])
    L = int(header[3])
    O = int(header[4])
    A = int(header[5])

    idx = 1

    pis: List[int] = []
    for _ in range(I):
        pis.append(int(lines[idx].strip()))
        idx += 1

    # latches
    for _ in range(L):
        idx += 1

    pos: List[int] = []
    for _ in range(O):
        pos.append(int(lines[idx].strip()))
        idx += 1

    ands: Dict[int, Tuple[int, int]] = {}
    for _ in range(A):
        row = lines[idx].strip()
        idx += 1
        if not row:
            continue
        parts = row.split()
        if len(parts) != 3:
            continue
        lhs_lit = int(parts[0])
        rhs0 = int(parts[1])
        rhs1 = int(parts[2])
        out_node = lhs_lit // 2
        if keep_nodes is not None and out_node not in keep_nodes:
            continue
        ands[out_node] = (rhs0, rhs1)

    return {
        "format": "aag:v1",
        "source": str(aag_path),
        "M": M,
        "I": I,
        "L": L,
        "O": O,
        "A": A,
        "pis": pis,
        "pos": pos,
        "and": {str(k): [v[0], v[1]] for k, v in ands.items()},
    }



def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build SUPER json (SAT v2) from mapped net, lut cones, lut connections, postopt aag, and mapped blif."
    )
    p.add_argument("--mapped-net", required=True, help="Path to <design>.mapped.net (from VPR)")
    p.add_argument("--lut-cones", required=True, help="Path to <design>.lut_cones.json (from mt_lut_cones)")
    p.add_argument("--conns", required=True, help="Path to <design>.lut_connections_full.json")
    p.add_argument("--postopt-aag", required=True, help="Path to postopt .aag (ASCII AIG)")
    p.add_argument("--mapped-blif", required=True, help="Path to <design>.mapped.blif (LUT-mapped BLIF)")
    p.add_argument("--out", required=True, help="Output path for <design>.super.sat.v2.json")
    return p.parse_args()


def must_exist(path: str) -> Path:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"[ERROR] File not found: {p}")
    if p.is_file() and p.stat().st_size == 0:
        raise SystemExit(f"[ERROR] File is empty: {p}")
    return p


# ----------------------------
# Super JSON builder
# ----------------------------
def build_super_json(
    mapped_net: str,
    lut_cones_json: str,
    connections_json: str,
    postopt_aag: str,
    mapped_blif: str,
) -> Dict[str, Any]:
    # 1) netlist mapping (prefer BLIF order)
    lut_io = parse_mapped_net(mapped_net, mapped_blif_path=mapped_blif)

    # 2) LUT cones + connections
    cones = load_json(lut_cones_json)
    conns = load_json(connections_json)

    # 3) index LUT cones by name + collect keep_nodes
    luts: Dict[str, Any] = {}
    keep_nodes: Set[int] = set()

    for entry in cones.get("lut_cones", []):
        lut_name = entry["lut_name"]
        luts[lut_name] = {
            "lut_root": entry["lut_root"],
            "K": cones.get("K"),
            "func_hex": entry.get("func_hex"),
            "leaves": entry.get("leaves", []),
            "internal_nodes": entry.get("internal_nodes", []),
            "node_functions": entry.get("node_functions", []),
        }

        keep_nodes.add(int(entry["lut_root"]))
        for n in entry.get("leaves", []):
            keep_nodes.add(int(n))
        for n in entry.get("internal_nodes", []):
            keep_nodes.add(int(n))

        if lut_name in lut_io:
            luts[lut_name]["netlist"] = lut_io[lut_name]

    # 4) AAG parse
    aig_graph = parse_aag(postopt_aag, keep_nodes=None)  # keep_nodes optional; keep full for debugging

    # 5) PI mapping via BLIF .inputs
    blif_inputs = parse_blif_inputs(mapped_blif)
    pi_name_to_node, pi_name_to_lit = build_pi_name_maps_from_blif_and_aag(blif_inputs, aig_graph["pis"])

    aig_graph["blif_inputs"] = blif_inputs
    aig_graph["pi_name_to_node"] = {k: int(v) for k, v in pi_name_to_node.items()}
    aig_graph["pi_name_to_lit"] = {k: int(v) for k, v in pi_name_to_lit.items()}

    # 6) merge connections + enforce dst pin from src->dst arc
    merged_connections = []
    for c in conns.get("connections", []):
        src_name = c["src"]["lut_name"]
        dst_name = c["dst"]["lut_name"]

        dst_lut = luts.get(dst_name)
        dst_inputs_ordered: List[str] = []
        if dst_lut and "netlist" in dst_lut:
            dst_inputs_ordered = dst_lut["netlist"].get("lut_inputs_ordered", []) or []

        src_lut = luts.get(src_name)
        src_out = ""
        if src_lut and "netlist" in src_lut:
            src_out = src_lut["netlist"].get("output_net", "") or ""

        dst_pin_from_src = None
        dst_net_from_src = None
        if src_out and dst_inputs_ordered and (src_out in dst_inputs_ordered):
            dst_pin_from_src = dst_inputs_ordered.index(src_out)
            dst_net_from_src = dst_inputs_ordered[dst_pin_from_src]

        pits = []
        for p in c.get("pitstops", []):
            pit_name = p.get("lut_name")
            pit_lut = luts.get(pit_name) if pit_name else None

            pit_out = ""
            if pit_lut and "netlist" in pit_lut:
                pit_out = pit_lut["netlist"].get("output_net", "") or ""

            # enforce target pin = the src->dst pin (scenario logic)
            dst_pin = dst_pin_from_src
            dst_net = dst_net_from_src
            link_mode = "forced_target_from_src_arc" if dst_pin is not None else "unresolved_no_src_arc"

            # fallback: if no src->dst arc found, but pit is a direct fanin
            if dst_pin is None and pit_out and dst_inputs_ordered and (pit_out in dst_inputs_ordered):
                dst_pin = dst_inputs_ordered.index(pit_out)
                dst_net = dst_inputs_ordered[dst_pin]
                link_mode = "direct_fanin_fallback"

            pits.append({
                "lut_name": pit_name,
                "coords": p.get("coords"),
                "distances": p.get("distances"),
                "costs": p.get("costs"),
                "aig": p.get("aig"),
                "expr_root": p.get("expr_root"),
                "lut": pit_lut,
                "net_link": {
                    "pit_output_net": pit_out,
                    "dst_input_pin": dst_pin,
                    "dst_input_net": dst_net,
                    "src_output_net": src_out,
                    "link_mode": link_mode,
                },
            })

        merged_connections.append({
            "src": {**c["src"], "lut": luts.get(src_name)},
            "dst": {**c["dst"], "lut": luts.get(dst_name)},
            "d_ab": c.get("d_ab"),
            "src_to_dst_link": {
                "src_output_net": src_out,
                "dst_input_pin": dst_pin_from_src,
                "dst_input_net": dst_net_from_src,
            },
            "pitstops": pits,
        })

    return {
        "design": conns.get("design", cones.get("circuit")),
        "K": cones.get("K"),
        "sources": {
            "mapped_net": str(mapped_net),
            "lut_cones": str(lut_cones_json),
            "lut_connections_full": str(connections_json),
            "postopt_aag": str(postopt_aag),
            "mapped_blif": str(mapped_blif),
        },
        "luts": luts,
        "aig_graph": aig_graph,
        "connections": merged_connections,
    }


if __name__ == "__main__":
    args = parse_args()

    mapped_net  = str(must_exist(args.mapped_net))
    lut_cones   = str(must_exist(args.lut_cones))
    conns       = str(must_exist(args.conns))
    postopt_aag = str(must_exist(args.postopt_aag))
    mapped_blif = str(must_exist(args.mapped_blif))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    superj = build_super_json(mapped_net, lut_cones, conns, postopt_aag, mapped_blif)
    out_path.write_text(json.dumps(superj, indent=2))

    print(f"[OK] Wrote {out_path}")
    # onderstaande stats zijn handig, maar laat ze alleen staan als superj deze keys altijd heeft:
    if isinstance(superj, dict):
        if "luts" in superj:
            print(f"     LUTs: {len(superj['luts'])}")
        if "connections" in superj:
            print(f"     Connections: {len(superj['connections'])}")
        if "aig_graph" in superj and isinstance(superj["aig_graph"], dict) and "and" in superj["aig_graph"]:
            print(f"     AIG AND nodes stored: {len(superj['aig_graph']['and'])}")
