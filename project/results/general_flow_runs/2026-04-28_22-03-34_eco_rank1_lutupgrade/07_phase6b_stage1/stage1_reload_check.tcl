set stage1_dcp [lindex $argv 0]
set out_dir    [lindex $argv 1]

open_checkpoint $stage1_dcp

set cf [open [file join $out_dir stage1_reload_check.csv] w]
puts $cf "cell,ref_name,loc,bel,site,init,pins_i0_i5"

foreach cell_name {
  f[108]_INST_0_i_6
  f[108]_INST_0_i_7
  f[108]_INST_0_i_8
  f[108]_INST_0_i_9
} {
  set c [get_cells -quiet $cell_name]

  if {[llength $c] != 1} {
    puts $cf "$cell_name,MISSING,,,,,"
    continue
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

  set init [get_property INIT $c]

  set pin_status {}
  foreach p {I0 I1 I2 I3 I4 I5} {
    set full_pin "$cell_name/$p"
    set pin_obj [get_pins -quiet $full_pin]
    if {[llength $pin_obj] == 1} {
      lappend pin_status "$p:YES"
    } else {
      lappend pin_status "$p:NO"
    }
  }

  puts $cf "$cell_name,$ref,$loc,$bel,$site,$init,[join $pin_status {|}]"
}

close $cf

report_route_status -file [file join $out_dir stage1_reload_route_status.rpt]
report_drc -file [file join $out_dir stage1_reload_drc.rpt]

puts "STAGE1_RELOAD_CHECK_DONE"
