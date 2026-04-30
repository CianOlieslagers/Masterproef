set dcp "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-29_14-42-06_eco_rank1_lutupgrade_physical_validation/09_phase6c_fresh_route/phase6b2_eco_routed_fresh.dcp"
set out_dir "/home/cian/Masterproef/project/results/general_flow_runs/2026-04-29_14-42-06_eco_rank1_lutupgrade_physical_validation/09_phase6c_fresh_route"


open_checkpoint $dcp

report_route_status -file "$out_dir/reload_route_status.rpt"
report_drc -file "$out_dir/reload_drc.rpt"
report_timing_summary -file "$out_dir/reload_timing_summary.rpt"

puts "FRESH_ROUTED_RELOAD_PASS"
