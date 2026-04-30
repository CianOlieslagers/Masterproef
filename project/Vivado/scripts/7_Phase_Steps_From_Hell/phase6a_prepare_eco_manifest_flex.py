#!/usr/bin/env python3
"""
FASE 6A FLEX — ECO manifestgeneratie voor variabel aantal LUT roles.

Compatibel met:
  - oude phase5b2 candidates met root/helper1/helper2
  - nieuwe ABC-converted candidates met roles={root,node_...}

Output filenames blijven identiek aan de legacy flow:
  - phase6a_eco_manifest.json
  - phase6a_summary.txt
  - phase6a_operations.csv
  - phase6a_input_rewires.csv
  - phase6a_vivado_feasibility_check.tcl
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
            "usage: python3 phase6a_prepare_eco_manifest_flex.py "
            "<baseline_dcp> <phase3_window_info.json> "
            "<phase5_selected_candidate.json> <out_dir>"
        )

    baseline_dcp = os.path.abspath(sys.argv[1])
    phase3_json = os.path.abspath(sys.argv[2])
    candidate_json = os.path.abspath(sys.argv[3])
    out_dir = os.path.abspath(sys.argv[4])

    ensure_dir(out_dir)

    if not os.path.exists(baseline_dcp):
        fail(f"baseline DCP does not exist: {baseline_dcp}")
    if not os.path.exists(phase3_json):
        fail(f"phase3 JSON does not exist: {phase3_json}")
    if not os.path.exists(candidate_json):
        fail(f"candidate JSON does not exist: {candidate_json}")

    with open(phase3_json, "r") as f:
        phase3 = json.load(f)

    with open(candidate_json, "r") as f:
        cand = json.load(f)

    if not cand:
        fail("candidate JSON is empty/null")

    if "roles" not in cand:
        fail("candidate JSON has no roles field")

    roles = cand["roles"]

    boundary_by_index = {
        int(b["boundary_index"]): b
        for b in phase3["boundary_inputs"]
    }

    boundary_outputs = phase3["boundary_outputs"]
    if len(boundary_outputs) != 1:
        fail(f"expected exactly 1 boundary output, found: {len(boundary_outputs)}")

    old_output = boundary_outputs[0]
    old_output_net = old_output["net"]
    old_output_driver_cell = old_output["source_cell"]
    old_output_driver_pin = old_output["source_pin"]
    outside_loads = old_output.get("outside_loads", "")

    # New output driver:
    # - For ABC candidates: explicit cand["output_driver"]
    # - For old candidates: roles["root"]
    if "output_driver" in cand and cand["output_driver"]:
        new_output_driver_cell = cand["output_driver"]["physical_cell"]
        new_output_driver_pin = cand["output_driver"].get(
            "physical_pin",
            f"{new_output_driver_cell}/O",
        )
    else:
        if "root" not in roles:
            fail("candidate has no output_driver and no root role")
        new_output_driver_cell = roles["root"]["cell"]
        new_output_driver_pin = f"{new_output_driver_cell}/O"

    operations = []

    # INIT / upgrade operations.
    for role_name, role in roles.items():
        cell = role["cell"]
        original_ref = role["original_ref"]
        logical_ref = role.get("logical_ref", "LUT6")
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

    # Input rewires.
    input_rewires = []

    for role_name, role in roles.items():
        sink_cell = role["cell"]

        for inp in role.get("inputs", []):
            sink_pin = inp["sink_pin"]

            if "boundary_index" in inp:
                bidx = int(inp["boundary_index"])
                if bidx not in boundary_by_index:
                    fail(f"boundary_index {bidx} not found in phase3 boundary inputs")

                b = boundary_by_index[bidx]

                source_type = "BOUNDARY"
                source_net = b["net"]
                source_cell = b.get("driver_cell", "")
                source_pin = b.get("driver_pin", "")
                source_desc = f"BI{bidx}:{source_net}"

            elif "source_cell" in inp:
                source_type = "INTERNAL"
                source_cell = inp["source_cell"]
                source_pin = f"{source_cell}/O"
                source_net = ""
                source_desc = source_pin

            else:
                fail(f"unsupported role input: {inp}")

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
                "logical_ref": role.get("logical_ref", "LUT6"),
                "details": f"{source_desc} -> {sink_cell}/{sink_pin}",
                "risk": "MEDIUM" if source_type == "BOUNDARY" else "HIGH",
            })

    output_driver_changed = new_output_driver_pin != old_output_driver_pin

    if output_driver_changed:
        operations.append({
            "operation": "CHANGE_OUTPUT_DRIVER",
            "role": "output_driver",
            "cell": new_output_driver_cell,
            "original_ref": roles.get("root", {}).get("original_ref", ""),
            "logical_ref": roles.get("root", {}).get("logical_ref", "LUT6"),
            "details": (
                f"net {old_output_net}: old driver {old_output_driver_pin}, "
                f"new driver {new_output_driver_pin}, loads {outside_loads}"
            ),
            "risk": "HIGH",
        })
    else:
        operations.append({
            "operation": "KEEP_OUTPUT_DRIVER",
            "role": "output_driver",
            "cell": new_output_driver_cell,
            "original_ref": "",
            "logical_ref": "",
            "details": f"net {old_output_net}: output driver remains {new_output_driver_pin}",
            "risk": "LOW",
        })

    affected_nets = set()
    affected_nets.add(old_output_net)

    for r in input_rewires:
        if r["source_net"]:
            affected_nets.add(r["source_net"])

    for e in phase3.get("internal_edges", []):
        if e.get("net"):
            affected_nets.add(e["net"])

    old_input_pin_sources = {
        f"{p['sink_cell']}/{p['sink_ref_pin']}": p
        for p in phase3["lut_input_pins"]
    }

    manifest = {
        "phase": "FASE 6A FLEX",
        "baseline_dcp": baseline_dcp,
        "phase3_json": phase3_json,
        "candidate_json": candidate_json,
        "candidate_id": cand.get("candidate_id", ""),
        "candidate_status": cand.get("phase5b2_fast_status", cand.get("phase5d_status", "")),
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
            role["original_ref"] != role.get("logical_ref", "LUT6")
            for role in roles.values()
        ),
        "requires_output_driver_change": output_driver_changed,
        "role_count": len(roles),
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
        f.write(f"candidate_id={cand.get('candidate_id', '')}\n")
        f.write(f"truth_table_equivalence={cand.get('truth_table_equivalence')}\n")
        f.write(f"num_checked_vectors={cand.get('num_checked_vectors')}\n")
        f.write(f"estimated_improvement={cand.get('estimated_improvement')}\n")
        f.write(f"requires_lut_upgrade={manifest['requires_lut_upgrade']}\n")
        f.write(f"requires_output_driver_change={manifest['requires_output_driver_change']}\n")
        f.write(f"old_output_net={old_output_net}\n")
        f.write(f"old_output_driver={old_output_driver_pin}\n")
        f.write(f"new_output_driver={new_output_driver_pin}\n")
        f.write(f"role_count={len(roles)}\n")
        f.write(f"num_operations={len(operations)}\n")
        f.write(f"num_input_rewires={len(input_rewires)}\n")
        f.write(f"num_affected_nets={len(affected_nets)}\n")
        f.write(f"manifest={manifest_path}\n")
        f.write(f"vivado_check_tcl={tcl_path}\n")

    # Feasibility Tcl.
    with open(tcl_path, "w") as f:
        f.write("# Auto-generated by phase6a_prepare_eco_manifest_flex.py\n")
        f.write("# Feasibility only. Does NOT modify DCP.\n\n")
        f.write(f"set baseline_dcp {tcl_quote(baseline_dcp)}\n")
        f.write(f"set out_dir {tcl_quote(out_dir)}\n")
        f.write("file mkdir $out_dir\n")
        f.write("set csv_file [file join $out_dir phase6a_vivado_feasibility_checks.csv]\n")
        f.write("set cf [open $csv_file w]\n")
        f.write('puts $cf "check,status,detail"\n')
        f.write("set fail_count 0\n\n")

        f.write(r'''
proc csv_escape {s} {
    set s [string trim $s]
    if {[regexp {[,\"\n\r]} $s]} {
        set s [string map [list "\"" "\"\""] $s]
        return "\"$s\""
    }
    return $s
}

proc check_write {cf name status detail} {
    puts $cf "[csv_escape $name],[csv_escape $status],[csv_escape $detail]"
    flush $cf
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
''')

        f.write("\nopen_checkpoint $baseline_dcp\n")
        f.write('check_write $cf "open_checkpoint" "PASS" $baseline_dcp\n\n')

        checked_cells = sorted({role["cell"] for role in roles.values()})

        for cell in checked_cells:
            f.write(f"\n# Check cell {cell}\n")
            f.write(f"set c [get_cells -quiet {tcl_quote(cell)}]\n")
            f.write("if {[llength $c] == 1} {\n")
            f.write(f"  check_write $cf {tcl_quote('cell_exists:' + cell)} PASS {tcl_quote(cell)}\n")
            f.write("} else {\n")
            f.write(f"  check_write $cf {tcl_quote('cell_exists:' + cell)} FAIL {tcl_quote(cell)}\n")
            f.write("  incr fail_count\n")
            f.write("}\n")

        for role_name, role in roles.items():
            cell = role["cell"]
            original_ref = role["original_ref"]
            logical_ref = role.get("logical_ref", "LUT6")

            for inp in role.get("inputs", []):
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
                        f"WARN {tcl_quote('pin absent now; expected after upgrade')}\n"
                    )
                else:
                    f.write(f"  check_write $cf {tcl_quote('target_pin_exists:' + full_pin)} FAIL {tcl_quote(full_pin)}\n")
                    f.write("  incr fail_count\n")

                f.write("}\n")

        boundary_nets = sorted({r["source_net"] for r in input_rewires if r["source_net"]})
        for net in boundary_nets:
            f.write(f"\n# Check boundary net {net}\n")
            f.write(f"set n [get_nets -quiet {tcl_quote(net)}]\n")
            f.write("if {[llength $n] == 1} {\n")
            f.write(f"  check_write $cf {tcl_quote('boundary_net_exists:' + net)} PASS {tcl_quote(net)}\n")
            f.write("} else {\n")
            f.write(f"  check_write $cf {tcl_quote('boundary_net_exists:' + net)} FAIL {tcl_quote(net)}\n")
            f.write("  incr fail_count\n")
            f.write("}\n")

        f.write("\n# Output net check\n")
        f.write(f"set output_net [get_nets -quiet {tcl_quote(old_output_net)}]\n")
        f.write("if {[llength $output_net] == 1} {\n")
        f.write(f"  check_write $cf {tcl_quote('output_net_exists:' + old_output_net)} PASS {tcl_quote(old_output_net)}\n")
        f.write("} else {\n")
        f.write(f"  check_write $cf {tcl_quote('output_net_exists:' + old_output_net)} FAIL {tcl_quote(old_output_net)}\n")
        f.write("  incr fail_count\n")
        f.write("}\n")

        f.write("\n# New output driver pin check\n")
        f.write(f"set new_driver_pin [get_pins -quiet {tcl_quote(new_output_driver_pin)}]\n")
        f.write("if {[llength $new_driver_pin] == 1} {\n")
        f.write(f"  check_write $cf {tcl_quote('new_output_driver_pin_exists:' + new_output_driver_pin)} PASS {tcl_quote(new_output_driver_pin)}\n")
        f.write("} else {\n")
        f.write(f"  check_write $cf {tcl_quote('new_output_driver_pin_exists:' + new_output_driver_pin)} FAIL {tcl_quote(new_output_driver_pin)}\n")
        f.write("  incr fail_count\n")
        f.write("}\n")

        f.write("\n")
        f.write('check_write $cf "fail_count" [expr {$fail_count == 0 ? "PASS" : "FAIL"}] $fail_count\n')
        f.write("close $cf\n")
        f.write("if {$fail_count == 0} {\n")
        f.write('  puts "PHASE6A_VIVADO_CHECK_DONE"\n')
        f.write("} else {\n")
        f.write('  puts "PHASE6A_VIVADO_CHECK_FAIL fail_count=$fail_count"\n')
        f.write("  exit 2\n")
        f.write("}\n")

    print("PHASE6A_FLEX_MANIFEST_CREATED")
    print(f"Summary : {summary_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Tcl     : {tcl_path}")


if __name__ == "__main__":
    main()
