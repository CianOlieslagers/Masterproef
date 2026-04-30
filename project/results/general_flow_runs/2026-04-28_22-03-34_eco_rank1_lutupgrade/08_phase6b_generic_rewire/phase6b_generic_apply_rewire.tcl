# Auto-generated Phase 6B generic ECO rewire
set stage1_dcp {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/07_phase6b_generic_stage1/phase6b_generic_stage1_inits_upgrades.dcp}
set out_dcp {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/08_phase6b_generic_rewire/phase6b_generic_eco_unrouted.dcp}
set checks_csv {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/08_phase6b_generic_rewire/phase6b_generic_rewire_checks.csv}
set route_status_rpt {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/08_phase6b_generic_rewire/phase6b_generic_after_rewire_route_status.rpt}
set drc_rpt {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/08_phase6b_generic_rewire/phase6b_generic_after_rewire_drc.rpt}

open_checkpoint $stage1_dcp

set fh [open $checks_csv "w"]
puts $fh "check,status,detail"

proc csv_escape {s} {
    regsub -all {,} $s {;} s
    regsub -all {\n} $s { } s
    return $s
}

proc emit_check {fh check status detail} {
    puts $fh "[csv_escape $check],[csv_escape $status],[csv_escape $detail]"
}

set fail_count 0

proc get_single_pin {fh pin_name} {
    set p [get_pins -quiet $pin_name]
    if {[llength $p] != 1} {
        emit_check $fh "pin_lookup" "FAIL" $pin_name
        return ""
    }
    return [lindex $p 0]
}

proc get_single_net_by_name {fh net_name} {
    set n [get_nets -quiet $net_name]
    if {[llength $n] < 1} {
        emit_check $fh "net_lookup" "FAIL" $net_name
        return ""
    }
    return [lindex $n 0]
}

proc disconnect_pin_if_connected {fh pin_name} {
    set p [get_single_pin $fh $pin_name]
    if {$p eq ""} { return 0 }
    set nets [get_nets -quiet -of_objects $p]
    if {[llength $nets] == 0} {
        emit_check $fh "disconnect_pin" "PASS" "$pin_name already_unconnected"
        return 1
    }
    foreach n $nets {
        set nname [get_property NAME $n]
        if {[catch {disconnect_net -net $n -objects $p} err]} {
            emit_check $fh "disconnect_pin" "FAIL" "$pin_name from $nname err=$err"
            return 0
        } else {
            emit_check $fh "disconnect_pin" "PASS" "$pin_name from $nname"
        }
    }
    return 1
}

proc get_or_create_output_net {fh source_cell} {
    set out_pin_name "${source_cell}/O"
    set p [get_single_pin $fh $out_pin_name]
    if {$p eq ""} { return "" }
    set nets [get_nets -quiet -of_objects $p]
    if {[llength $nets] >= 1} {
        return [lindex $nets 0]
    }
    set safe_name [string map {"[" "_" "]" "_" "/" "_"} $source_cell]
    set new_net_name "eco_${safe_name}_out"
    if {[catch {create_net $new_net_name} err]} {
        emit_check $fh "create_internal_net" "FAIL" "$new_net_name err=$err"
        return ""
    }
    set new_net [get_nets -quiet $new_net_name]
    if {[llength $new_net] < 1} {
        emit_check $fh "create_internal_net" "FAIL" "$new_net_name not_found_after_create"
        return ""
    }
    set new_net [lindex $new_net 0]
    if {[catch {connect_net -net $new_net -objects $p} err]} {
        emit_check $fh "connect_output_pin_to_new_net" "FAIL" "$out_pin_name err=$err"
        return ""
    }
    emit_check $fh "create_internal_net" "PASS" $new_net_name
    return $new_net
}

proc connect_pin_to_net {fh pin_name net_obj expected_detail} {
    set p [get_single_pin $fh $pin_name]
    if {$p eq "" || $net_obj eq ""} { return 0 }
    set net_name [get_property NAME $net_obj]
    if {[catch {connect_net -net $net_obj -objects $p} err]} {
        emit_check $fh "connect_pin" "FAIL" "$pin_name to $net_name err=$err"
        return 0
    }
    emit_check $fh "connect_pin" "PASS" "$pin_name to $net_name $expected_detail"
    return 1
}

proc verify_pin_net {fh pin_name expected_net_name} {
    set p [get_single_pin $fh $pin_name]
    if {$p eq ""} { return 0 }
    set nets [get_nets -quiet -of_objects $p]
    if {[llength $nets] != 1} {
        emit_check $fh "verify_pin_net" "FAIL" "$pin_name net_count=[llength $nets] expected=$expected_net_name"
        return 0
    }
    set actual [get_property NAME [lindex $nets 0]]
    if {$actual eq $expected_net_name} {
        emit_check $fh "verify_pin_net" "PASS" "$pin_name -> $actual"
        return 1
    } else {
        emit_check $fh "verify_pin_net" "FAIL" "$pin_name actual=$actual expected=$expected_net_name"
        return 0
    }
}

# 1) Disconnect alle sink pins die opnieuw verbonden moeten worden
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_8/I0}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_8/I1}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_7/I0}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_7/I1}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_7/I2}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_7/I3}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_7/I4}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_9/I0}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_9/I1}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_9/I2}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_9/I3}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_9/I4}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_9/I5}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_6/I0}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_6/I1}]} { incr fail_count }
if {![disconnect_pin_if_connected $fh {f[108]_INST_0_i_6/I2}]} { incr fail_count }

# 2) Output driver blijft hetzelfde
emit_check $fh "change_output_driver" "PASS" "output driver unchanged"

# 3) Nieuwe inputconnecties leggen
set target_net [get_single_net_by_name $fh {f[99]_INST_0_i_3_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_8/I0} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_8/I0} {f[99]_INST_0_i_3_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[99]_INST_0_i_2_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_8/I1} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_8/I1} {f[99]_INST_0_i_2_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[99]_INST_0_i_3_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_7/I0} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_7/I0} {f[99]_INST_0_i_3_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[99]_INST_0_i_2_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_7/I1} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_7/I1} {f[99]_INST_0_i_2_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[98]_INST_0_i_3_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_7/I2} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_7/I2} {f[98]_INST_0_i_3_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[98]_INST_0_i_2_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_7/I3} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_7/I3} {f[98]_INST_0_i_2_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {p_149_in}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_7/I4} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_7/I4} {p_149_in}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[101]_INST_0_i_2_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_9/I0} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_9/I0} {f[101]_INST_0_i_2_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[100]_INST_0_i_3_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_9/I1} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_9/I1} {f[100]_INST_0_i_3_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[100]_INST_0_i_2_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_9/I2} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_9/I2} {f[100]_INST_0_i_2_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[101]_INST_0_i_3_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_9/I3} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_9/I3} {f[101]_INST_0_i_3_n_0}]} { incr fail_count }
set target_net [get_or_create_output_net $fh {f[108]_INST_0_i_7}]
if {$target_net eq ""} {
    incr fail_count
} else {
    set target_net_name [get_property NAME $target_net]
    if {![connect_pin_to_net $fh {f[108]_INST_0_i_9/I4} $target_net {internal} ]} { incr fail_count }
    if {![verify_pin_net $fh {f[108]_INST_0_i_9/I4} $target_net_name]} { incr fail_count }
}
set target_net [get_or_create_output_net $fh {f[108]_INST_0_i_8}]
if {$target_net eq ""} {
    incr fail_count
} else {
    set target_net_name [get_property NAME $target_net]
    if {![connect_pin_to_net $fh {f[108]_INST_0_i_9/I5} $target_net {internal} ]} { incr fail_count }
    if {![verify_pin_net $fh {f[108]_INST_0_i_9/I5} $target_net_name]} { incr fail_count }
}
set target_net [get_or_create_output_net $fh {f[108]_INST_0_i_9}]
if {$target_net eq ""} {
    incr fail_count
} else {
    set target_net_name [get_property NAME $target_net]
    if {![connect_pin_to_net $fh {f[108]_INST_0_i_6/I0} $target_net {internal} ]} { incr fail_count }
    if {![verify_pin_net $fh {f[108]_INST_0_i_6/I0} $target_net_name]} { incr fail_count }
}
set target_net [get_single_net_by_name $fh {f[102]_INST_0_i_2_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_6/I1} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_6/I1} {f[102]_INST_0_i_2_n_0}]} { incr fail_count }
set target_net [get_single_net_by_name $fh {f[102]_INST_0_i_3_n_0}]
if {![connect_pin_to_net $fh {f[108]_INST_0_i_6/I2} $target_net {boundary} ]} { incr fail_count }
if {![verify_pin_net $fh {f[108]_INST_0_i_6/I2} {f[102]_INST_0_i_3_n_0}]} { incr fail_count }

# 4) Probeer affected nets te unroute-en. Als Vivado deze optie niet ondersteunt, gaan we verder.
set ns [get_nets -quiet {f[100]_INST_0_i_2_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[100]_INST_0_i_3_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[101]_INST_0_i_2_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[101]_INST_0_i_3_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[102]_INST_0_i_2_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[102]_INST_0_i_3_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[108]_INST_0_i_7_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[108]_INST_0_i_8_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[98]_INST_0_i_2_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[98]_INST_0_i_3_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[99]_INST_0_i_2_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {f[99]_INST_0_i_3_n_0}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {n11840132_in}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {p_124_in}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}
set ns [get_nets -quiet {p_149_in}]
if {[llength $ns] >= 1} {
    set n [lindex $ns 0]
    set nname [get_property NAME $n]
    if {[catch {route_design -unroute -nets $n} err]} {
        emit_check $fh "unroute_net" "WARN" "$nname err=$err"
    } else {
        emit_check $fh "unroute_net" "PASS" $nname
    }
}

# 5) Rapporten en checkpoint
report_route_status -file $route_status_rpt
report_drc -file $drc_rpt

emit_check $fh "fail_count" [expr {$fail_count == 0 ? "PASS" : "FAIL"}] $fail_count
close $fh

if {$fail_count != 0} {
    puts "PHASE6B_GENERIC_REWIRE_FAIL fail_count=$fail_count"
    exit 2
}

write_checkpoint -force $out_dcp
puts "PHASE6B_GENERIC_REWIRE_PASS"
puts "Output DCP: $out_dcp"
