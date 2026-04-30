set in_dcp  [lindex $argv 0]
set out_dcp [lindex $argv 1]
set out_dir [lindex $argv 2]

open_checkpoint $in_dcp

# Fresh route op de ECO-DCP.
route_design

write_checkpoint -force $out_dcp

report_route_status -file [file join $out_dir "after_route_status.rpt"]
report_drc          -file [file join $out_dir "after_route_drc.rpt"]
report_timing_summary -file [file join $out_dir "after_route_timing_summary.rpt"]

puts "PHASE6C_GENERIC_ROUTE_DONE"
puts "Output DCP: $out_dcp"
