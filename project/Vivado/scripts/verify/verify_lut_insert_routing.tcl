# =========================================================
# Vivado ECO Verification Script (Routing & Timing Check)
# =========================================================

if { $argc != 2 } {
    puts "FOUT: Verkeerd aantal argumenten."
    puts "Gebruik: vivado -mode batch -source verify_eco_routing.tcl -tclargs <input_eco.dcp> <output_dir>"
    exit 1
}

set eco_dcp  [lindex $argv 0]
set out_dir  [lindex $argv 1]

puts "================================================="
puts "Start Vivado ECO Verificatie"
puts "Input DCP:  $eco_dcp"
puts "Output map: $out_dir"
puts "================================================="

file mkdir $out_dir

# 1. Lees de RapidWright output in
open_checkpoint $eco_dcp

# 2. Route het design (Vivado zal automatisch alleen de nieuwe/gewijzigde netten routen!)
puts "Start routing van de nieuwe ECO netten..."
route_design

# 3. Voer Design Rule Checks (DRC) uit om illegale configuraties op te sporen
puts "Genereren van DRC rapport..."
report_drc -file $out_dir/eco_post_route_drc.rpt

# 4. Controleer de timing
puts "Genereren van Timing rapport..."
report_timing_summary -file $out_dir/eco_post_route_timing.rpt
report_timing -delay_type max -max_paths 10 -sort_by slack -file $out_dir/eco_worst_paths.rpt

# 5. Sla het definitieve, volledig geroute resultaat op
write_checkpoint -force $out_dir/final_routed_eco.dcp

puts "ECO Verificatie succesvol afgerond! Rapporten in $out_dir"
