if { $argc != 2 } {
    puts "Gebruik: vivado -mode batch -source audit_wrong_nets.tcl -tclargs <manifest.tsv> <audit_results.tsv>"
    exit 1
}

set manifest_tsv [lindex $argv 0]
set audit_tsv    [lindex $argv 1]

proc tsv_escape {s} {
    regsub -all {\t} $s { } s
    regsub -all {\n} $s { } s
    return $s
}

proc is_lut_type {ptype} {
    return [regexp {^CLB\.LUT\.LUT[1-6]$} $ptype]
}

set f [open $manifest_tsv r]
set lines [split [read $f] "\n"]
close $f

if {[llength $lines] < 2} {
    puts "FOUT: leeg manifest"
    exit 2
}

set header [split [lindex $lines 0] "\t"]
array set idx {}
for {set i 0} {$i < [llength $header]} {incr i} {
    set idx([lindex $header $i]) $i
}

set reference_dcp ""
foreach line [lrange $lines 1 end] {
    if {$line eq ""} { continue }
    set cols [split $line "\t"]
    if {[llength $cols] > $idx(reference_dcp)} {
        set reference_dcp [lindex $cols $idx(reference_dcp)]
        break
    }
}

if {$reference_dcp eq ""} {
    puts "FOUT: geen reference_dcp in manifest"
    exit 3
}

puts "Open checkpoint: $reference_dcp"
open_checkpoint $reference_dcp

set out [open $audit_tsv w]
puts $out [join {
    iter
    net_name
    sink_cell
    target_slice
    baseline_ps
    eco_total_ps
    delta_total_ps
    sink_pin_cmd
    resolved_sink_pin
    sink_ref_name
    sink_primitive_group
    sink_primitive_subgroup
    sink_primitive_type
    source_cell
    source_ref_name
    source_primitive_group
    source_primitive_subgroup
    source_primitive_type
    actual_sink_pin_name
    source_is_lut
    sink_is_lut
    sink_pin_looks_lut_input
    strict_lut_to_lut
    likely_io_sink
    net_found_in_reference_dcp
    suspicious_reason
} "\t"]

proc getv {cols idx name} {
    if {[info exists idx($name)] && [llength $cols] > $idx($name)} {
        return [lindex $cols $idx($name)]
    }
    return ""
}

foreach line [lrange $lines 1 end] {
    if {$line eq ""} { continue }
    set cols [split $line "\t"]

    set iter              [getv $cols idx iter]
    set net_name          [getv $cols idx net_name]
    set sink_cell_name    [getv $cols idx sink_cell]
    set target_slice      [getv $cols idx target_slice]
    set baseline_ps       [getv $cols idx baseline_ps]
    set eco_total_ps      [getv $cols idx eco_total_ps]
    set delta_total_ps    [getv $cols idx delta_total_ps]
    set sink_pin_cmd      [getv $cols idx sink_pin_cmd]
    set resolved_sink_pin [getv $cols idx resolved_sink_pin]

    set sink_ref_name ""
    set sink_pg ""
    set sink_psg ""
    set sink_ptype ""
    set source_cell_name ""
    set source_ref_name ""
    set source_pg ""
    set source_psg ""
    set source_ptype ""
    set actual_sink_pin_name ""
    set source_is_lut 0
    set sink_is_lut 0
    set sink_pin_looks_lut_input 0
    set strict_lut_to_lut 0
    set likely_io_sink 0
    set net_found 0
    set suspicious_reasons {}

    set sink_cell [get_cells -quiet $sink_cell_name]
    if {[llength $sink_cell] > 0} {
        set sink_ref_name [get_property REF_NAME $sink_cell]
        set sink_pg        [get_property PRIMITIVE_GROUP $sink_cell]
        set sink_psg       [get_property PRIMITIVE_SUBGROUP $sink_cell]
        set sink_ptype     [get_property PRIMITIVE_TYPE $sink_cell]
        set sink_is_lut    [is_lut_type $sink_ptype]

        if {$sink_pg eq "I/O"} {
            set likely_io_sink 1
            lappend suspicious_reasons "sink_is_io"
        }
        if {!$sink_is_lut} {
            lappend suspicious_reasons "sink_not_lut"
        }
    } else {
        lappend suspicious_reasons "sink_cell_not_found"
    }

    set net [get_nets -quiet $net_name]
    if {[llength $net] > 0} {
        set net_found 1

        set out_pins [get_pins -quiet -of_objects $net -filter {DIRECTION == OUT}]
        if {[llength $out_pins] == 1} {
            set src_pin [lindex $out_pins 0]
            set src_cell [get_cells -quiet -of_objects $src_pin]
            if {[llength $src_cell] > 0} {
                set source_cell_name [get_property NAME $src_cell]
                set source_ref_name  [get_property REF_NAME $src_cell]
                set source_pg        [get_property PRIMITIVE_GROUP $src_cell]
                set source_psg       [get_property PRIMITIVE_SUBGROUP $src_cell]
                set source_ptype     [get_property PRIMITIVE_TYPE $src_cell]
                set source_is_lut    [is_lut_type $source_ptype]
                if {!$source_is_lut} {
                    lappend suspicious_reasons "source_not_lut"
                }
            } else {
                lappend suspicious_reasons "source_cell_not_found"
            }
        } else {
            lappend suspicious_reasons "driver_pin_count_[llength $out_pins]"
        }

        set in_pins [get_pins -quiet -of_objects $net -filter {DIRECTION == IN}]
        set found_sink_pin 0
        foreach p $in_pins {
            set c [get_cells -quiet -of_objects $p]
            if {[llength $c] > 0 && [get_property NAME $c] eq $sink_cell_name} {
                set actual_sink_pin_name [get_property REF_PIN_NAME $p]
                set found_sink_pin 1
                break
            }
        }

        if {!$found_sink_pin} {
            if {[llength $in_pins] == 1} {
                set p [lindex $in_pins 0]
                set actual_sink_pin_name [get_property REF_PIN_NAME $p]
                lappend suspicious_reasons "sink_pin_not_matched_to_sink_cell"
            } else {
                lappend suspicious_reasons "sink_pin_not_found_on_net"
            }
        }

        if {[regexp {^I[0-5]$} $actual_sink_pin_name]} {
            set sink_pin_looks_lut_input 1
        } else {
            if {$actual_sink_pin_name ne ""} {
                lappend suspicious_reasons "sink_pin_$actual_sink_pin_name"
            }
        }

    } else {
        lappend suspicious_reasons "net_not_found_in_reference_dcp"
    }

    if {$source_is_lut && $sink_is_lut && $sink_pin_looks_lut_input} {
        set strict_lut_to_lut 1
    }

    if {$resolved_sink_pin eq "I"} {
        lappend suspicious_reasons "resolved_pin_I"
    }

    puts $out [join [list \
        [tsv_escape $iter] \
        [tsv_escape $net_name] \
        [tsv_escape $sink_cell_name] \
        [tsv_escape $target_slice] \
        [tsv_escape $baseline_ps] \
        [tsv_escape $eco_total_ps] \
        [tsv_escape $delta_total_ps] \
        [tsv_escape $sink_pin_cmd] \
        [tsv_escape $resolved_sink_pin] \
        [tsv_escape $sink_ref_name] \
        [tsv_escape $sink_pg] \
        [tsv_escape $sink_psg] \
        [tsv_escape $sink_ptype] \
        [tsv_escape $source_cell_name] \
        [tsv_escape $source_ref_name] \
        [tsv_escape $source_pg] \
        [tsv_escape $source_psg] \
        [tsv_escape $source_ptype] \
        [tsv_escape $actual_sink_pin_name] \
        $source_is_lut \
        $sink_is_lut \
        $sink_pin_looks_lut_input \
        $strict_lut_to_lut \
        $likely_io_sink \
        $net_found \
        [tsv_escape [join $suspicious_reasons ";"]] \
    ] "\t"]
}

close $out
puts "Audit geschreven naar: $audit_tsv"
exit 0
