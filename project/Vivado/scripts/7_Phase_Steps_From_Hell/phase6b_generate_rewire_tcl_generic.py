#!/usr/bin/env python3
"""
FASE 6B GENERIC — Genereer Vivado Tcl voor generic ABC ECO rewiring.

Deze versie volgt bewust de oude werkende phase6b2-logica:

  - disconnect alle target sink pins
  - disconnect output pins die nieuwe interne drivers worden
  - maak nieuwe ECO-nets voor interne verbindingen
  - verbind source output + sinks op die nieuwe ECO-nets
  - verbind final output driver terug op de oude boundary-output net
  - schrijf een unrouted ECO-DCP

Belangrijk:
  Deze fase route nog NIET finaal. Routing gebeurt in Phase 6C.
"""

import json
import os
import re
import sys
from pathlib import Path


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def tcl_brace(s):
    s = "" if s is None else str(s)
    s = s.replace("\\", "/")
    s = s.replace("{", "\\{").replace("}", "\\}")
    return "{" + s + "}"


def sanitize_net_name(s):
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(s))
    s = re.sub(r"_+", "_", s)
    return "eco_" + s.strip("_")


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

    m = load_json(manifest_path)

    rewires = m.get("input_rewires", [])
    nodes = m.get("nodes", [])
    affected_nets = m.get("affected_nets", [])

    old_output_net = m["old_output"]["net"]
    old_output_driver_pin = m["old_output"]["driver_pin"]
    new_output_driver_pin = m["new_output"]["driver_pin"]
    new_output_driver_cell = m["new_output"]["driver_cell"]

    if not rewires:
        fail("manifest has no input_rewires")

    tcl_path = os.path.join(out_dir, "phase6b_generic_apply_rewire.tcl")
    out_unrouted_dcp = os.path.join(out_dir, "phase6b_generic_eco_unrouted.dcp")
    checks_csv = os.path.join(out_dir, "phase6b_generic_rewire_checks.csv")
    route_status_rpt = os.path.join(out_dir, "phase6b_generic_after_rewire_route_status.rpt")
    drc_rpt = os.path.join(out_dir, "phase6b_generic_after_rewire_drc.rpt")

    # ------------------------------------------------------------------
    # Build internal ECO-net groups.
    #
    # Belangrijk:
    #   - Niet bestaande source output nets hergebruiken.
    #   - Eén ECO-net per internal source cell.
    #   - Als de source cell ook de final output driver is, gebruik dan
    #     old_output_net, want één output pin kan niet op twee nets zitten.
    # ------------------------------------------------------------------

    internal_groups = {}

    for r in rewires:
        if r["source_type"] != "INTERNAL":
            continue

        src_cell = r["source_cell"]
        src_pin = f"{src_cell}/O"

        if src_pin == new_output_driver_pin:
            net_name = old_output_net
        else:
            net_name = sanitize_net_name(f"{src_cell}_O_internal")

        if src_cell not in internal_groups:
            internal_groups[src_cell] = {
                "source_cell": src_cell,
                "source_pin": src_pin,
                "net_name": net_name,
                "sinks": [],
            }

        internal_groups[src_cell]["sinks"].append(r["sink_full_pin"])

    target_sink_pins = sorted(set(r["sink_full_pin"] for r in rewires))

    output_pins_to_disconnect = set()
    output_pins_to_disconnect.add(old_output_driver_pin)
    output_pins_to_disconnect.add(new_output_driver_pin)

    for g in internal_groups.values():
        output_pins_to_disconnect.add(g["source_pin"])

    output_pins_to_disconnect = sorted(output_pins_to_disconnect)

    # INITs opnieuw assert-en in Vivado.
    init_rows = []
    for n in nodes:
        init_rows.append({
            "cell": n["physical_cell"],
            "init": n["new_INIT_effective"],
            "effective_ref": n["effective_ref"],
        })

    lines = []

    lines.append("# Auto-generated Phase 6B generic ECO rewire")
    lines.append("# This version follows the old working phase6b2 pattern.")
    lines.append("")
    lines.append(f"set stage1_dcp {tcl_brace(stage1_dcp)}")
    lines.append(f"set out_dcp {tcl_brace(out_unrouted_dcp)}")
    lines.append(f"set checks_csv {tcl_brace(checks_csv)}")
    lines.append(f"set route_status_rpt {tcl_brace(route_status_rpt)}")
    lines.append(f"set drc_rpt {tcl_brace(drc_rpt)}")
    lines.append("")
    lines.append("open_checkpoint $stage1_dcp")
    lines.append("")
    lines.append('set cf [open $checks_csv "w"]')
    lines.append('puts $cf "check,status,detail"')
    lines.append("set fail_count 0")
    lines.append("")

    lines.append(r'''
proc csv_escape {s} {
    set s [string trim $s]
    if {[regexp {[,\"\n\r]} $s]} {
        set s [string map [list "\"" "\"\""] $s]
        return "\"$s\""
    }
    return $s
}

proc check_write {cf check status detail} {
    puts $cf "[csv_escape $check],[csv_escape $status],[csv_escape $detail]"
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

proc disconnect_pin_from_all_nets {cf pin_name} {
    set p [get_pins -quiet $pin_name]

    if {[llength $p] != 1} {
        check_write $cf "disconnect_pin_exists:$pin_name" "FAIL" $pin_name
        return 0
    }

    set p [lindex $p 0]
    set nets [get_nets -quiet -of_objects $p]

    if {[llength $nets] == 0} {
        check_write $cf "disconnect:$pin_name" "PASS" "no_existing_net"
        return 1
    }

    foreach n $nets {
        set nname [obj_name $n]

        if {[catch {disconnect_net -net $n -objects $p} err]} {
            check_write $cf "disconnect:$pin_name" "FAIL" "$nname :: $err"
            return 0
        } else {
            check_write $cf "disconnect:$pin_name" "PASS" $nname
        }
    }

    return 1
}

proc get_or_create_net {cf net_name} {
    set n [get_nets -quiet $net_name]

    if {[llength $n] >= 1} {
        check_write $cf "net_exists:$net_name" "PASS" $net_name
        return [lindex $n 0]
    }

    if {[catch {create_net $net_name} err]} {
        check_write $cf "create_net:$net_name" "FAIL" $err
        return ""
    }

    set n [get_nets -quiet $net_name]

    if {[llength $n] >= 1} {
        check_write $cf "create_net:$net_name" "PASS" $net_name
        return [lindex $n 0]
    }

    check_write $cf "create_net:$net_name" "FAIL" "created_but_not_found"
    return ""
}

proc connect_pin_to_net_name {cf net_name pin_name} {
    set p [get_pins -quiet $pin_name]

    if {[llength $p] != 1} {
        check_write $cf "connect_pin_exists:$pin_name" "FAIL" $pin_name
        return 0
    }

    set p [lindex $p 0]
    set n [get_or_create_net $cf $net_name]

    if {$n eq ""} {
        check_write $cf "connect_net_exists:$net_name" "FAIL" $net_name
        return 0
    }

    if {[catch {connect_net -net $n -objects $p} err]} {
        check_write $cf "connect:$pin_name" "FAIL" "$net_name :: $err"
        return 0
    }

    check_write $cf "connect:$pin_name" "PASS" $net_name
    return 1
}

proc maybe_remove_empty_net {cf net_name} {
    set n [get_nets -quiet $net_name]

    if {[llength $n] != 1} {
        return
    }

    set n [lindex $n 0]
    set pins [get_pins -quiet -of_objects $n]

    if {[llength $pins] == 0} {
        if {[catch {remove_net $n} err]} {
            check_write $cf "remove_empty_net:$net_name" "WARN" $err
        } else {
            check_write $cf "remove_empty_net:$net_name" "PASS" $net_name
        }
    }
}

proc check_pin_net {cf pin_name expected_net} {
    set p [get_pins -quiet $pin_name]

    if {[llength $p] != 1} {
        check_write $cf "check_pin_net:$pin_name" "FAIL" "pin_missing"
        return 0
    }

    set p [lindex $p 0]
    set nets [get_nets -quiet -of_objects $p]
    set names {}

    foreach n $nets {
        lappend names [obj_name $n]
    }

    if {[lsearch -exact $names $expected_net] >= 0 && [llength $names] == 1} {
        check_write $cf "check_pin_net:$pin_name" "PASS" $expected_net
        return 1
    } else {
        check_write $cf "check_pin_net:$pin_name" "FAIL" "actual=$names expected=$expected_net"
        return 0
    }
}

proc check_net_driver {cf net_name expected_driver_pin} {
    set n [get_nets -quiet $net_name]

    if {[llength $n] != 1} {
        check_write $cf "check_net_driver:$net_name" "FAIL" "net_missing"
        return 0
    }

    set n [lindex $n 0]
    set drivers [get_pins -quiet -of_objects $n -filter {DIRECTION == OUT}]
    set names {}

    foreach d $drivers {
        lappend names [obj_name $d]
    }

    if {[lsearch -exact $names $expected_driver_pin] >= 0 && [llength $names] == 1} {
        check_write $cf "check_net_driver:$net_name" "PASS" $expected_driver_pin
        return 1
    } else {
        check_write $cf "check_net_driver:$net_name" "FAIL" "actual=$names expected=$expected_driver_pin"
        return 0
    }
}
''')

    # Re-assert INITs.
    lines.append("")
    lines.append("# 0) Re-assert INITs after opening Stage1 DCP")
    for row in init_rows:
        cell = row["cell"]
        init = row["init"]
        ref = row["effective_ref"]
        lines.append(f"set c [get_cells -quiet {tcl_brace(cell)}]")
        lines.append("if {[llength $c] == 1} {")
        lines.append(f"    set_property INIT {tcl_brace(init)} $c")
        lines.append(f"    check_write $cf {tcl_brace('set_init:' + cell)} PASS {tcl_brace(init)}")
        lines.append("    set ref_now [get_property REF_NAME $c]")
        lines.append(f"    if {{$ref_now eq {tcl_brace(ref)}}} {{")
        lines.append(f"        check_write $cf {tcl_brace('ref_check:' + cell)} PASS $ref_now")
        lines.append("    } else {")
        lines.append(f"        check_write $cf {tcl_brace('ref_check:' + cell)} WARN \"actual=$ref_now expected={ref}\"")
        lines.append("    }")
        lines.append("} else {")
        lines.append(f"    check_write $cf {tcl_brace('set_init:' + cell)} FAIL {tcl_brace('cell not found')}")
        lines.append("    incr fail_count")
        lines.append("}")
        lines.append("")

    # Disconnect sink pins.
    lines.append("")
    lines.append("# 1) Disconnect all target sink pins from old nets")
    for p in target_sink_pins:
        lines.append(f"if {{![disconnect_pin_from_all_nets $cf {tcl_brace(p)}]}} {{ incr fail_count }}")

    # Disconnect source output pins.
    lines.append("")
    lines.append("# 2) Disconnect output pins that will be rewired")
    lines.append("# This is the key fix versus the first generic version.")
    for p in output_pins_to_disconnect:
        lines.append(f"if {{![disconnect_pin_from_all_nets $cf {tcl_brace(p)}]}} {{ incr fail_count }}")

    # Connect boundary inputs.
    lines.append("")
    lines.append("# 3) Connect boundary input nets to target sink pins")
    for r in rewires:
        if r["source_type"] != "BOUNDARY":
            continue

        source_net = r["source_net"]
        sink_pin = r["sink_full_pin"]

        lines.append(f"if {{![connect_pin_to_net_name $cf {tcl_brace(source_net)} {tcl_brace(sink_pin)}]}} {{ incr fail_count }}")

    # Connect final output driver back to old output net.
    lines.append("")
    lines.append("# 4) Reconnect final output driver to old boundary-output net")
    lines.append(f"if {{![connect_pin_to_net_name $cf {tcl_brace(old_output_net)} {tcl_brace(new_output_driver_pin)}]}} {{ incr fail_count }}")

    # Connect internal groups.
    lines.append("")
    lines.append("# 5) Create/connect internal ECO nets")
    for src_cell, g in sorted(internal_groups.items()):
        src_pin = g["source_pin"]
        net_name = g["net_name"]
        sinks = sorted(set(g["sinks"]))

        lines.append("")
        lines.append(f"# Internal source {src_pin} -> {net_name}")

        # If this source is also the final output driver, it was already connected above.
        if src_pin != new_output_driver_pin:
            lines.append(f"if {{![connect_pin_to_net_name $cf {tcl_brace(net_name)} {tcl_brace(src_pin)}]}} {{ incr fail_count }}")

        for sink_pin in sinks:
            lines.append(f"if {{![connect_pin_to_net_name $cf {tcl_brace(net_name)} {tcl_brace(sink_pin)}]}} {{ incr fail_count }}")

    # Remove empty old nets.
    lines.append("")
    lines.append("# 6) Remove old empty affected nets where possible")
    protected_nets = {old_output_net}
    for g in internal_groups.values():
        protected_nets.add(g["net_name"])

    for net in sorted(set(affected_nets)):
        if not net:
            continue
        if net in protected_nets:
            continue
        lines.append(f"maybe_remove_empty_net $cf {tcl_brace(net)}")

    # Sanity checks.
    lines.append("")
    lines.append("# 7) Sanity checks after rewiring")

    for r in rewires:
        if r["source_type"] == "BOUNDARY":
            lines.append(f"if {{![check_pin_net $cf {tcl_brace(r['sink_full_pin'])} {tcl_brace(r['source_net'])}]}} {{ incr fail_count }}")

    lines.append(f"if {{![check_net_driver $cf {tcl_brace(old_output_net)} {tcl_brace(new_output_driver_pin)}]}} {{ incr fail_count }}")

    for src_cell, g in sorted(internal_groups.items()):
        src_pin = g["source_pin"]
        net_name = g["net_name"]
        sinks = sorted(set(g["sinks"]))

        lines.append(f"if {{![check_pin_net $cf {tcl_brace(src_pin)} {tcl_brace(net_name)}]}} {{ incr fail_count }}")
        lines.append(f"if {{![check_net_driver $cf {tcl_brace(net_name)} {tcl_brace(src_pin)}]}} {{ incr fail_count }}")

        for sink_pin in sinks:
            lines.append(f"if {{![check_pin_net $cf {tcl_brace(sink_pin)} {tcl_brace(net_name)}]}} {{ incr fail_count }}")

    # Reports + checkpoint.
    lines.append("")
    lines.append("# 8) Reports and unrouted checkpoint")
    lines.append("report_route_status -file $route_status_rpt")
    lines.append("report_drc -file $drc_rpt")
    lines.append("")
    lines.append('check_write $cf "fail_count" [expr {$fail_count == 0 ? "PASS" : "FAIL"}] $fail_count')
    lines.append("")
    lines.append("if {$fail_count != 0} {")
    lines.append("    close $cf")
    lines.append('    puts "PHASE6B_GENERIC_REWIRE_FAIL fail_count=$fail_count"')
    lines.append("    exit 2")
    lines.append("}")
    lines.append("")
    lines.append("write_checkpoint -force $out_dcp")
    lines.append('check_write $cf "write_unrouted_checkpoint" "PASS" $out_dcp')
    lines.append("close $cf")
    lines.append("")
    lines.append('puts "PHASE6B_GENERIC_REWIRE_PASS"')
    lines.append('puts "Output DCP: $out_dcp"')

    Path(tcl_path).write_text("\n".join(lines) + "\n")

    summary_path = os.path.join(out_dir, "phase6b_generic_rewire_generation_summary.txt")
    with open(summary_path, "w") as f:
        f.write("phase6b_generic_rewire_generation_status=PASS\n")
        f.write(f"stage1_dcp={stage1_dcp}\n")
        f.write(f"manifest={manifest_path}\n")
        f.write(f"tcl={tcl_path}\n")
        f.write(f"out_dcp={out_unrouted_dcp}\n")
        f.write(f"checks_csv={checks_csv}\n")
        f.write(f"route_status_rpt={route_status_rpt}\n")
        f.write(f"drc_rpt={drc_rpt}\n")
        f.write(f"num_input_rewires={len(rewires)}\n")
        f.write(f"num_target_sink_pins={len(target_sink_pins)}\n")
        f.write(f"num_internal_groups={len(internal_groups)}\n")
        f.write(f"num_output_pins_to_disconnect={len(output_pins_to_disconnect)}\n")
        f.write(f"old_output_net={old_output_net}\n")
        f.write(f"old_output_driver_pin={old_output_driver_pin}\n")
        f.write(f"new_output_driver_pin={new_output_driver_pin}\n")
        f.write(f"new_output_driver_cell={new_output_driver_cell}\n")
        f.write("internal_groups:\n")
        for src_cell, g in sorted(internal_groups.items()):
            f.write(
                f"  {src_cell}: source_pin={g['source_pin']} "
                f"net={g['net_name']} sinks={'|'.join(sorted(set(g['sinks'])))}\n"
            )

    print("PHASE6B_GENERIC_REWIRE_TCL_GENERATED")
    print(f"Tcl      : {tcl_path}")
    print(f"Out DCP  : {out_unrouted_dcp}")
    print(f"Checks   : {checks_csv}")
    print(f"Summary  : {summary_path}")


if __name__ == "__main__":
    main()
