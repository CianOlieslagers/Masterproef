set dcp_path [lindex $argv 0]
set nodes_csv [lindex $argv 1]
set out_csv [lindex $argv 2]

open_checkpoint $dcp_path

set fh [open $out_csv "w"]
puts $fh "cell,ref_name,init,pins_i0_i5"

set f [open $nodes_csv r]
set lines [split [read $f] "\n"]
close $f

set header [split [lindex $lines 0] ","]
set cell_idx [lsearch -exact $header "physical_cell"]

foreach line [lrange $lines 1 end] {
    if {[string trim $line] eq ""} {
        continue
    }

    set cols [split $line ","]
    set cell_name [lindex $cols $cell_idx]

    set c [get_cells -quiet $cell_name]
    if {[llength $c] != 1} {
        puts $fh "$cell_name,NOT_FOUND,,"
        continue
    }

    set ref [get_property REF_NAME $c]
    set init [get_property INIT $c]

    set pin_status {}
    foreach p {I0 I1 I2 I3 I4 I5} {
        set full_pin "${cell_name}/${p}"
        set pin_obj [get_pins -quiet $full_pin]
        if {[llength $pin_obj] == 1} {
            lappend pin_status "${p}:YES"
        } else {
            lappend pin_status "${p}:NO"
        }
    }

    puts $fh "$cell_name,$ref,$init,[join $pin_status {|}]"
}

close $fh

report_route_status -file [file join [file dirname $out_csv] "stage1_reload_route_status.rpt"]
report_drc -file [file join [file dirname $out_csv] "stage1_reload_drc.rpt"]

puts "STAGE1_RELOAD_CHECK_DONE"
