# Auto-generated Phase 6B generic ECO rewire
# This version follows the old working phase6b2 pattern.

set stage1_dcp {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/07_phase6b_generic_stage1/phase6b_generic_stage1_inits_upgrades.dcp}
set out_dcp {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/08_phase6b_generic_rewire_v2/phase6b_generic_eco_unrouted.dcp}
set checks_csv {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/08_phase6b_generic_rewire_v2/phase6b_generic_rewire_checks.csv}
set route_status_rpt {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/08_phase6b_generic_rewire_v2/phase6b_generic_after_rewire_route_status.rpt}
set drc_rpt {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/08_phase6b_generic_rewire_v2/phase6b_generic_after_rewire_drc.rpt}

open_checkpoint $stage1_dcp

set cf [open $checks_csv "w"]
puts $cf "check,status,detail"
set fail_count 0


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


# 0) Re-assert INITs after opening Stage1 DCP
set c [get_cells -quiet {f[108]_INST_0_i_8}]
if {[llength $c] == 1} {
    set_property INIT {4'h8} $c
    check_write $cf {set_init:f[108]_INST_0_i_8} PASS {4'h8}
    set ref_now [get_property REF_NAME $c]
    if {$ref_now eq {LUT2}} {
        check_write $cf {ref_check:f[108]_INST_0_i_8} PASS $ref_now
    } else {
        check_write $cf {ref_check:f[108]_INST_0_i_8} WARN "actual=$ref_now expected=LUT2"
    }
} else {
    check_write $cf {set_init:f[108]_INST_0_i_8} FAIL {cell not found}
    incr fail_count
}

set c [get_cells -quiet {f[108]_INST_0_i_7}]
if {[llength $c] == 1} {
    set_property INIT {64'hE000EEE0E000EEE0} $c
    check_write $cf {set_init:f[108]_INST_0_i_7} PASS {64'hE000EEE0E000EEE0}
    set ref_now [get_property REF_NAME $c]
    if {$ref_now eq {LUT6}} {
        check_write $cf {ref_check:f[108]_INST_0_i_7} PASS $ref_now
    } else {
        check_write $cf {ref_check:f[108]_INST_0_i_7} WARN "actual=$ref_now expected=LUT6"
    }
} else {
    check_write $cf {set_init:f[108]_INST_0_i_7} FAIL {cell not found}
    incr fail_count
}

set c [get_cells -quiet {f[108]_INST_0_i_9}]
if {[llength $c] == 1} {
    set_property INIT {64'h015701570157157F} $c
    check_write $cf {set_init:f[108]_INST_0_i_9} PASS {64'h015701570157157F}
    set ref_now [get_property REF_NAME $c]
    if {$ref_now eq {LUT6}} {
        check_write $cf {ref_check:f[108]_INST_0_i_9} PASS $ref_now
    } else {
        check_write $cf {ref_check:f[108]_INST_0_i_9} WARN "actual=$ref_now expected=LUT6"
    }
} else {
    check_write $cf {set_init:f[108]_INST_0_i_9} FAIL {cell not found}
    incr fail_count
}

set c [get_cells -quiet {f[108]_INST_0_i_6}]
if {[llength $c] == 1} {
    set_property INIT {64'h2B2B2B2B2B2B2B2B} $c
    check_write $cf {set_init:f[108]_INST_0_i_6} PASS {64'h2B2B2B2B2B2B2B2B}
    set ref_now [get_property REF_NAME $c]
    if {$ref_now eq {LUT6}} {
        check_write $cf {ref_check:f[108]_INST_0_i_6} PASS $ref_now
    } else {
        check_write $cf {ref_check:f[108]_INST_0_i_6} WARN "actual=$ref_now expected=LUT6"
    }
} else {
    check_write $cf {set_init:f[108]_INST_0_i_6} FAIL {cell not found}
    incr fail_count
}


# 1) Disconnect all target sink pins from old nets
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_6/I0}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_6/I1}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_6/I2}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_7/I0}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_7/I1}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_7/I2}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_7/I3}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_7/I4}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_8/I0}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_8/I1}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_9/I0}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_9/I1}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_9/I2}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_9/I3}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_9/I4}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_9/I5}]} { incr fail_count }

# 2) Disconnect output pins that will be rewired
# This is the key fix versus the first generic version.
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_6/O}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_7/O}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_8/O}]} { incr fail_count }
if {![disconnect_pin_from_all_nets $cf {f[108]_INST_0_i_9/O}]} { incr fail_count }

# 3) Connect boundary input nets to target sink pins
if {![connect_pin_to_net_name $cf {f[99]_INST_0_i_3_n_0} {f[108]_INST_0_i_8/I0}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[99]_INST_0_i_2_n_0} {f[108]_INST_0_i_8/I1}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[99]_INST_0_i_3_n_0} {f[108]_INST_0_i_7/I0}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[99]_INST_0_i_2_n_0} {f[108]_INST_0_i_7/I1}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[98]_INST_0_i_3_n_0} {f[108]_INST_0_i_7/I2}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[98]_INST_0_i_2_n_0} {f[108]_INST_0_i_7/I3}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {p_149_in} {f[108]_INST_0_i_7/I4}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[101]_INST_0_i_2_n_0} {f[108]_INST_0_i_9/I0}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[100]_INST_0_i_3_n_0} {f[108]_INST_0_i_9/I1}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[100]_INST_0_i_2_n_0} {f[108]_INST_0_i_9/I2}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[101]_INST_0_i_3_n_0} {f[108]_INST_0_i_9/I3}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[102]_INST_0_i_2_n_0} {f[108]_INST_0_i_6/I1}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {f[102]_INST_0_i_3_n_0} {f[108]_INST_0_i_6/I2}]} { incr fail_count }

# 4) Reconnect final output driver to old boundary-output net
if {![connect_pin_to_net_name $cf {p_124_in} {f[108]_INST_0_i_6/O}]} { incr fail_count }

# 5) Create/connect internal ECO nets

# Internal source f[108]_INST_0_i_7/O -> eco_f_108_INST_0_i_7_O_internal
if {![connect_pin_to_net_name $cf {eco_f_108_INST_0_i_7_O_internal} {f[108]_INST_0_i_7/O}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {eco_f_108_INST_0_i_7_O_internal} {f[108]_INST_0_i_9/I4}]} { incr fail_count }

# Internal source f[108]_INST_0_i_8/O -> eco_f_108_INST_0_i_8_O_internal
if {![connect_pin_to_net_name $cf {eco_f_108_INST_0_i_8_O_internal} {f[108]_INST_0_i_8/O}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {eco_f_108_INST_0_i_8_O_internal} {f[108]_INST_0_i_9/I5}]} { incr fail_count }

# Internal source f[108]_INST_0_i_9/O -> eco_f_108_INST_0_i_9_O_internal
if {![connect_pin_to_net_name $cf {eco_f_108_INST_0_i_9_O_internal} {f[108]_INST_0_i_9/O}]} { incr fail_count }
if {![connect_pin_to_net_name $cf {eco_f_108_INST_0_i_9_O_internal} {f[108]_INST_0_i_6/I0}]} { incr fail_count }

# 6) Remove old empty affected nets where possible
maybe_remove_empty_net $cf {f[100]_INST_0_i_2_n_0}
maybe_remove_empty_net $cf {f[100]_INST_0_i_3_n_0}
maybe_remove_empty_net $cf {f[101]_INST_0_i_2_n_0}
maybe_remove_empty_net $cf {f[101]_INST_0_i_3_n_0}
maybe_remove_empty_net $cf {f[102]_INST_0_i_2_n_0}
maybe_remove_empty_net $cf {f[102]_INST_0_i_3_n_0}
maybe_remove_empty_net $cf {f[108]_INST_0_i_7_n_0}
maybe_remove_empty_net $cf {f[108]_INST_0_i_8_n_0}
maybe_remove_empty_net $cf {f[98]_INST_0_i_2_n_0}
maybe_remove_empty_net $cf {f[98]_INST_0_i_3_n_0}
maybe_remove_empty_net $cf {f[99]_INST_0_i_2_n_0}
maybe_remove_empty_net $cf {f[99]_INST_0_i_3_n_0}
maybe_remove_empty_net $cf {n11840132_in}
maybe_remove_empty_net $cf {p_149_in}

# 7) Sanity checks after rewiring
if {![check_pin_net $cf {f[108]_INST_0_i_8/I0} {f[99]_INST_0_i_3_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_8/I1} {f[99]_INST_0_i_2_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_7/I0} {f[99]_INST_0_i_3_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_7/I1} {f[99]_INST_0_i_2_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_7/I2} {f[98]_INST_0_i_3_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_7/I3} {f[98]_INST_0_i_2_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_7/I4} {p_149_in}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_9/I0} {f[101]_INST_0_i_2_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_9/I1} {f[100]_INST_0_i_3_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_9/I2} {f[100]_INST_0_i_2_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_9/I3} {f[101]_INST_0_i_3_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_6/I1} {f[102]_INST_0_i_2_n_0}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_6/I2} {f[102]_INST_0_i_3_n_0}]} { incr fail_count }
if {![check_net_driver $cf {p_124_in} {f[108]_INST_0_i_6/O}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_7/O} {eco_f_108_INST_0_i_7_O_internal}]} { incr fail_count }
if {![check_net_driver $cf {eco_f_108_INST_0_i_7_O_internal} {f[108]_INST_0_i_7/O}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_9/I4} {eco_f_108_INST_0_i_7_O_internal}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_8/O} {eco_f_108_INST_0_i_8_O_internal}]} { incr fail_count }
if {![check_net_driver $cf {eco_f_108_INST_0_i_8_O_internal} {f[108]_INST_0_i_8/O}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_9/I5} {eco_f_108_INST_0_i_8_O_internal}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_9/O} {eco_f_108_INST_0_i_9_O_internal}]} { incr fail_count }
if {![check_net_driver $cf {eco_f_108_INST_0_i_9_O_internal} {f[108]_INST_0_i_9/O}]} { incr fail_count }
if {![check_pin_net $cf {f[108]_INST_0_i_6/I0} {eco_f_108_INST_0_i_9_O_internal}]} { incr fail_count }

# 8) Reports and unrouted checkpoint
report_route_status -file $route_status_rpt
report_drc -file $drc_rpt

check_write $cf "fail_count" [expr {$fail_count == 0 ? "PASS" : "FAIL"}] $fail_count

if {$fail_count != 0} {
    close $cf
    puts "PHASE6B_GENERIC_REWIRE_FAIL fail_count=$fail_count"
    exit 2
}

write_checkpoint -force $out_dcp
check_write $cf "write_unrouted_checkpoint" "PASS" $out_dcp
close $cf

puts "PHASE6B_GENERIC_REWIRE_PASS"
puts "Output DCP: $out_dcp"
