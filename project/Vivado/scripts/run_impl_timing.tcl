# =========================
# Vivado implementation script + timing experiment
# =========================

# Controleer of de output directory is meegegeven
# =========================
# Vivado implementation script + timing experiment
# =========================

# Controleer of alle 5 argumenten zijn meegegeven
if { $argc != 5 } {
    puts "FOUT: Verkeerd aantal argumenten."
    puts "Gebruik: vivado -mode batch -source run_impl_timing.tcl -tclargs <out_dir> <src_file> <top_module> <part_number> <xdc_file>"
    exit 1
}

# Koppel argumenten aan variabelen
set out_dir    [lindex $argv 0]
set src_file   [lindex $argv 1]
set top_module [lindex $argv 2]
set part       [lindex $argv 3]
set xdc_file   [lindex $argv 4]

# Dynamische output paden
set rpt_dir $out_dir/reports
set dcp_dir $out_dir/checkpoints

# Mappen aanmaken
file mkdir $out_dir
file mkdir $rpt_dir
file mkdir $dcp_dir

puts "================================================="
puts "Start Implementation & Timing Experiment"
puts "Output map: $out_dir"
puts "Source:     $src_file"
puts "Top Module: $top_module"
puts "Part:       $part"
puts "================================================="

# Bronnen inlezen
read_verilog $src_file
read_xdc $xdc_file

# Synthesis
synth_design -top $top_module -part $part

write_checkpoint -force $dcp_dir/post_synth_timingexp.dcp
report_utilization -file $rpt_dir/post_synth_utilization_timingexp.rpt
report_timing_summary -file $rpt_dir/post_synth_timing_timingexp.rpt
write_edif -force $dcp_dir/post_synth.edf

# Implementation (Opt & Place)
opt_design
write_checkpoint -force $dcp_dir/post_opt_timingexp.dcp

place_design
write_checkpoint -force $dcp_dir/post_place_timingexp.dcp
report_utilization -file $rpt_dir/post_place_utilization_timingexp.rpt
report_timing_summary -file $rpt_dir/post_place_timing_timingexp.rpt
write_edif -force $dcp_dir/post_place.edf

# Routing
route_design
write_checkpoint -force $dcp_dir/post_route_timingexp.dcp
report_route_status -file $rpt_dir/post_route_status_timingexp.rpt
report_timing_summary -file $rpt_dir/post_route_timing_timingexp.rpt
report_timing -delay_type max -max_paths 20 -sort_by slack -file $rpt_dir/worst_paths_maxdelay.rpt
report_drc -file $rpt_dir/post_route_drc_timingexp.rpt
write_edif -force $dcp_dir/post_route.edf

puts "Implementation completed successfully. Alle bestanden staan in $out_dir"
