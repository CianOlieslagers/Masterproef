# =========================
# Vivado synthesis script
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

# Synthesis uitvoeren
synth_design -top $top_module -part $part

# Outputs wegschrijven
write_checkpoint -force $dcp_dir/post_synth.dcp
report_utilization -file $rpt_dir/post_synth_utilization.rpt
report_timing_summary -file $rpt_dir/post_synth_timing.rpt

puts "Synthesis completed successfully."
