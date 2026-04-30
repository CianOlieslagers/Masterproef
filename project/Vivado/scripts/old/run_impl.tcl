# =========================
# Vivado implementation script
# =========================

# Instellingen
set top_module top
set part xc7a200tfbg676-1
# Paden
set src_file ./src/adder.v
set build_dir ./build
set rpt_dir $build_dir/reports
set dcp_dir $build_dir/checkpoints

# Mappen aanmaken
file mkdir $build_dir
file mkdir $rpt_dir
file mkdir $dcp_dir

# Verilog inlezen
read_verilog $src_file

# Synthesis
synth_design -top $top_module -part $part
write_checkpoint -force $dcp_dir/post_synth.dcp
report_utilization -file $rpt_dir/post_synth_utilization.rpt
report_timing_summary -file $rpt_dir/post_synth_timing.rpt

# Implementation
opt_design
write_checkpoint -force $dcp_dir/post_opt.dcp

place_design
write_checkpoint -force $dcp_dir/post_place.dcp
report_utilization -file $rpt_dir/post_place_utilization.rpt
report_timing_summary -file $rpt_dir/post_place_timing.rpt

route_design
write_checkpoint -force $dcp_dir/post_route.dcp
report_route_status -file $rpt_dir/post_route_status.rpt
report_timing_summary -file $rpt_dir/post_route_timing.rpt
report_drc -file $rpt_dir/post_route_drc.rpt

puts "Implementation completed successfully."
