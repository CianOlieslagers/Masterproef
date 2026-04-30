set routed_dcp [lindex $argv 0]
set out_dir    [lindex $argv 1]

open_checkpoint $routed_dcp

report_route_status -file [file join $out_dir "reload_route_status.rpt"]
report_drc          -file [file join $out_dir "reload_drc.rpt"]
report_timing_summary -file [file join $out_dir "reload_timing_summary.rpt"]

puts "PHASE6C_GENERIC_RELOAD_CHECK_DONE"
