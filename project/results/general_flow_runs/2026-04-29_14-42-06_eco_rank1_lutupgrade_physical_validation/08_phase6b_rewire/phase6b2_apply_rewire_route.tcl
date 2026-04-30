# Auto-generated FASE 6B.2 rewire + route script
# This script modifies the stage1 upgraded DCP.

set stage1_dcp "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-29_14-42-06_eco_rank1_lutupgrade_physical_validation/07_phase6b_stage1/phase6b2_stage1_upgraded_inits.dcp"
set out_dir "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-29_14-42-06_eco_rank1_lutupgrade_physical_validation/08_phase6b_rewire"
set eco_routed_dcp "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-29_14-42-06_eco_rank1_lutupgrade_physical_validation/08_phase6b_rewire/phase6b2_eco_routed_same_session.dcp"
file mkdir $out_dir
set checks_csv [file join $out_dir phase6b2_vivado_checks.csv]
set log_txt [file join $out_dir phase6b2_vivado_apply.log]
set cf [open $checks_csv w]
set lf [open $log_txt w]
puts $cf "check,status,detail"


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

open_checkpoint $stage1_dcp
check_write $cf "open_checkpoint" "PASS" $stage1_dcp


# Set INIT for root f[108]_INST_0_i_8
set_property INIT 64'h00000EEF0EEFFFFF [get_cells "f[108]_INST_0_i_8"]
check_write $cf "set_init:f[108]_INST_0_i_8" PASS "64'h00000EEF0EEFFFFF"

# Set INIT for helper1 f[108]_INST_0_i_7
set_property INIT 64'h022A2A2A0202022A [get_cells "f[108]_INST_0_i_7"]
check_write $cf "set_init:f[108]_INST_0_i_7" PASS "64'h022A2A2A0202022A"

# Set INIT for helper2 f[108]_INST_0_i_6
set_property INIT 64'h1111111111111111 [get_cells "f[108]_INST_0_i_6"]
check_write $cf "set_init:f[108]_INST_0_i_6" PASS "64'h1111111111111111"

# Disconnect all target sink pins from old nets
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_6/I0"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_6/I1"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_7/I0"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_7/I1"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_7/I2"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_7/I3"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_7/I4"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_7/I5"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_8/I0"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_8/I1"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_8/I2"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_8/I3"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_8/I4"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_8/I5"

# Disconnect old and new output pins from their old nets
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_6/O"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_7/O"
disconnect_pin_from_all_nets $cf "f[108]_INST_0_i_8/O"

# Connect boundary input nets to target sink pins
connect_pin_to_net $cf "f[101]_INST_0_i_2_n_0" "f[108]_INST_0_i_8/I2"
connect_pin_to_net $cf "f[101]_INST_0_i_3_n_0" "f[108]_INST_0_i_8/I3"
connect_pin_to_net $cf "f[102]_INST_0_i_2_n_0" "f[108]_INST_0_i_8/I4"
connect_pin_to_net $cf "f[102]_INST_0_i_3_n_0" "f[108]_INST_0_i_8/I5"
connect_pin_to_net $cf "n11840132_in" "f[108]_INST_0_i_7/I0"
connect_pin_to_net $cf "f[99]_INST_0_i_3_n_0" "f[108]_INST_0_i_7/I1"
connect_pin_to_net $cf "f[99]_INST_0_i_2_n_0" "f[108]_INST_0_i_7/I2"
connect_pin_to_net $cf "f[98]_INST_0_i_3_n_0" "f[108]_INST_0_i_7/I3"
connect_pin_to_net $cf "f[98]_INST_0_i_2_n_0" "f[108]_INST_0_i_7/I4"
connect_pin_to_net $cf "p_149_in" "f[108]_INST_0_i_7/I5"
connect_pin_to_net $cf "f[100]_INST_0_i_3_n_0" "f[108]_INST_0_i_6/I0"
connect_pin_to_net $cf "f[100]_INST_0_i_2_n_0" "f[108]_INST_0_i_6/I1"

# Create/connect internal helper nets

# f[108]_INST_0_i_7/O -> f[108]_INST_0_i_8/I0
connect_pin_to_net $cf "eco_f_108_INST_0_i_7_O_to_f_108_INST_0_i_8_I0" "f[108]_INST_0_i_7/O"
connect_pin_to_net $cf "eco_f_108_INST_0_i_7_O_to_f_108_INST_0_i_8_I0" "f[108]_INST_0_i_8/I0"

# f[108]_INST_0_i_6/O -> f[108]_INST_0_i_8/I1
connect_pin_to_net $cf "eco_f_108_INST_0_i_6_O_to_f_108_INST_0_i_8_I1" "f[108]_INST_0_i_6/O"
connect_pin_to_net $cf "eco_f_108_INST_0_i_6_O_to_f_108_INST_0_i_8_I1" "f[108]_INST_0_i_8/I1"

# Output driver swap
connect_pin_to_net $cf "p_124_in" "f[108]_INST_0_i_8/O"

# Remove old empty internal nets if they became empty
maybe_remove_empty_net $cf "f[100]_INST_0_i_2_n_0"
maybe_remove_empty_net $cf "f[100]_INST_0_i_3_n_0"
maybe_remove_empty_net $cf "f[101]_INST_0_i_2_n_0"
maybe_remove_empty_net $cf "f[101]_INST_0_i_3_n_0"
maybe_remove_empty_net $cf "f[102]_INST_0_i_2_n_0"
maybe_remove_empty_net $cf "f[102]_INST_0_i_3_n_0"
maybe_remove_empty_net $cf "f[108]_INST_0_i_7_n_0"
maybe_remove_empty_net $cf "f[108]_INST_0_i_8_n_0"
maybe_remove_empty_net $cf "f[98]_INST_0_i_2_n_0"
maybe_remove_empty_net $cf "f[98]_INST_0_i_3_n_0"
maybe_remove_empty_net $cf "f[99]_INST_0_i_2_n_0"
maybe_remove_empty_net $cf "f[99]_INST_0_i_3_n_0"
maybe_remove_empty_net $cf "n11840132_in"
maybe_remove_empty_net $cf "p_149_in"

# Sanity checks after rewiring
check_pin_net $cf "f[108]_INST_0_i_8/I2" "f[101]_INST_0_i_2_n_0"
check_pin_net $cf "f[108]_INST_0_i_8/I3" "f[101]_INST_0_i_3_n_0"
check_pin_net $cf "f[108]_INST_0_i_8/I4" "f[102]_INST_0_i_2_n_0"
check_pin_net $cf "f[108]_INST_0_i_8/I5" "f[102]_INST_0_i_3_n_0"
check_pin_net $cf "f[108]_INST_0_i_7/I0" "n11840132_in"
check_pin_net $cf "f[108]_INST_0_i_7/I1" "f[99]_INST_0_i_3_n_0"
check_pin_net $cf "f[108]_INST_0_i_7/I2" "f[99]_INST_0_i_2_n_0"
check_pin_net $cf "f[108]_INST_0_i_7/I3" "f[98]_INST_0_i_3_n_0"
check_pin_net $cf "f[108]_INST_0_i_7/I4" "f[98]_INST_0_i_2_n_0"
check_pin_net $cf "f[108]_INST_0_i_7/I5" "p_149_in"
check_pin_net $cf "f[108]_INST_0_i_6/I0" "f[100]_INST_0_i_3_n_0"
check_pin_net $cf "f[108]_INST_0_i_6/I1" "f[100]_INST_0_i_2_n_0"
check_pin_net $cf "f[108]_INST_0_i_7/O" "eco_f_108_INST_0_i_7_O_to_f_108_INST_0_i_8_I0"
check_pin_net $cf "f[108]_INST_0_i_8/I0" "eco_f_108_INST_0_i_7_O_to_f_108_INST_0_i_8_I0"
check_net_driver $cf "eco_f_108_INST_0_i_7_O_to_f_108_INST_0_i_8_I0" "f[108]_INST_0_i_7/O"
check_pin_net $cf "f[108]_INST_0_i_6/O" "eco_f_108_INST_0_i_6_O_to_f_108_INST_0_i_8_I1"
check_pin_net $cf "f[108]_INST_0_i_8/I1" "eco_f_108_INST_0_i_6_O_to_f_108_INST_0_i_8_I1"
check_net_driver $cf "eco_f_108_INST_0_i_6_O_to_f_108_INST_0_i_8_I1" "f[108]_INST_0_i_6/O"
check_net_driver $cf "p_124_in" "f[108]_INST_0_i_8/O"

# Write unrouted/intermediate checkpoint
write_checkpoint -force [file join $out_dir phase6b2_eco_unrouted.dcp]
check_write $cf "write_unrouted_checkpoint" "PASS" "phase6b2_eco_unrouted.dcp"

# Route ECO design
set route_status UNKNOWN
if {[catch {route_design -preserve} err]} {
  check_write $cf "route_design_preserve" "WARN" $err
  if {[catch {route_design} err2]} {
    check_write $cf "route_design_full" "FAIL" $err2
    set route_status FAIL
  } else {
    check_write $cf "route_design_full" "PASS" "route_design"
    set route_status PASS
  }
} else {
  check_write $cf "route_design_preserve" "PASS" "route_design -preserve"
  set route_status PASS
}

# Reports
report_route_status -file [file join $out_dir phase6b2_route_status.rpt]
report_drc -file [file join $out_dir phase6b2_drc.rpt]
report_timing_summary -file [file join $out_dir phase6b2_timing_summary.rpt]
report_timing -max_paths 10 -nworst 10 -file [file join $out_dir phase6b2_worst_paths.rpt]

write_checkpoint -force $eco_routed_dcp
check_write $cf "write_eco_routed_checkpoint" "PASS" $eco_routed_dcp

close $cf
close $lf
puts "PHASE6B2_VIVADO_APPLY_DONE"
puts "Checks: $checks_csv"
puts "ECO DCP: $eco_routed_dcp"
