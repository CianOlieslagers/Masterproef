set in_dcp "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-27_12-06-13_eco_rank1_lutupgrade/08_phase6b_rewire/phase6b2_eco_unrouted.dcp"
set out_dir "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-27_12-06-13_eco_rank1_lutupgrade/09_phase6c_fresh_route"
set out_dcp "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-27_12-06-13_eco_rank1_lutupgrade/09_phase6c_fresh_route/phase6b2_eco_routed_fresh.dcp"
file mkdir $out_dir

set checks "$out_dir/fresh_route_checks.csv"
set cf [open $checks w]
puts $cf "check,status,detail"


proc check_write {cf check status detail} {
    puts $cf "$check,$status,$detail"
    flush $cf
}

open_checkpoint $in_dcp
check_write $cf "open_unrouted_checkpoint" "PASS" $in_dcp

report_route_status -file "$out_dir/before_route_status.rpt"
report_drc -file "$out_dir/before_route_drc.rpt"

if {[catch {route_design} err]} {
    check_write $cf "route_design_full" "FAIL" $err
} else {
    check_write $cf "route_design_full" "PASS" "route_design"
}

report_route_status -file "$out_dir/after_route_status.rpt"
report_drc -file "$out_dir/after_route_drc.rpt"
report_timing_summary -file "$out_dir/after_route_timing_summary.rpt"
report_timing -max_paths 10 -nworst 10 -file "$out_dir/after_route_worst_paths.rpt"

write_checkpoint -force $out_dcp
check_write $cf "write_routed_checkpoint" "PASS" $out_dcp

close $cf

puts "FRESH_ROUTE_DONE"
puts "OUT_DCP=$out_dcp"
puts "CHECKS=$checks"
