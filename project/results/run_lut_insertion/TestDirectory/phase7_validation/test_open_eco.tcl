open_checkpoint /home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/phase6b2_full_eco_patch1/phase6b2_eco_routed.dcp

report_route_status -file /home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/phase7_validation/test_eco_route_status.rpt
report_drc -file /home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/phase7_validation/test_eco_drc.rpt
report_timing_summary -file /home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/phase7_validation/test_eco_timing_summary.rpt

puts "ECO_OPEN_PASS"
