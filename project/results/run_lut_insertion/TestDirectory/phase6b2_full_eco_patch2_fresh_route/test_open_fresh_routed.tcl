set dcp "/home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/phase6b2_full_eco_patch2_fresh_route/phase6b2_eco_routed_fresh.dcp"
set out_dir "/home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/phase6b2_full_eco_patch2_fresh_route"

open_checkpoint $dcp

report_route_status -file "$out_dir/reload_route_status.rpt"
report_drc -file "$out_dir/reload_drc.rpt"
report_timing_summary -file "$out_dir/reload_timing_summary.rpt"

puts "FRESH_ROUTED_RELOAD_PASS"
