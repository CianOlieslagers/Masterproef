# Controleer of we de juiste argumenten krijgen
if { $argc != 2 } {
    puts "FOUT: Verkeerd aantal argumenten."
    puts "Gebruik: vivado -mode batch -source extract_connectivity.tcl -tclargs <input.dcp> <output_csv_pad>"
    exit 1
}

# Lees de argumenten in variabelen
set dcp_file [lindex $argv 0]
set out_csv  [lindex $argv 1]

puts "================================================="
puts "Extract Connectivity Tool"
puts "Input DCP: $dcp_file"
puts "Output CSV: $out_csv"
puts "================================================="

# 1. Laad het geplaatste ontwerp in
open_checkpoint $dcp_file

# Zorg dat de output map bestaat voor we schrijven
set out_dir [file dirname $out_csv]
file mkdir $out_dir

# 2. Maak het CSV bestand aan
set fp [open $out_csv w]
puts $fp "net,from_cell,to_cell"

# 3. Zoek alle connecties
puts "Bezig met het zoeken naar netwerk connecties..."
foreach net [get_nets -hierarchical -filter {TYPE != "POWER" && TYPE != "GROUND"}] {
    set src [get_cells -quiet -of_objects [get_pins -quiet -leaf -filter {DIRECTION == OUT} -of_objects $net]]
    set sinks [get_cells -quiet -of_objects [get_pins -quiet -leaf -filter {DIRECTION == IN} -of_objects $net]]

    foreach sink $sinks {
        if {$src != "" && $sink != ""} {
            puts $fp "$net,$src,$sink"
        }
    }
}
close $fp
puts "Klaar! CSV is succesvol opgeslagen in $out_csv."
