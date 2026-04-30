#!/usr/bin/env python3
"""
FASE 6A — ECO feasibility diagnose en manifestgeneratie.

Input:
  1. baseline DCP
  2. phase3_window_info.json
  3. phase5b2_fast_selected_candidate.json
  4. output directory

Output:
  - phase6a_eco_manifest.json
  - phase6a_summary.txt
  - phase6a_operations.csv
  - phase6a_vivado_feasibility_check.tcl

Dit script past de DCP nog NIET aan.
Het genereert alleen een expliciet manifest en een Vivado Tcl checkscript.
"""

import csv
import json
import os
import sys


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def tcl_quote(s):
    s = str(s)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def main():
    if len(sys.argv) != 5:
        fail(
            "usage: python3 phase6a_prepare_eco_manifest.py "
            "<baseline_dcp> <phase3_window_info.json> "
            "<phase5_selected_candidate.json> <out_dir>"
        )

    baseline_dcp = os.path.abspath(sys.argv[1])
    phase3_json = os.path.abspath(sys.argv[2])
    candidate_json = os.path.abspath(sys.argv[3])
    out_dir = os.path.abspath(sys.argv[4])

    ensure_dir(out_dir)

    if not os.path.exists(baseline_dcp):
        fail(f"baseline DCP bestaat niet: {baseline_dcp}")
    if not os.path.exists(phase3_json):
        fail(f"phase3 JSON bestaat niet: {phase3_json}")
    if not os.path.exists(candidate_json):
        fail(f"candidate JSON bestaat niet: {candidate_json}")

    with open(phase3_json, "r") as f:
        phase3 = json.load(f)

    with open(candidate_json, "r") as f:
        cand = json.load(f)

    if not cand:
        fail("candidate JSON is leeg/null")

    boundary_by_index = {
        int(b["boundary_index"]): b
        for b in phase3["boundary_inputs"]
    }

    luts_by_cell = {
        l["cell"]: l
        for l in phase3["luts"]
    }

    boundary_outputs = phase3["boundary_outputs"]
    if len(boundary_outputs) != 1:
        fail(f"verwacht exact 1 boundary output, gevonden: {len(boundary_outputs)}")

    old_output = boundary_outputs[0]
    old_output_net = old_output["net"]
    old_output_driver_cell = old_output["source_cell"]
    old_output_driver_pin = old_output["source_pin"]
    outside_loads = old_output.get("outside_loads", "")

    roles = cand["roles"]
    root = roles["root"]
    helper1 = roles["helper1"]
    helper2 = roles["helper2"]

    new_output_driver_cell = root["cell"]
    new_output_driver_pin = f"{new_output_driver_cell}/O"

    operations = []

    # INIT updates.
    for role_name, role in roles.items():
        cell = role["cell"]
        original_ref = role["original_ref"]
        logical_ref = role["logical_ref"]
        new_init = role["new_INIT"]

        operations.append({
            "operation": "SET_INIT",
            "role": role_name,
            "cell": cell,
            "original_ref": original_ref,
            "logical_ref": logical_ref,
            "details": new_init,
            "risk": "LOW" if original_ref == logical_ref else "HIGH",
        })

        if original_ref != logical_ref:
            operations.append({
                "operation": "UPGRADE_LUT_CELL",
                "role": role_name,
                "cell": cell,
                "original_ref": original_ref,
                "logical_ref": logical_ref,
                "details": f"{cell}: {original_ref} -> {logical_ref}",
                "risk": "HIGH",
            })

    # Input rewires from candidate roles.
    input_rewires = []

    for role_name, role in roles.items():
        sink_cell = role["cell"]

        for inp in role["inputs"]:
            sink_pin = inp["sink_pin"]

            if "boundary_index" in inp:
                bidx = int(inp["boundary_index"])
                b = boundary_by_index[bidx]
                source_type = "BOUNDARY"
                source_net = b["net"]
                source_cell = b.get("driver_cell", "")
                source_pin = b.get("driver_pin", "")
                source_desc = f"BI{bidx}:{source_net}"
            else:
                source_type = "INTERNAL"
                source_cell = inp["source_cell"]
                source_pin = f"{source_cell}/O"
                source_net = ""
                source_desc = source_pin

            input_rewires.append({
                "sink_role": role_name,
                "sink_cell": sink_cell,
                "sink_pin": sink_pin,
                "sink_full_pin": f"{sink_cell}/{sink_pin}",
                "source_type": source_type,
                "source_desc": source_desc,
                "source_net": source_net,
                "source_cell": source_cell,
                "source_pin": source_pin,
            })

            operations.append({
                "operation": "CONNECT_INPUT",
                "role": role_name,
                "cell": sink_cell,
                "original_ref": role["original_ref"],
                "logical_ref": role["logical_ref"],
                "details": f"{source_desc} -> {sink_cell}/{sink_pin}",
                "risk": "MEDIUM" if source_type == "BOUNDARY" else "HIGH",
            })

    # Output driver change.
    output_driver_changed = cand.get("output_driver_changed", False)

    if output_driver_changed:
        operations.append({
            "operation": "CHANGE_OUTPUT_DRIVER",
            "role": "root",
            "cell": new_output_driver_cell,
            "original_ref": root["original_ref"],
            "logical_ref": root["logical_ref"],
            "details": (
                f"net {old_output_net}: old driver {old_output_driver_pin}, "
                f"new driver {new_output_driver_pin}, loads {outside_loads}"
            ),
            "risk": "HIGH",
        })

    # Affected nets.
    affected_nets = set()
    affected_nets.add(old_output_net)

    for r in input_rewires:
        if r["source_net"]:
            affected_nets.add(r["source_net"])

    for e in phase3.get("internal_edges", []):
        affected_nets.add(e["net"])

    # Existing old pins from phase3.
    old_input_pin_sources = {
        f"{p['sink_cell']}/{p['sink_ref_pin']}": p
        for p in phase3["lut_input_pins"]
    }

    manifest = {
        "phase": "FASE 6A",
        "baseline_dcp": baseline_dcp,
        "phase3_json": phase3_json,
        "candidate_json": candidate_json,
        "candidate_id": cand["candidate_id"],
        "candidate_status": cand.get("phase5b2_fast_status", ""),
        "truth_table_equivalence": cand.get("truth_table_equivalence", False),
        "num_checked_vectors": cand.get("num_checked_vectors", 0),
        "estimated_improvement": cand.get("estimated_improvement", False),
        "old_output": {
            "net": old_output_net,
            "driver_cell": old_output_driver_cell,
            "driver_pin": old_output_driver_pin,
            "outside_loads": outside_loads,
        },
        "new_output": {
            "driver_cell": new_output_driver_cell,
            "driver_pin": new_output_driver_pin,
        },
        "roles": roles,
        "input_rewires": input_rewires,
        "operations": operations,
        "affected_nets": sorted(affected_nets),
        "old_input_pin_sources": old_input_pin_sources,
        "requires_lut_upgrade": any(
            role["original_ref"] != role["logical_ref"]
            for role in roles.values()
        ),
        "requires_output_driver_change": output_driver_changed,
    }

    manifest_path = os.path.join(out_dir, "phase6a_eco_manifest.json")
    summary_path = os.path.join(out_dir, "phase6a_summary.txt")
    ops_csv_path = os.path.join(out_dir, "phase6a_operations.csv")
    rewires_csv_path = os.path.join(out_dir, "phase6a_input_rewires.csv")
    tcl_path = os.path.join(out_dir, "phase6a_vivado_feasibility_check.tcl")

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    write_csv(
        ops_csv_path,
        ["operation", "role", "cell", "original_ref", "logical_ref", "details", "risk"],
        operations,
    )

    write_csv(
        rewires_csv_path,
        [
            "sink_role",
            "sink_cell",
            "sink_pin",
            "sink_full_pin",
            "source_type",
            "source_desc",
            "source_net",
            "source_cell",
            "source_pin",
        ],
        input_rewires,
    )

    with open(summary_path, "w") as f:
        f.write("phase6a_status=MANIFEST_CREATED\n")
        f.write(f"candidate_id={cand['candidate_id']}\n")
        f.write(f"truth_table_equivalence={cand.get('truth_table_equivalence')}\n")
        f.write(f"num_checked_vectors={cand.get('num_checked_vectors')}\n")
        f.write(f"estimated_improvement={cand.get('estimated_improvement')}\n")
        f.write(f"requires_lut_upgrade={manifest['requires_lut_upgrade']}\n")
        f.write(f"requires_output_driver_change={manifest['requires_output_driver_change']}\n")
        f.write(f"old_output_net={old_output_net}\n")
        f.write(f"old_output_driver={old_output_driver_pin}\n")
        f.write(f"new_output_driver={new_output_driver_pin}\n")
        f.write(f"num_operations={len(operations)}\n")
        f.write(f"num_input_rewires={len(input_rewires)}\n")
        f.write(f"num_affected_nets={len(affected_nets)}\n")
        f.write(f"manifest={manifest_path}\n")
        f.write(f"vivado_check_tcl={tcl_path}\n")

    # Generate Vivado Tcl feasibility check.
    with open(tcl_path, "w") as f:
        f.write("# Auto-generated by phase6a_prepare_eco_manifest.py\n")
        f.write("# This script checks feasibility only. It does NOT modify the DCP.\n\n")
        f.write(f"set baseline_dcp {tcl_quote(baseline_dcp)}\n")
        f.write(f"set out_dir {tcl_quote(out_dir)}\n")
        f.write("file mkdir $out_dir\n")
        f.write("set report_file [file join $out_dir phase6a_vivado_feasibility_report.txt]\n")
        f.write("set csv_file [file join $out_dir phase6a_vivado_feasibility_checks.csv]\n")
        f.write("set rf [open $report_file w]\n")
        f.write("set cf [open $csv_file w]\n")
        f.write('puts $cf "check,status,detail"\n\n')

        f.write("""
proc csv_escape {s} {
    set s [string trim $s]
    if {[regexp {[,\"\\n\\r]} $s]} {
        set s [string map [list "\"" "\"\""] $s]
        return "\"$s\""
    }
    return $s
}

proc check_write {cf name status detail} {
    puts $cf "[csv_escape $name],[csv_escape $status],[csv_escape $detail]"
}

proc obj_name {obj} {
    if {[catch {set n [get_property NAME $obj]}]} {
        return [string trim $obj]
    }
    if {$n eq ""} {
        return [string trim $obj]
    }
    return $n
}

proc safe_prop {obj prop} {
    if {[catch {set v [get_property $prop $obj]}]} {
        return ""
    }
    return $v
}
""")

        f.write("\nopen_checkpoint $baseline_dcp\n\n")
        f.write('puts $rf "Opened DCP: $baseline_dcp"\n')
        f.write('check_write $cf "open_checkpoint" "PASS" $baseline_dcp\n\n')

        # Cell checks.
        checked_cells = sorted({role["cell"] for role in roles.values()})
        for cell in checked_cells:
            f.write(f"\n# Check cell {cell}\n")
            f.write(f"set c [get_cells -quiet {tcl_quote(cell)}]\n")
            f.write("if {[llength $c] == 1} {\n")
            f.write(f"  check_write $cf {tcl_quote('cell_exists:' + cell)} PASS {tcl_quote(cell)}\n")
            f.write("  set ref [safe_prop [lindex $c 0] REF_NAME]\n")
            f.write("  set loc [safe_prop [lindex $c 0] LOC]\n")
            f.write("  set bel [safe_prop [lindex $c 0] BEL]\n")
            f.write(f"  check_write $cf {tcl_quote('cell_ref:' + cell)} PASS $ref\n")
            f.write(f"  check_write $cf {tcl_quote('cell_loc_bel:' + cell)} PASS \"$loc/$bel\"\n")
            f.write("} else {\n")
            f.write(f"  check_write $cf {tcl_quote('cell_exists:' + cell)} FAIL {tcl_quote(cell)}\n")
            f.write("}\n")

        # Existing pin checks.
        for role_name, role in roles.items():
            cell = role["cell"]
            original_ref = role["original_ref"]
            logical_ref = role["logical_ref"]

            for inp in role["inputs"]:
                sink_pin = inp["sink_pin"]
                full_pin = f"{cell}/{sink_pin}"

                f.write(f"\n# Check target pin {full_pin}\n")
                f.write(f"set p [get_pins -quiet {tcl_quote(full_pin)}]\n")
                f.write("if {[llength $p] == 1} {\n")
                f.write(f"  check_write $cf {tcl_quote('target_pin_exists:' + full_pin)} PASS {tcl_quote(full_pin)}\n")
                f.write("} else {\n")
                if original_ref != logical_ref and sink_pin in ["I2", "I3", "I4", "I5"]:
                    f.write(
                        f"  check_write $cf {tcl_quote('target_pin_missing_expected_after_upgrade:' + full_pin)} "
                        f"WARN {tcl_quote('pin absent now; expected after ' + original_ref + ' -> ' + logical_ref + ' upgrade')}\n"
                    )
                else:
                    f.write(f"  check_write $cf {tcl_quote('target_pin_exists:' + full_pin)} FAIL {tcl_quote(full_pin)}\n")
                f.write("}\n")

        # Boundary nets.
        boundary_nets = sorted({r["source_net"] for r in input_rewires if r["source_net"]})
        for net in boundary_nets:
            f.write(f"\n# Check boundary net {net}\n")
            f.write(f"set n [get_nets -quiet {tcl_quote(net)}]\n")
            f.write("if {[llength $n] == 1} {\n")
            f.write(f"  check_write $cf {tcl_quote('boundary_net_exists:' + net)} PASS {tcl_quote(net)}\n")
            f.write("  set drivers [get_pins -quiet -of_objects $n -filter {DIRECTION == OUT}]\n")
            f.write(f"  check_write $cf {tcl_quote('boundary_net_driver_count:' + net)} PASS \"drivers=[llength $drivers]\"\n")
            f.write("} else {\n")
            f.write(f"  check_write $cf {tcl_quote('boundary_net_exists:' + net)} FAIL {tcl_quote(net)}\n")
            f.write("}\n")

        # Output net check.
        f.write("\n# Output net driver check\n")
        f.write(f"set output_net [get_nets -quiet {tcl_quote(old_output_net)}]\n")
        f.write("if {[llength $output_net] == 1} {\n")
        f.write(f"  check_write $cf {tcl_quote('output_net_exists:' + old_output_net)} PASS {tcl_quote(old_output_net)}\n")
        f.write("  set drivers [get_pins -quiet -of_objects $output_net -filter {DIRECTION == OUT}]\n")
        f.write("  set driver_names {}\n")
        f.write("  foreach d $drivers { lappend driver_names [obj_name $d] }\n")
        f.write(f"  set expected_old_driver {tcl_quote(old_output_driver_pin)}\n")
        f.write("  if {[lsearch -exact $driver_names $expected_old_driver] >= 0} {\n")
        f.write("    check_write $cf \"old_output_driver_matches\" PASS $expected_old_driver\n")
        f.write("  } else {\n")
        f.write("    check_write $cf \"old_output_driver_matches\" FAIL \"actual=$driver_names expected=$expected_old_driver\"\n")
        f.write("  }\n")
        f.write("  set loads [get_pins -quiet -of_objects $output_net -filter {DIRECTION == IN}]\n")
        f.write("  check_write $cf \"output_net_load_count\" PASS \"loads=[llength $loads]\"\n")
        f.write("} else {\n")
        f.write(f"  check_write $cf {tcl_quote('output_net_exists:' + old_output_net)} FAIL {tcl_quote(old_output_net)}\n")
        f.write("}\n")

        # New output driver pin existence.
        f.write("\n# New output driver pin check\n")
        f.write(f"set new_driver_pin [get_pins -quiet {tcl_quote(new_output_driver_pin)}]\n")
        f.write("if {[llength $new_driver_pin] == 1} {\n")
        f.write(f"  check_write $cf {tcl_quote('new_output_driver_pin_exists:' + new_output_driver_pin)} PASS {tcl_quote(new_output_driver_pin)}\n")
        f.write("} else {\n")
        f.write(f"  check_write $cf {tcl_quote('new_output_driver_pin_exists:' + new_output_driver_pin)} FAIL {tcl_quote(new_output_driver_pin)}\n")
        f.write("}\n")

        # Affected nets.
        f.write("\n# Affected nets\n")
        for net in sorted(affected_nets):
            f.write(f"set n [get_nets -quiet {tcl_quote(net)}]\n")
            f.write("if {[llength $n] == 1} {\n")
            f.write(f"  check_write $cf {tcl_quote('affected_net_exists:' + net)} PASS {tcl_quote(net)}\n")
            f.write("} else {\n")
            f.write(f"  check_write $cf {tcl_quote('affected_net_exists:' + net)} WARN {tcl_quote(net)}\n")
            f.write("}\n")

        f.write("\nclose $rf\n")
        f.write("close $cf\n")
        f.write('puts "PHASE6A_VIVADO_CHECK_DONE"\n')
        f.write('puts "Report: $report_file"\n')
        f.write('puts "CSV   : $csv_file"\n')

    print("PHASE6A_MANIFEST_CREATED")
    print(f"Summary : {summary_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Tcl     : {tcl_path}")


if __name__ == "__main__":
    main()
