set dcp     [lindex $argv 0]
set out_dir [lindex $argv 1]

open_checkpoint $dcp

report_route_status -file [file join $out_dir reload_route_status.rpt]
report_drc -file [file join $out_dir reload_drc.rpt]
report_timing_summary -file [file join $out_dir reload_timing_summary.rpt]
report_timing -max_paths 10 -nworst 10 -file [file join $out_dir reload_worst_paths.rpt]

puts "FRESH_ROUTED_RELOAD_PASS"
