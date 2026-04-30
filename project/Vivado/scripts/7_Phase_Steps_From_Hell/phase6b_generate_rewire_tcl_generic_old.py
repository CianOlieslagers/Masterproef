#!/usr/bin/env python3
"""
FASE 6B GENERIC — Genereer Vivado Tcl voor generic ECO rewiring.

Input:
  <stage1_dcp>
  <phase6a_generic_eco_manifest.json>
  <out_dir>

Output:
  phase6b_generic_apply_rewire.tcl
  phase6b_generic_eco_unrouted.dcp
  phase6b_generic_rewire_checks.csv
"""

import json
import os
import sys
from pathlib import Path


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def tcl_brace(s):
    """
    Tcl-safe brace quoting.
    FPGA names bevatten vaak [ ] en moeten dus niet als Tcl command substitution gezien worden.
    """
    s = "" if s is None else str(s)
    s = s.replace("\\", "/")
    s = s.replace("{", "\\{").replace("}", "\\}")
    return "{" + s + "}"


def main():
    if len(sys.argv) < 4:
        fail(
            "usage: python3 phase6b_generate_rewire_tcl_generic.py "
            "<stage1_dcp> <phase6a_generic_eco_manifest.json> <out_dir>"
        )

    stage1_dcp = os.path.abspath(sys.argv[1])
    manifest_path = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])

    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(stage1_dcp):
        fail(f"stage1 DCP not found: {stage1_dcp}")

    if not os.path.exists(manifest_path):
        fail(f"manifest not found: {manifest_path}")

    manifest = load_json(manifest_path)

    input_rewires = manifest.get("input_rewires", [])
    affected_nets = manifest.get("affected_nets", [])
    old_output = manifest.get("old_output", {})
    new_output = manifest.get("new_output", {})
    output_driver_changed = bool(manifest.get("output_driver_changed", False))

    if not input_rewires:
        fail("manifest has no input_rewires")

    tcl_path = os.path.join(out_dir, "phase6b_generic_apply_rewire.tcl")
    out_dcp = os.path.join(out_dir, "phase6b_generic_eco_unrouted.dcp")
    checks_csv = os.path.join(out_dir, "phase6b_generic_rewire_checks.csv")
    route_status_rpt = os.path.join(out_dir, "phase6b_generic_after_rewire_route_status.rpt")
    drc_rpt = os.path.join(out_dir, "phase6b_generic_after_rewire_drc.rpt")

    lines = []

    lines.append("# Auto-generated Phase 6B generic ECO rewire")
    lines.append(f"set stage1_dcp {tcl_brace(stage1_dcp)}")
    lines.append(f"set out_dcp {tcl_brace(out_dcp)}")
    lines.append(f"set checks_csv {tcl_brace(checks_csv)}")
    lines.append(f"set route_status_rpt {tcl_brace(route_status_rpt)}")
    lines.append(f"set drc_rpt {tcl_brace(drc_rpt)}")
    lines.append("")
    lines.append("open_checkpoint $stage1_dcp")
    lines.append("")
    lines.append('set fh [open $checks_csv "w"]')
    lines.append('puts $fh "check,status,detail"')
    lines.append("")
    lines.append("proc csv_escape {s} {")
    lines.append("    regsub -all {,} $s {;} s")
    lines.append("    regsub -all {\\n} $s { } s")
    lines.append("    return $s")
    lines.append("}")
    lines.append("")
    lines.append("proc emit_check {fh check status detail} {")
    lines.append("    puts $fh \"[csv_escape $check],[csv_escape $status],[csv_escape $detail]\"")
    lines.append("}")
    lines.append("")
    lines.append("set fail_count 0")
    lines.append("")
    lines.append("proc get_single_pin {fh pin_name} {")
    lines.append("    set p [get_pins -quiet $pin_name]")
    lines.append("    if {[llength $p] != 1} {")
    lines.append('        emit_check $fh "pin_lookup" "FAIL" $pin_name')
    lines.append("        return \"\"")
    lines.append("    }")
    lines.append("    return [lindex $p 0]")
    lines.append("}")
    lines.append("")
    lines.append("proc get_single_net_by_name {fh net_name} {")
    lines.append("    set n [get_nets -quiet $net_name]")
    lines.append("    if {[llength $n] < 1} {")
    lines.append('        emit_check $fh "net_lookup" "FAIL" $net_name')
    lines.append("        return \"\"")
    lines.append("    }")
    lines.append("    return [lindex $n 0]")
    lines.append("}")
    lines.append("")
    lines.append("proc disconnect_pin_if_connected {fh pin_name} {")
    lines.append("    set p [get_single_pin $fh $pin_name]")
    lines.append("    if {$p eq \"\"} { return 0 }")
    lines.append("    set nets [get_nets -quiet -of_objects $p]")
    lines.append("    if {[llength $nets] == 0} {")
    lines.append('        emit_check $fh "disconnect_pin" "PASS" "$pin_name already_unconnected"')
    lines.append("        return 1")
    lines.append("    }")
    lines.append("    foreach n $nets {")
    lines.append("        set nname [get_property NAME $n]")
    lines.append("        if {[catch {disconnect_net -net $n -objects $p} err]} {")
    lines.append('            emit_check $fh "disconnect_pin" "FAIL" "$pin_name from $nname err=$err"')
    lines.append("            return 0")
    lines.append("        } else {")
    lines.append('            emit_check $fh "disconnect_pin" "PASS" "$pin_name from $nname"')
    lines.append("        }")
    lines.append("    }")
    lines.append("    return 1")
    lines.append("}")
    lines.append("")
    lines.append("proc get_or_create_output_net {fh source_cell} {")
    lines.append("    set out_pin_name \"${source_cell}/O\"")
    lines.append("    set p [get_single_pin $fh $out_pin_name]")
    lines.append("    if {$p eq \"\"} { return \"\" }")
    lines.append("    set nets [get_nets -quiet -of_objects $p]")
    lines.append("    if {[llength $nets] >= 1} {")
    lines.append("        return [lindex $nets 0]")
    lines.append("    }")
    lines.append("    set safe_name [string map {\"[\" \"_\" \"]\" \"_\" \"/\" \"_\"} $source_cell]")
    lines.append("    set new_net_name \"eco_${safe_name}_out\"")
    lines.append("    if {[catch {create_net $new_net_name} err]} {")
    lines.append('        emit_check $fh "create_internal_net" "FAIL" "$new_net_name err=$err"')
    lines.append("        return \"\"")
    lines.append("    }")
    lines.append("    set new_net [get_nets -quiet $new_net_name]")
    lines.append("    if {[llength $new_net] < 1} {")
    lines.append('        emit_check $fh "create_internal_net" "FAIL" "$new_net_name not_found_after_create"')
    lines.append("        return \"\"")
    lines.append("    }")
    lines.append("    set new_net [lindex $new_net 0]")
    lines.append("    if {[catch {connect_net -net $new_net -objects $p} err]} {")
    lines.append('        emit_check $fh "connect_output_pin_to_new_net" "FAIL" "$out_pin_name err=$err"')
    lines.append("        return \"\"")
    lines.append("    }")
    lines.append('    emit_check $fh "create_internal_net" "PASS" $new_net_name')
    lines.append("    return $new_net")
    lines.append("}")
    lines.append("")
    lines.append("proc connect_pin_to_net {fh pin_name net_obj expected_detail} {")
    lines.append("    set p [get_single_pin $fh $pin_name]")
    lines.append("    if {$p eq \"\" || $net_obj eq \"\"} { return 0 }")
    lines.append("    set net_name [get_property NAME $net_obj]")
    lines.append("    if {[catch {connect_net -net $net_obj -objects $p} err]} {")
    lines.append('        emit_check $fh "connect_pin" "FAIL" "$pin_name to $net_name err=$err"')
    lines.append("        return 0")
    lines.append("    }")
    lines.append('    emit_check $fh "connect_pin" "PASS" "$pin_name to $net_name $expected_detail"')
    lines.append("    return 1")
    lines.append("}")
    lines.append("")
    lines.append("proc verify_pin_net {fh pin_name expected_net_name} {")
    lines.append("    set p [get_single_pin $fh $pin_name]")
    lines.append("    if {$p eq \"\"} { return 0 }")
    lines.append("    set nets [get_nets -quiet -of_objects $p]")
    lines.append("    if {[llength $nets] != 1} {")
    lines.append('        emit_check $fh "verify_pin_net" "FAIL" "$pin_name net_count=[llength $nets] expected=$expected_net_name"')
    lines.append("        return 0")
    lines.append("    }")
    lines.append("    set actual [get_property NAME [lindex $nets 0]]")
    lines.append("    if {$actual eq $expected_net_name} {")
    lines.append('        emit_check $fh "verify_pin_net" "PASS" "$pin_name -> $actual"')
    lines.append("        return 1")
    lines.append("    } else {")
    lines.append('        emit_check $fh "verify_pin_net" "FAIL" "$pin_name actual=$actual expected=$expected_net_name"')
    lines.append("        return 0")
    lines.append("    }")
    lines.append("}")
    lines.append("")

    lines.append("# 1) Disconnect alle sink pins die opnieuw verbonden moeten worden")
    for rw in input_rewires:
        sink_full_pin = rw["sink_full_pin"]
        lines.append(f"if {{![disconnect_pin_if_connected $fh {tcl_brace(sink_full_pin)}]}} {{ incr fail_count }}")
    lines.append("")

    # Output driver change only if needed.
    if output_driver_changed:
        old_net = old_output.get("net", "")
        old_driver_pin = old_output.get("driver_pin", "")
        new_driver_pin = new_output.get("driver_pin", "")

        lines.append("# 2) Output driver wijzigen")
        lines.append(f"set output_net [get_single_net_by_name $fh {tcl_brace(old_net)}]")
        lines.append(f"set old_driver_pin [get_single_pin $fh {tcl_brace(old_driver_pin)}]")
        lines.append(f"set new_driver_pin [get_single_pin $fh {tcl_brace(new_driver_pin)}]")
        lines.append("if {$output_net eq \"\" || $old_driver_pin eq \"\" || $new_driver_pin eq \"\"} {")
        lines.append("    incr fail_count")
        lines.append("} else {")
        lines.append("    catch {disconnect_net -net $output_net -objects $old_driver_pin} err1")
        lines.append("    set new_driver_old_nets [get_nets -quiet -of_objects $new_driver_pin]")
        lines.append("    foreach nn $new_driver_old_nets { catch {disconnect_net -net $nn -objects $new_driver_pin} }")
        lines.append("    if {[catch {connect_net -net $output_net -objects $new_driver_pin} err2]} {")
        lines.append('        emit_check $fh "change_output_driver" "FAIL" "err=$err2"')
        lines.append("        incr fail_count")
        lines.append("    } else {")
        lines.append('        emit_check $fh "change_output_driver" "PASS" "output driver changed"')
        lines.append("    }")
        lines.append("}")
    else:
        lines.append("# 2) Output driver blijft hetzelfde")
        lines.append('emit_check $fh "change_output_driver" "PASS" "output driver unchanged"')
    lines.append("")

    lines.append("# 3) Nieuwe inputconnecties leggen")
    for rw in input_rewires:
        sink_full_pin = rw["sink_full_pin"]
        source_type = rw["source_type"]

        if source_type == "BOUNDARY":
            source_net = rw["source_net"]
            lines.append(f"set target_net [get_single_net_by_name $fh {tcl_brace(source_net)}]")
            lines.append(
                f"if {{![connect_pin_to_net $fh {tcl_brace(sink_full_pin)} $target_net "
                f"{tcl_brace('boundary')} ]}} {{ incr fail_count }}"
            )
            lines.append(f"if {{![verify_pin_net $fh {tcl_brace(sink_full_pin)} {tcl_brace(source_net)}]}} {{ incr fail_count }}")

        elif source_type == "INTERNAL":
            source_cell = rw["source_cell"]
            lines.append(f"set target_net [get_or_create_output_net $fh {tcl_brace(source_cell)}]")
            lines.append("if {$target_net eq \"\"} {")
            lines.append("    incr fail_count")
            lines.append("} else {")
            lines.append("    set target_net_name [get_property NAME $target_net]")
            lines.append(
                f"    if {{![connect_pin_to_net $fh {tcl_brace(sink_full_pin)} $target_net "
                f"{tcl_brace('internal')} ]}} {{ incr fail_count }}"
            )
            lines.append(f"    if {{![verify_pin_net $fh {tcl_brace(sink_full_pin)} $target_net_name]}} {{ incr fail_count }}")
            lines.append("}")
        else:
            lines.append(f'emit_check $fh "connect_pin" "FAIL" "unknown source_type {source_type}"')
            lines.append("incr fail_count")

    lines.append("")

    lines.append("# 4) Probeer affected nets te unroute-en. Als Vivado deze optie niet ondersteunt, gaan we verder.")
    for net in affected_nets:
        if not net:
            continue
        lines.append(f"set ns [get_nets -quiet {tcl_brace(net)}]")
        lines.append("if {[llength $ns] >= 1} {")
        lines.append("    set n [lindex $ns 0]")
        lines.append("    set nname [get_property NAME $n]")
        lines.append("    if {[catch {route_design -unroute -nets $n} err]} {")
        lines.append('        emit_check $fh "unroute_net" "WARN" "$nname err=$err"')
        lines.append("    } else {")
        lines.append('        emit_check $fh "unroute_net" "PASS" $nname')
        lines.append("    }")
        lines.append("}")
    lines.append("")

    lines.append("# 5) Rapporten en checkpoint")
    lines.append("report_route_status -file $route_status_rpt")
    lines.append("report_drc -file $drc_rpt")
    lines.append("")
    lines.append('emit_check $fh "fail_count" [expr {$fail_count == 0 ? "PASS" : "FAIL"}] $fail_count')
    lines.append("close $fh")
    lines.append("")
    lines.append("if {$fail_count != 0} {")
    lines.append('    puts "PHASE6B_GENERIC_REWIRE_FAIL fail_count=$fail_count"')
    lines.append("    exit 2")
    lines.append("}")
    lines.append("")
    lines.append("write_checkpoint -force $out_dcp")
    lines.append('puts "PHASE6B_GENERIC_REWIRE_PASS"')
    lines.append('puts "Output DCP: $out_dcp"')

    Path(tcl_path).write_text("\n".join(lines) + "\n")

    summary_path = os.path.join(out_dir, "phase6b_generic_rewire_generation_summary.txt")
    with open(summary_path, "w") as f:
        f.write("phase6b_generic_rewire_generation_status=PASS\n")
        f.write(f"stage1_dcp={stage1_dcp}\n")
        f.write(f"manifest={manifest_path}\n")
        f.write(f"tcl={tcl_path}\n")
        f.write(f"out_dcp={out_dcp}\n")
        f.write(f"checks_csv={checks_csv}\n")
        f.write(f"route_status_rpt={route_status_rpt}\n")
        f.write(f"drc_rpt={drc_rpt}\n")
        f.write(f"num_input_rewires={len(input_rewires)}\n")
        f.write(f"num_affected_nets={len(affected_nets)}\n")
        f.write(f"output_driver_changed={int(output_driver_changed)}\n")

    print("PHASE6B_GENERIC_REWIRE_TCL_GENERATED")
    print(f"Tcl      : {tcl_path}")
    print(f"Out DCP  : {out_dcp}")
    print(f"Checks   : {checks_csv}")
    print(f"Summary  : {summary_path}")


if __name__ == "__main__":
    main()
