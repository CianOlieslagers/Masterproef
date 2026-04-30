set dcp_path [lindex $argv 0]
set out_csv  [lindex $argv 1]

open_checkpoint $dcp_path

set cell_name "f[108]_INST_0_i_9"

set fh [open $out_csv "w"]
puts $fh "cell,exists,ref_name,loc,bel,site,is_loc_fixed,is_bel_fixed,pins"

set c [get_cells -quiet $cell_name]

if {[llength $c] != 1} {
    puts $fh "$cell_name,0,,,,,,,"
    close $fh
    exit
}

set c [lindex $c 0]

set ref [get_property REF_NAME $c]
set loc [get_property LOC $c]
set bel [get_property BEL $c]

set site ""
set sites [get_sites -quiet -of_objects $c]
if {[llength $sites] > 0} {
    set site [get_property NAME [lindex $sites 0]]
}

set is_loc_fixed ""
catch { set is_loc_fixed [get_property IS_LOC_FIXED $c] }

set is_bel_fixed ""
catch { set is_bel_fixed [get_property IS_BEL_FIXED $c] }

set pin_status {}
foreach p {I0 I1 I2 I3 I4 I5 O} {
    set full "${cell_name}/${p}"
    set po [get_pins -quiet $full]
    if {[llength $po] == 1} {
        set nets [get_nets -quiet -of_objects $po]
        set net_names {}
        foreach n $nets {
            lappend net_names [get_property NAME $n]
        }
        lappend pin_status "${p}:YES:[join $net_names {|}]"
    } else {
        lappend pin_status "${p}:NO:"
    }
}

puts $fh "$cell_name,1,$ref,$loc,$bel,$site,$is_loc_fixed,$is_bel_fixed,[join $pin_status {;}]"
close $fh
