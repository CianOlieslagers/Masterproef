#!/usr/bin/env python3
"""
FASE 6A GENERIC — Maak ECO-manifest uit ABC/Phase5D candidate.

Doel:
  - Lees baseline DCP, Phase 3 window info en Phase 5D selected candidate.
  - Zet generieke ABC-nodes om naar concrete ECO-operaties:
      * SET_INIT
      * UPGRADE_LUT_CELL indien nodig
      * CONNECT_INPUT
      * CHANGE_OUTPUT_DRIVER indien nodig
  - Schrijf een generiek manifest.
  - Schrijf CSV's voor inspectie.
  - Genereer een Vivado feasibility check Tcl.

Belangrijk:
  - Dit script past de DCP nog NIET aan.
  - Dit is alleen manifest + check.
  - De bestaande Phase 6B is nog niet compatibel met dit generieke manifest.
"""

import csv
import json
import os
import re
import sys
from pathlib import Path


# -----------------------------
# Utilities
# -----------------------------

def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def ref_capacity(ref):
    m = re.fullmatch(r"LUT([1-6])", (ref or "").strip())
    if not m:
        return 0
    return int(m.group(1))


def ref_for_width(width):
    if width <= 1:
        return "LUT1"
    if width <= 2:
        return "LUT2"
    if width <= 3:
        return "LUT3"
    if width <= 4:
        return "LUT4"
    if width <= 5:
        return "LUT5"
    return "LUT6"


def parse_init_int(init_str):
    """
    Ondersteunt bv:
      64'h2B2B...
      4'h8
      0x123
      123
    """
    s = str(init_str).strip()

    m = re.fullmatch(r"([0-9]+)'h([0-9a-fA-F_]+)", s)
    if m:
        return int(m.group(2).replace("_", ""), 16)

    if s.lower().startswith("0x"):
        return int(s, 16)

    return int(s, 0)


def format_init(value, width_bits):
    hex_digits = max(1, width_bits // 4)
    return f"{width_bits}'h{value & ((1 << width_bits) - 1):0{hex_digits}X}"


def init_width_for_ref(ref):
    cap = ref_capacity(ref)
    if cap <= 0:
        return 64
    return 1 << cap


def effective_ref_and_init(node):
    """
    Beslis welke REF_NAME en INIT effectief gebruikt worden.

    Regel:
      - Als original_ref genoeg inputs ondersteunt: behoud original_ref.
      - Als original_ref te klein is: upgrade naar LUT6.
      - INIT wordt gecomprimeerd naar de effectieve ref-breedte.
    """
    original_ref = node.get("original_ref", "")
    input_count = int(node.get("input_count", 0))
    original_cap = ref_capacity(original_ref)

    init64 = parse_init_int(node.get("new_INIT", "0"))

    if original_cap >= input_count and original_cap > 0:
        effective_ref = original_ref
        requires_upgrade = False
    else:
        effective_ref = "LUT6"
        requires_upgrade = True

    width_bits = init_width_for_ref(effective_ref)
    effective_init = format_init(init64, width_bits)

    return effective_ref, effective_init, requires_upgrade


def boundary_by_index_map(phase3):
    return {
        int(b["boundary_index"]): b
        for b in phase3.get("boundary_inputs", [])
    }


def lut_by_cell_map(phase3):
    return {
        l["cell"]: l
        for l in phase3.get("luts", [])
    }


def output_net_by_cell_map(phase3):
    """
    Probeert output-net per LUT-cell te vinden.
    Niet alle Phase3-versies hebben exact dezelfde keys, dus dit is defensief.
    """
    out = {}

    for p in phase3.get("lut_output_pins", []):
        cell = p.get("cell") or p.get("source_cell") or p.get("sink_cell")
        net = p.get("net", "")
        pin = p.get("pin") or p.get("output_pin") or p.get("source_pin") or ""

        if cell and net:
            out[cell] = {
                "net": net,
                "pin": pin if pin else f"{cell}/O",
            }

    # Fallback via luts output_pin als net niet gekend is.
    for l in phase3.get("luts", []):
        cell = l.get("cell", "")
        if cell and cell not in out:
            out[cell] = {
                "net": "",
                "pin": l.get("output_pin", f"{cell}/O"),
            }

    return out


def old_output_info(phase3):
    outs = phase3.get("boundary_outputs", [])
    if not outs:
        return {
            "net": "",
            "driver_cell": "",
            "driver_pin": "",
            "outside_loads": "",
            "outside_ports": "",
        }

    o = outs[0]

    return {
        "net": o.get("net", ""),
        "driver_cell": o.get("source_cell", ""),
        "driver_pin": o.get("source_pin", ""),
        "outside_loads": o.get("outside_loads", ""),
        "outside_ports": o.get("outside_ports", ""),
    }


def topological_order_nodes(nodes):
    """
    Orden nodes zodat interne bronnen vóór verbruikers komen.
    Als er iets misgaat, behoud originele volgorde.
    """
    by_name = {n["abc_node"]: n for n in nodes}
    indeg = {n["abc_node"]: 0 for n in nodes}
    adj = {n["abc_node"]: [] for n in nodes}

    for n in nodes:
        dst = n["abc_node"]

        for inp in n.get("inputs", []):
            src = inp.get("source_signal", "")
            if src in by_name:
                adj[src].append(dst)
                indeg[dst] += 1

    q = [name for name, d in indeg.items() if d == 0]
    ordered = []

    while q:
        name = q.pop(0)
        ordered.append(by_name[name])

        for nxt in adj[name]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)

    if len(ordered) != len(nodes):
        return nodes

    return ordered


def make_source_desc(inp, boundary_by_index):
    if "boundary_index" in inp:
        bidx = int(inp["boundary_index"])
        b = boundary_by_index.get(bidx, {})
        return {
            "source_type": "BOUNDARY",
            "source_signal": inp.get("source_signal", f"b{bidx}"),
            "boundary_index": bidx,
            "source_net": b.get("net", ""),
            "source_cell": b.get("driver_cell", ""),
            "source_pin": b.get("driver_pin", ""),
            "source_desc": f"BI{bidx}:{b.get('net', '')}",
        }

    source_cell = inp.get("source_cell", "")

    return {
        "source_type": "INTERNAL",
        "source_signal": inp.get("source_signal", ""),
        "boundary_index": "",
        "source_net": "",
        "source_cell": source_cell,
        "source_pin": f"{source_cell}/O" if source_cell else "",
        "source_desc": f"{source_cell}/O" if source_cell else inp.get("source_signal", ""),
    }


def generate_feasibility_tcl(path, baseline_dcp, manifest_path, manifest, out_dir):
    """
    Genereert Tcl die checkt:
      - cellen bestaan
      - boundary nets bestaan
      - interne source cells bestaan
      - output net bestaat
      - vereiste pins bestaan of mogen ontbreken vóór geplande upgrade
    """
    result_csv = os.path.join(out_dir, "phase6a_generic_feasibility_result.csv")

    def tcl_quote(s):
        return str(s).replace("\\", "/").replace('"', '\\"')

    lines = []
    lines.append("# Auto-generated Phase 6A generic feasibility check")
    lines.append(f'set baseline_dcp "{tcl_quote(baseline_dcp)}"')
    lines.append(f'set result_csv "{tcl_quote(result_csv)}"')
    lines.append("")
    lines.append("open_checkpoint $baseline_dcp")
    lines.append("")
    lines.append('set fh [open $result_csv "w"]')
    lines.append('puts $fh "check,status,detail"')
    lines.append("")
    lines.append("proc emit_check {fh check status detail} {")
    lines.append('    regsub -all {,} $detail {;} detail2')
    lines.append('    puts $fh "$check,$status,$detail2"')
    lines.append("}")
    lines.append("")
    lines.append("set fail_count 0")
    lines.append("")
    lines.append("proc check_cell_exists {fh cname} {")
    lines.append("    set cs [get_cells -quiet $cname]")
    lines.append("    if {[llength $cs] == 1} {")
    lines.append('        emit_check $fh "cell_exists" "PASS" $cname')
    lines.append("        return 1")
    lines.append("    } else {")
    lines.append('        emit_check $fh "cell_exists" "FAIL" $cname')
    lines.append("        return 0")
    lines.append("    }")
    lines.append("}")
    lines.append("")
    lines.append("proc check_net_exists {fh nname label} {")
    lines.append("    if {$nname eq \"\"} {")
    lines.append('        emit_check $fh $label "WARN" "empty_net_name"')
    lines.append("        return 1")
    lines.append("    }")
    lines.append("    set ns [get_nets -quiet $nname]")
    lines.append("    if {[llength $ns] >= 1} {")
    lines.append('        emit_check $fh $label "PASS" $nname')
    lines.append("        return 1")
    lines.append("    } else {")
    lines.append('        emit_check $fh $label "FAIL" $nname')
    lines.append("        return 0")
    lines.append("    }")
    lines.append("}")
    lines.append("")
    lines.append("proc check_pin_exists_or_expected {fh pin planned_upgrade} {")
    lines.append("    set ps [get_pins -quiet $pin]")
    lines.append("    if {[llength $ps] == 1} {")
    lines.append('        emit_check $fh "pin_exists" "PASS" $pin')
    lines.append("        return 1")
    lines.append("    }")
    lines.append("    if {$planned_upgrade} {")
    lines.append('        emit_check $fh "pin_exists_after_upgrade" "PASS" $pin')
    lines.append("        return 1")
    lines.append("    }")
    lines.append('    emit_check $fh "pin_exists" "FAIL" $pin')
    lines.append("    return 0")
    lines.append("}")
    lines.append("")

    # Cell checks and pin checks.
    for node in manifest["nodes"]:
        cell = node["physical_cell"]
        requires_upgrade = 1 if node["requires_upgrade"] else 0

        lines.append(f'if {{![check_cell_exists $fh "{tcl_quote(cell)}"]}} {{ incr fail_count }}')

        for inp in node["inputs"]:
            pin = f'{cell}/{inp["sink_pin"]}'
            lines.append(
                f'if {{![check_pin_exists_or_expected $fh "{tcl_quote(pin)}" {requires_upgrade}]}} '
                f'{{ incr fail_count }}'
            )

    # Boundary nets and internal source cells.
    for rw in manifest["input_rewires"]:
        if rw["source_type"] == "BOUNDARY":
            net = rw.get("source_net", "")
            lines.append(
                f'if {{![check_net_exists $fh "{tcl_quote(net)}" "boundary_net_exists"]}} '
                f'{{ incr fail_count }}'
            )
        elif rw["source_type"] == "INTERNAL":
            scell = rw.get("source_cell", "")
            lines.append(
                f'if {{![check_cell_exists $fh "{tcl_quote(scell)}"]}} '
                f'{{ incr fail_count }}'
            )

    # Output net check.
    old_net = manifest.get("old_output", {}).get("net", "")
    lines.append(
        f'if {{![check_net_exists $fh "{tcl_quote(old_net)}" "output_net_exists"]}} '
        f'{{ incr fail_count }}'
    )

    # Output driver cell check.
    new_driver = manifest.get("new_output", {}).get("driver_cell", "")
    lines.append(
        f'if {{![check_cell_exists $fh "{tcl_quote(new_driver)}"]}} '
        f'{{ incr fail_count }}'
    )

    lines.append("")
    lines.append('emit_check $fh "manifest_path" "INFO" "' + tcl_quote(manifest_path) + '"')
    lines.append('emit_check $fh "fail_count" [expr {$fail_count == 0 ? "PASS" : "FAIL"}] $fail_count')
    lines.append("close $fh")
    lines.append("")
    lines.append("if {$fail_count == 0} {")
    lines.append('    puts "PHASE6A_GENERIC_FEASIBILITY_PASS"')
    lines.append("} else {")
    lines.append('    puts "PHASE6A_GENERIC_FEASIBILITY_FAIL fail_count=$fail_count"')
    lines.append("    exit 2")
    lines.append("}")

    Path(path).write_text("\n".join(lines) + "\n")


# -----------------------------
# Main
# -----------------------------

def main():
    if len(sys.argv) < 5:
        fail(
            "usage: python3 phase6a_prepare_eco_manifest_generic.py "
            "<baseline_dcp> <phase3_window_info.json> <phase5d_selected_candidate.json> <out_dir>"
        )

    baseline_dcp = os.path.abspath(sys.argv[1])
    phase3_path = os.path.abspath(sys.argv[2])
    candidate_path = os.path.abspath(sys.argv[3])
    out_dir = os.path.abspath(sys.argv[4])

    ensure_dir(out_dir)

    if not os.path.exists(baseline_dcp):
        fail(f"baseline DCP not found: {baseline_dcp}")

    phase3 = load_json(phase3_path)
    candidate = load_json(candidate_path)

    if not candidate:
        fail("candidate JSON is null/empty")

    if not candidate.get("truth_table_equivalence", False):
        fail("candidate does not claim truth_table_equivalence=true")

    nodes_in = candidate.get("nodes", [])
    if not nodes_in:
        fail("candidate has no nodes[]")

    nodes_in = topological_order_nodes(nodes_in)

    boundary_by_index = boundary_by_index_map(phase3)
    luts_by_cell = lut_by_cell_map(phase3)
    output_net_by_cell = output_net_by_cell_map(phase3)

    operations = []
    input_rewires = []
    nodes_out = []
    affected_nets = set()

    old_out = old_output_info(phase3)

    new_output = {
        "driver_cell": candidate.get("output_driver", {}).get("physical_cell", ""),
        "driver_pin": candidate.get("output_driver", {}).get("physical_pin", ""),
        "abc_node": candidate.get("output_driver", {}).get("abc_node", ""),
    }

    if old_out.get("net"):
        affected_nets.add(old_out["net"])

    for node in nodes_in:
        abc_node = node["abc_node"]
        cell = node["physical_cell"]

        if cell not in luts_by_cell:
            fail(f"candidate physical cell not in Phase3 window: {cell}")

        effective_ref, effective_init, requires_upgrade = effective_ref_and_init(node)

        node_out = {
            "abc_node": abc_node,
            "physical_cell": cell,
            "original_ref": node.get("original_ref", ""),
            "effective_ref": effective_ref,
            "requires_upgrade": requires_upgrade,
            "site": node.get("site", ""),
            "bel": node.get("bel", ""),
            "input_count": int(node.get("input_count", 0)),
            "new_INIT_original": node.get("new_INIT", ""),
            "new_INIT_effective": effective_init,
            "output_pin": f"{cell}/O",
            "old_output_net": output_net_by_cell.get(cell, {}).get("net", ""),
            "inputs": [],
        }

        operations.append({
            "operation": "SET_INIT",
            "abc_node": abc_node,
            "cell": cell,
            "original_ref": node.get("original_ref", ""),
            "effective_ref": effective_ref,
            "details": effective_init,
            "risk": "LOW" if not requires_upgrade else "MEDIUM",
        })

        if requires_upgrade:
            operations.append({
                "operation": "UPGRADE_LUT_CELL",
                "abc_node": abc_node,
                "cell": cell,
                "original_ref": node.get("original_ref", ""),
                "effective_ref": effective_ref,
                "details": f'{cell}: {node.get("original_ref", "")} -> {effective_ref}',
                "risk": "HIGH",
            })

        for inp in node.get("inputs", []):
            src = make_source_desc(inp, boundary_by_index)

            if src["source_net"]:
                affected_nets.add(src["source_net"])

            if src["source_cell"]:
                old_net = output_net_by_cell.get(src["source_cell"], {}).get("net", "")
                if old_net:
                    affected_nets.add(old_net)

            rw = {
                "abc_node": abc_node,
                "sink_cell": cell,
                "sink_pin": inp["sink_pin"],
                "sink_full_pin": f'{cell}/{inp["sink_pin"]}',
                "source_type": src["source_type"],
                "source_signal": src["source_signal"],
                "boundary_index": src["boundary_index"],
                "source_desc": src["source_desc"],
                "source_net": src["source_net"],
                "source_cell": src["source_cell"],
                "source_pin": src["source_pin"],
            }

            input_rewires.append(rw)
            node_out["inputs"].append(rw)

            operations.append({
                "operation": "CONNECT_INPUT",
                "abc_node": abc_node,
                "cell": cell,
                "original_ref": node.get("original_ref", ""),
                "effective_ref": effective_ref,
                "details": f'{src["source_desc"]} -> {cell}/{inp["sink_pin"]}',
                "risk": "MEDIUM",
            })

        if node_out["old_output_net"]:
            affected_nets.add(node_out["old_output_net"])

        nodes_out.append(node_out)

    output_driver_changed = (
        old_out.get("driver_cell", "") != new_output.get("driver_cell", "")
    )

    operations.append({
        "operation": "CHANGE_OUTPUT_DRIVER",
        "abc_node": new_output.get("abc_node", ""),
        "cell": new_output.get("driver_cell", ""),
        "original_ref": "",
        "effective_ref": "",
        "details": (
            f'net {old_out.get("net", "")}: '
            f'old driver {old_out.get("driver_pin", "")}, '
            f'new driver {new_output.get("driver_pin", "")}'
        ),
        "risk": "HIGH" if output_driver_changed else "LOW",
    })

    manifest = {
        "phase": "FASE 6A GENERIC",
        "baseline_dcp": baseline_dcp,
        "phase3_json": phase3_path,
        "candidate_json": candidate_path,
        "candidate_id": candidate.get("candidate_id", ""),
        "candidate_family": candidate.get("family", ""),
        "candidate_status": candidate.get("phase5d_status", ""),
        "truth_table_equivalence": candidate.get("truth_table_equivalence", False),
        "num_checked_vectors": candidate.get("num_checked_vectors", ""),
        "abc_lut_count": candidate.get("abc_lut_count", ""),
        "window_lut_count": candidate.get("window_lut_count", ""),
        "baseline_score": candidate.get("baseline_score", ""),
        "score_without_penalties": candidate.get("score_without_penalties", ""),
        "score_with_penalties": candidate.get("score_with_penalties", ""),
        "estimated_improvement": candidate.get("estimated_improvement", False),
        "old_output": old_out,
        "new_output": new_output,
        "output_driver_changed": output_driver_changed,
        "nodes": nodes_out,
        "input_rewires": input_rewires,
        "operations": operations,
        "affected_nets": sorted(affected_nets),
        "cost": candidate.get("cost", {}),
        "changed_pins_from_candidate": candidate.get("changed_pins", []),
        "requires_any_lut_upgrade": any(n["requires_upgrade"] for n in nodes_out),
    }

    manifest_path = os.path.join(out_dir, "phase6a_generic_eco_manifest.json")
    operations_csv = os.path.join(out_dir, "phase6a_generic_operations.csv")
    rewires_csv = os.path.join(out_dir, "phase6a_generic_input_rewires.csv")
    nodes_csv = os.path.join(out_dir, "phase6a_generic_nodes.csv")
    summary_txt = os.path.join(out_dir, "phase6a_generic_summary.txt")
    feasibility_tcl = os.path.join(out_dir, "phase6a_generic_feasibility_check.tcl")

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    write_csv(
        operations_csv,
        ["operation", "abc_node", "cell", "original_ref", "effective_ref", "details", "risk"],
        operations,
    )

    write_csv(
        rewires_csv,
        [
            "abc_node",
            "sink_cell",
            "sink_pin",
            "sink_full_pin",
            "source_type",
            "source_signal",
            "boundary_index",
            "source_desc",
            "source_net",
            "source_cell",
            "source_pin",
        ],
        input_rewires,
    )

    node_rows = []
    for n in nodes_out:
        node_rows.append({
            "abc_node": n["abc_node"],
            "physical_cell": n["physical_cell"],
            "original_ref": n["original_ref"],
            "effective_ref": n["effective_ref"],
            "requires_upgrade": int(n["requires_upgrade"]),
            "site": n["site"],
            "bel": n["bel"],
            "input_count": n["input_count"],
            "new_INIT_original": n["new_INIT_original"],
            "new_INIT_effective": n["new_INIT_effective"],
            "old_output_net": n["old_output_net"],
        })

    write_csv(
        nodes_csv,
        [
            "abc_node",
            "physical_cell",
            "original_ref",
            "effective_ref",
            "requires_upgrade",
            "site",
            "bel",
            "input_count",
            "new_INIT_original",
            "new_INIT_effective",
            "old_output_net",
        ],
        node_rows,
    )

    generate_feasibility_tcl(
        path=feasibility_tcl,
        baseline_dcp=baseline_dcp,
        manifest_path=manifest_path,
        manifest=manifest,
        out_dir=out_dir,
    )

    with open(summary_txt, "w") as f:
        f.write("phase6a_generic_status=PASS\n")
        f.write(f"candidate_id={manifest['candidate_id']}\n")
        f.write(f"candidate_status={manifest['candidate_status']}\n")
        f.write(f"truth_table_equivalence={int(bool(manifest['truth_table_equivalence']))}\n")
        f.write(f"abc_lut_count={manifest['abc_lut_count']}\n")
        f.write(f"window_lut_count={manifest['window_lut_count']}\n")
        f.write(f"baseline_score={manifest['baseline_score']}\n")
        f.write(f"score_with_penalties={manifest['score_with_penalties']}\n")
        f.write(f"estimated_improvement={int(bool(manifest['estimated_improvement']))}\n")
        f.write(f"num_nodes={len(nodes_out)}\n")
        f.write(f"num_input_rewires={len(input_rewires)}\n")
        f.write(f"num_operations={len(operations)}\n")
        f.write(f"requires_any_lut_upgrade={int(manifest['requires_any_lut_upgrade'])}\n")
        f.write(f"output_driver_changed={int(output_driver_changed)}\n")
        f.write(f"old_output_driver={old_out.get('driver_pin', '')}\n")
        f.write(f"new_output_driver={new_output.get('driver_pin', '')}\n")
        f.write(f"manifest={manifest_path}\n")
        f.write(f"operations_csv={operations_csv}\n")
        f.write(f"rewires_csv={rewires_csv}\n")
        f.write(f"nodes_csv={nodes_csv}\n")
        f.write(f"feasibility_tcl={feasibility_tcl}\n")

    print("PHASE6A_GENERIC_PASS")
    print(f"Manifest        : {manifest_path}")
    print(f"Operations CSV  : {operations_csv}")
    print(f"Input rewires   : {rewires_csv}")
    print(f"Nodes CSV       : {nodes_csv}")
    print(f"Feasibility Tcl : {feasibility_tcl}")


if __name__ == "__main__":
    main()
