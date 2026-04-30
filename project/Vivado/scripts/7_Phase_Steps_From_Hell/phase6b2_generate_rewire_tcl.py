#!/usr/bin/env python3
import json
import os
import re
import sys


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def sanitize_net_name(s):
    s = re.sub(r"[^A-Za-z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s)
    return "eco_" + s.strip("_")


def main():
    if len(sys.argv) != 5:
        fail(
            "usage: python3 phase6b2_generate_rewire_tcl.py "
            "<stage1.dcp> <phase6a_eco_manifest.json> <out_dir> <eco_routed.dcp>"
        )

    stage1_dcp = os.path.abspath(sys.argv[1])
    manifest_path = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])
    eco_routed_dcp = os.path.abspath(sys.argv[4])

    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(stage1_dcp):
        fail(f"stage1 DCP bestaat niet: {stage1_dcp}")
    if not os.path.exists(manifest_path):
        fail(f"manifest bestaat niet: {manifest_path}")

    with open(manifest_path, "r") as f:
        m = json.load(f)

    roles = m["roles"]
    rewires = m["input_rewires"]

    old_output_net = m["old_output"]["net"]
    old_output_driver_pin = m["old_output"]["driver_pin"]
    new_output_driver_pin = m["new_output"]["driver_pin"]

    old_output_driver_cell = m["old_output"]["driver_cell"]
    new_output_driver_cell = m["new_output"]["driver_cell"]

    # Make one internal ECO net for every helper -> root connection
    internal_connections = []
    for role_name, role in roles.items():
        sink_cell = role["cell"]
        for inp in role["inputs"]:
            if "source_cell" in inp:
                source_cell = inp["source_cell"]
                sink_pin = inp["sink_pin"]
                net_name = sanitize_net_name(f"{source_cell}_O_to_{sink_cell}_{sink_pin}")
                internal_connections.append({
                    "source_cell": source_cell,
                    "source_pin": f"{source_cell}/O",
                    "sink_cell": sink_cell,
                    "sink_pin": f"{sink_cell}/{sink_pin}",
                    "net_name": net_name,
                })

    tcl_path = os.path.join(out_dir, "phase6b2_apply_rewire_route.tcl")

    with open(tcl_path, "w") as f:
        f.write("# Auto-generated FASE 6B.2 rewire + route script\n")
        f.write("# This script modifies the stage1 upgraded DCP.\n\n")

        f.write(f"set stage1_dcp {q(stage1_dcp)}\n")
        f.write(f"set out_dir {q(out_dir)}\n")
        f.write(f"set eco_routed_dcp {q(eco_routed_dcp)}\n")
        f.write("file mkdir $out_dir\n")
        f.write("set checks_csv [file join $out_dir phase6b2_vivado_checks.csv]\n")
        f.write("set log_txt [file join $out_dir phase6b2_vivado_apply.log]\n")
        f.write("set cf [open $checks_csv w]\n")
        f.write("set lf [open $log_txt w]\n")
        f.write('puts $cf "check,status,detail"\n\n')

        f.write(r'''
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

proc pin_exists {pin_name} {
    set p [get_pins -quiet $pin_name]
    return [expr {[llength $p] == 1}]
}

proc net_exists {net_name} {
    set n [get_nets -quiet $net_name]
    return [expr {[llength $n] == 1}]
}

proc disconnect_pin_from_all_nets {cf pin_name} {
    set p [get_pins -quiet $pin_name]
    if {[llength $p] != 1} {
        check_write $cf "disconnect_pin_exists:$pin_name" "FAIL" $pin_name
        return 0
    }

    set nets [get_nets -quiet -of_objects $p]
    foreach n $nets {
        set nname [obj_name $n]
        if {[catch {disconnect_net -net $n -objects $p} err]} {
            check_write $cf "disconnect:$pin_name" "FAIL" "$nname :: $err"
            return 0
        } else {
            check_write $cf "disconnect:$pin_name" "PASS" $nname
        }
    }

    if {[llength $nets] == 0} {
        check_write $cf "disconnect:$pin_name" "PASS" "no_existing_net"
    }

    return 1
}

proc get_or_create_net {cf net_name} {
    set n [get_nets -quiet $net_name]
    if {[llength $n] == 1} {
        check_write $cf "net_exists:$net_name" "PASS" $net_name
        return $n
    }

    if {[catch {create_net $net_name} err]} {
        check_write $cf "create_net:$net_name" "FAIL" $err
        return ""
    }

    set n [get_nets -quiet $net_name]
    if {[llength $n] == 1} {
        check_write $cf "create_net:$net_name" "PASS" $net_name
        return $n
    }

    check_write $cf "create_net:$net_name" "FAIL" "created_but_not_found"
    return ""
}

proc connect_pin_to_net {cf net_name pin_name} {
    set p [get_pins -quiet $pin_name]
    if {[llength $p] != 1} {
        check_write $cf "connect_pin_exists:$pin_name" "FAIL" $pin_name
        return 0
    }

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
        return
    }

    set nets [get_nets -quiet -of_objects $p]
    set names {}
    foreach n $nets { lappend names [obj_name $n] }

    if {[lsearch -exact $names $expected_net] >= 0} {
        check_write $cf "check_pin_net:$pin_name" "PASS" $expected_net
    } else {
        check_write $cf "check_pin_net:$pin_name" "FAIL" "actual=$names expected=$expected_net"
    }
}

proc check_net_driver {cf net_name expected_driver_pin} {
    set n [get_nets -quiet $net_name]
    if {[llength $n] != 1} {
        check_write $cf "check_net_driver:$net_name" "FAIL" "net_missing"
        return
    }

    set drivers [get_pins -quiet -of_objects $n -filter {DIRECTION == OUT}]
    set names {}
    foreach d $drivers { lappend names [obj_name $d] }

    if {[lsearch -exact $names $expected_driver_pin] >= 0 && [llength $names] == 1} {
        check_write $cf "check_net_driver:$net_name" "PASS" $expected_driver_pin
    } else {
        check_write $cf "check_net_driver:$net_name" "FAIL" "actual=$names expected=$expected_driver_pin"
    }
}
''')

        f.write("\nopen_checkpoint $stage1_dcp\n")
        f.write("check_write $cf \"open_checkpoint\" \"PASS\" $stage1_dcp\n\n")

        # Re-assert INITs.
        for role_name, role in roles.items():
            f.write(f"\n# Set INIT for {role_name} {role['cell']}\n")
            f.write(f"set_property INIT {role['new_INIT']} [get_cells {q(role['cell'])}]\n")
            f.write(f"check_write $cf {q('set_init:' + role['cell'])} PASS {q(role['new_INIT'])}\n")

        # Disconnect all target sink pins first.
        all_target_pins = []
        for r in rewires:
            all_target_pins.append(r["sink_full_pin"])

        # Also output drivers.
        # Also disconnect all output pins that will become drivers of new ECO nets.
        # This includes:
        #   - old output driver
        #   - new output driver
        #   - helper output pins used in internal helper -> root connections
        all_internal_source_pins = sorted({
             c["source_pin"]
             for c in internal_connections
        })

        all_output_pins_to_disconnect = sorted(set(
          [
               old_output_driver_pin,
               new_output_driver_pin,
          ] + all_internal_source_pins
        ))

        f.write("\n# Disconnect all target sink pins from old nets\n")
        for p in sorted(set(all_target_pins)):
            f.write(f"disconnect_pin_from_all_nets $cf {q(p)}\n")

        f.write("\n# Disconnect old and new output pins from their old nets\n")
        for p in sorted(set(all_output_pins_to_disconnect)):
            f.write(f"disconnect_pin_from_all_nets $cf {q(p)}\n")

        # Connect boundary input rewires.
        f.write("\n# Connect boundary input nets to target sink pins\n")
        for r in rewires:
            if r["source_type"] == "BOUNDARY":
                f.write(f"connect_pin_to_net $cf {q(r['source_net'])} {q(r['sink_full_pin'])}\n")

        # Connect internal helper nets.
        f.write("\n# Create/connect internal helper nets\n")
        for c in internal_connections:
            f.write(f"\n# {c['source_pin']} -> {c['sink_pin']}\n")
            f.write(f"connect_pin_to_net $cf {q(c['net_name'])} {q(c['source_pin'])}\n")
            f.write(f"connect_pin_to_net $cf {q(c['net_name'])} {q(c['sink_pin'])}\n")

        # Output driver swap.
        f.write("\n# Output driver swap\n")
        f.write(f"connect_pin_to_net $cf {q(old_output_net)} {q(new_output_driver_pin)}\n")

        # Try to remove old empty internal nets if empty.
        f.write("\n# Remove old empty internal nets if they became empty\n")
        for net in m.get("affected_nets", []):
            if net != old_output_net:
                f.write(f"maybe_remove_empty_net $cf {q(net)}\n")

        # Sanity checks.
        f.write("\n# Sanity checks after rewiring\n")
        for r in rewires:
            if r["source_type"] == "BOUNDARY":
                f.write(f"check_pin_net $cf {q(r['sink_full_pin'])} {q(r['source_net'])}\n")

        for c in internal_connections:
            f.write(f"check_pin_net $cf {q(c['source_pin'])} {q(c['net_name'])}\n")
            f.write(f"check_pin_net $cf {q(c['sink_pin'])} {q(c['net_name'])}\n")
            f.write(f"check_net_driver $cf {q(c['net_name'])} {q(c['source_pin'])}\n")

        f.write(f"check_net_driver $cf {q(old_output_net)} {q(new_output_driver_pin)}\n")

        f.write("\n# Write unrouted/intermediate checkpoint\n")
        f.write("write_checkpoint -force [file join $out_dir phase6b2_eco_unrouted.dcp]\n")
        f.write("check_write $cf \"write_unrouted_checkpoint\" \"PASS\" \"phase6b2_eco_unrouted.dcp\"\n")

        f.write("\n# Route ECO design\n")
        f.write("set route_status UNKNOWN\n")
        f.write("if {[catch {route_design -preserve} err]} {\n")
        f.write("  check_write $cf \"route_design_preserve\" \"WARN\" $err\n")
        f.write("  if {[catch {route_design} err2]} {\n")
        f.write("    check_write $cf \"route_design_full\" \"FAIL\" $err2\n")
        f.write("    set route_status FAIL\n")
        f.write("  } else {\n")
        f.write("    check_write $cf \"route_design_full\" \"PASS\" \"route_design\"\n")
        f.write("    set route_status PASS\n")
        f.write("  }\n")
        f.write("} else {\n")
        f.write("  check_write $cf \"route_design_preserve\" \"PASS\" \"route_design -preserve\"\n")
        f.write("  set route_status PASS\n")
        f.write("}\n")

        f.write("\n# Reports\n")
        f.write("report_route_status -file [file join $out_dir phase6b2_route_status.rpt]\n")
        f.write("report_drc -file [file join $out_dir phase6b2_drc.rpt]\n")
        f.write("report_timing_summary -file [file join $out_dir phase6b2_timing_summary.rpt]\n")
        f.write("report_timing -max_paths 10 -nworst 10 -file [file join $out_dir phase6b2_worst_paths.rpt]\n")

        f.write("\nwrite_checkpoint -force $eco_routed_dcp\n")
        f.write("check_write $cf \"write_eco_routed_checkpoint\" \"PASS\" $eco_routed_dcp\n")

        f.write("\nclose $cf\n")
        f.write("close $lf\n")
        f.write("puts \"PHASE6B2_VIVADO_APPLY_DONE\"\n")
        f.write("puts \"Checks: $checks_csv\"\n")
        f.write("puts \"ECO DCP: $eco_routed_dcp\"\n")

    print(f"PHASE6B2_TCL_CREATED: {tcl_path}")


if __name__ == "__main__":
    main()
