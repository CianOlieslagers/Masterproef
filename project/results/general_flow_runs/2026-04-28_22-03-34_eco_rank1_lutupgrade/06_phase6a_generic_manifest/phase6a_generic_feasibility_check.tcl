# Auto-generated Phase 6A generic feasibility check
set baseline_dcp "/home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/baseline_impl/checkpoints/post_route_timingexp.dcp"
set result_csv "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/06_phase6a_generic_manifest/phase6a_generic_feasibility_result.csv"

open_checkpoint $baseline_dcp

set fh [open $result_csv "w"]
puts $fh "check,status,detail"

proc emit_check {fh check status detail} {
    regsub -all {,} $detail {;} detail2
    puts $fh "$check,$status,$detail2"
}

set fail_count 0

proc check_cell_exists {fh cname} {
    set cs [get_cells -quiet $cname]
    if {[llength $cs] == 1} {
        emit_check $fh "cell_exists" "PASS" $cname
        return 1
    } else {
        emit_check $fh "cell_exists" "FAIL" $cname
        return 0
    }
}

proc check_net_exists {fh nname label} {
    if {$nname eq ""} {
        emit_check $fh $label "WARN" "empty_net_name"
        return 1
    }
    set ns [get_nets -quiet $nname]
    if {[llength $ns] >= 1} {
        emit_check $fh $label "PASS" $nname
        return 1
    } else {
        emit_check $fh $label "FAIL" $nname
        return 0
    }
}

proc check_pin_exists_or_expected {fh pin planned_upgrade} {
    set ps [get_pins -quiet $pin]
    if {[llength $ps] == 1} {
        emit_check $fh "pin_exists" "PASS" $pin
        return 1
    }
    if {$planned_upgrade} {
        emit_check $fh "pin_exists_after_upgrade" "PASS" $pin
        return 1
    }
    emit_check $fh "pin_exists" "FAIL" $pin
    return 0
}

if {![check_cell_exists $fh "f[108]_INST_0_i_8"]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_8/I0" 0]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_8/I1" 0]} { incr fail_count }
if {![check_cell_exists $fh "f[108]_INST_0_i_7"]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_7/I0" 0]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_7/I1" 0]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_7/I2" 0]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_7/I3" 0]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_7/I4" 0]} { incr fail_count }
if {![check_cell_exists $fh "f[108]_INST_0_i_9"]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_9/I0" 1]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_9/I1" 1]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_9/I2" 1]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_9/I3" 1]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_9/I4" 1]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_9/I5" 1]} { incr fail_count }
if {![check_cell_exists $fh "f[108]_INST_0_i_6"]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_6/I0" 0]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_6/I1" 0]} { incr fail_count }
if {![check_pin_exists_or_expected $fh "f[108]_INST_0_i_6/I2" 0]} { incr fail_count }
if {![check_net_exists $fh "f[99]_INST_0_i_3_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[99]_INST_0_i_2_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[99]_INST_0_i_3_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[99]_INST_0_i_2_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[98]_INST_0_i_3_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[98]_INST_0_i_2_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "p_149_in" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[101]_INST_0_i_2_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[100]_INST_0_i_3_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[100]_INST_0_i_2_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[101]_INST_0_i_3_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_cell_exists $fh "f[108]_INST_0_i_7"]} { incr fail_count }
if {![check_cell_exists $fh "f[108]_INST_0_i_8"]} { incr fail_count }
if {![check_cell_exists $fh "f[108]_INST_0_i_9"]} { incr fail_count }
if {![check_net_exists $fh "f[102]_INST_0_i_2_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "f[102]_INST_0_i_3_n_0" "boundary_net_exists"]} { incr fail_count }
if {![check_net_exists $fh "p_124_in" "output_net_exists"]} { incr fail_count }
if {![check_cell_exists $fh "f[108]_INST_0_i_6"]} { incr fail_count }

emit_check $fh "manifest_path" "INFO" "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-28_22-03-34_eco_rank1_lutupgrade/06_phase6a_generic_manifest/phase6a_generic_eco_manifest.json"
emit_check $fh "fail_count" [expr {$fail_count == 0 ? "PASS" : "FAIL"}] $fail_count
close $fh

if {$fail_count == 0} {
    puts "PHASE6A_GENERIC_FEASIBILITY_PASS"
} else {
    puts "PHASE6A_GENERIC_FEASIBILITY_FAIL fail_count=$fail_count"
    exit 2
}
