set dcp "/home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/phase6b1_lut_upgrade_test/post_route_lut2_to_lut6_microtest.dcp"
set out_dir "/home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/phase6b1_lut_upgrade_test"

file mkdir $out_dir

set rpt [file join $out_dir vivado_lut_upgrade_check.txt]
set csv [file join $out_dir vivado_lut_upgrade_check.csv]

set rf [open $rpt w]
set cf [open $csv w]

puts $cf "check,status,detail"

proc check_write {cf check status detail} {
    puts $cf "$check,$status,$detail"
}

open_checkpoint $dcp
check_write $cf "open_checkpoint" "PASS" $dcp

set c [get_cells -quiet "f[108]_INST_0_i_8"]

if {[llength $c] == 1} {
    check_write $cf "cell_exists" "PASS" "f[108]_INST_0_i_8"

    set ref [get_property REF_NAME $c]
    set init [get_property INIT $c]
    set loc [get_property LOC $c]
    set bel [get_property BEL $c]

    puts $rf "cell=f[108]_INST_0_i_8"
    puts $rf "REF_NAME=$ref"
    puts $rf "INIT=$init"
    puts $rf "LOC=$loc"
    puts $rf "BEL=$bel"

    if {$ref eq "LUT6"} {
        check_write $cf "ref_is_lut6" "PASS" $ref
    } else {
        check_write $cf "ref_is_lut6" "FAIL" $ref
    }

    if {$init eq "64'h00000EEF0EEFFFFF"} {
        check_write $cf "init_matches" "PASS" $init
    } else {
        check_write $cf "init_matches" "FAIL" $init
    }

    foreach p {I0 I1 I2 I3 I4 I5 O} {
        set pin_name "f[108]_INST_0_i_8/$p"
        set pin [get_pins -quiet $pin_name]

        if {[llength $pin] == 1} {
            check_write $cf "pin_exists:$pin_name" "PASS" $pin_name
        } else {
            check_write $cf "pin_exists:$pin_name" "FAIL" $pin_name
        }
    }

} else {
    check_write $cf "cell_exists" "FAIL" "f[108]_INST_0_i_8"
}

report_route_status -file [file join $out_dir route_status_after_lut_upgrade.rpt]
report_drc -file [file join $out_dir drc_after_lut_upgrade.rpt]

close $rf
close $cf

puts "PHASE6B1_VIVADO_CHECK_DONE"
puts "CSV: $csv"
puts "RPT: $rpt"
