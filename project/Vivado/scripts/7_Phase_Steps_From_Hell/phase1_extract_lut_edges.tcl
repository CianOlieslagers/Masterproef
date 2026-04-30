# phase1_extract_lut_edges.tcl
#
# Doel:
#   FASE 1 — Extractie van LUT-output -> LUT-input interconnects
#   op de slechtste timing paths.
#
# Gebruik:
#   vivado -mode batch -source phase1_extract_lut_edges.tcl -tclargs \
#     <post_route.dcp> <output_dir> <max_paths> <nworst>
#
# Voorbeeld:
#   vivado -mode batch -source phase1_extract_lut_edges.tcl -tclargs \
#     ~/Masterproef/project/results/run_lut_insertion/2026-04-21_17-34-57/baseline_impl/checkpoints/post_route_timingexp.dcp \
#     ~/Masterproef/project/results/run_lut_insertion/2026-04-21_17-34-57/phase1_timing_edges \
#     10 10

proc json_escape {s} {
    set s [string map [list "\\" "\\\\" "\"" "\\\"" "\n" "\\n" "\r" "\\r" "\t" "\\t"] $s]
    return "\"$s\""
}

proc json_num_or_null {v} {
    if {[string is double -strict $v] || [string is integer -strict $v]} {
        return $v
    }
    return "null"
}

proc safe_get_property {prop obj {default ""}} {
    if {[catch {set v [get_property $prop $obj]}]} {
        return $default
    }
    if {$v eq ""} {
        return $default
    }
    return $v
}

proc obj_name {obj} {
    set n [safe_get_property NAME $obj ""]
    if {$n eq ""} {
        return [string trim $obj]
    }
    return $n
}

proc csv_escape {s} {
    set s [string trim $s]
    if {[regexp {[,\"\n\r]} $s]} {
        set s [string map [list "\"" "\"\""] $s]
        return "\"$s\""
    }
    return $s
}

proc is_simple_lut_cell {cell} {
    set ref [safe_get_property REF_NAME $cell ""]
    return [regexp {^LUT[1-6]$} $ref]
}

proc is_lut6_2_cell {cell} {
    set ref [safe_get_property REF_NAME $cell ""]
    return [expr {$ref eq "LUT6_2"}]
}

proc is_lut_output_pin {pin} {
    set refpin [safe_get_property REF_PIN_NAME $pin ""]
    return [expr {$refpin eq "O" || $refpin eq "O5" || $refpin eq "O6"}]
}

proc is_lut_input_pin {pin} {
    set refpin [safe_get_property REF_PIN_NAME $pin ""]
    return [regexp {^I[0-5]$} $refpin]
}

proc get_cell_site_name {cell} {
    if {![catch {set sites [get_sites -quiet -of_objects $cell]}]} {
        if {[llength $sites] > 0} {
            return [obj_name [lindex $sites 0]]
        }
    }
    return [safe_get_property LOC $cell ""]
}

proc is_control_like_net {net} {
    set net_name [string tolower [obj_name $net]]

    set is_clock [safe_get_property IS_CLOCK $net ""]
    if {$is_clock eq "1" || [string toupper $is_clock] eq "TRUE"} {
        return 1
    }

    # Conservatieve naamfilter. Dit is bewust niet te agressief.
    if {[regexp {(^|[/_])(clk|clock|rst|reset|clear)([/_\[\]0-9]|$)} $net_name]} {
        return 1
    }

    return 0
}

proc first_available_delay_property {delay_obj} {
    # Voor max/setup timing is SLOW_MAX de meest logische keuze.
    # Niet elke Vivado-versie exposeert exact dezelfde propertynamen,
    # daarom gebruiken we fallbacks.
    foreach prop {SLOW_MAX MAX DELAY FAST_MAX FAST_MIN SLOW_MIN} {
        if {![catch {set v [get_property $prop $delay_obj]}]} {
            if {[string is double -strict $v] || [string is integer -strict $v]} {
                return $v
            }
        }
    }
    return ""
}

proc get_interconnect_delay_ps {net sink_pin} {
    if {[catch {
        set delay_objs [get_net_delays -quiet -of_objects $net -to $sink_pin -interconnect_only]
    }]} {
        return ""
    }

    if {[llength $delay_objs] == 0} {
        return ""
    }

    set d [first_available_delay_property [lindex $delay_objs 0]]
    return $d
}

proc parse_logic_route_from_report_timing {path} {
    set result [dict create total "" logic "" route ""]

    if {[catch {
        set txt [report_timing -quiet -return_string -of_objects $path -path_type full]
    }]} {
        return $result
    }

    if {[regexp {Data Path Delay:\s+([0-9.+-]+)ns\s+\(logic\s+([0-9.+-]+)ns.*route\s+([0-9.+-]+)ns} $txt -> total logic route]} {
        dict set result total $total
        dict set result logic $logic
        dict set result route $route
    }

    return $result
}

proc dict_get_default {d key default} {
    if {[dict exists $d $key]} {
        return [dict get $d $key]
    }
    return $default
}

proc compare_candidate_delay_desc {a b} {
    set da [dict_get_default $a interconnect_delay_ps -1]
    set db [dict_get_default $b interconnect_delay_ps -1]

    if {$da eq ""} { set da -1 }
    if {$db eq ""} { set db -1 }

    if {$da > $db} { return -1 }
    if {$da < $db} { return 1 }

    set sa [dict_get_default $a path_slack_ns 999999]
    set sb [dict_get_default $b path_slack_ns 999999]

    if {$sa < $sb} { return -1 }
    if {$sa > $sb} { return 1 }

    return 0
}

proc write_candidate_json {fh cand indent comma_after} {
    set numeric_fields {
        path_index
        path_slack_ns
        path_datapath_delay_ns
        path_logic_delay_ns
        path_route_delay_ns
        path_route_delay_from_netdelays_ns
        fanout
        interconnect_delay_ps
    }

    set fields {
        path_index
        path_slack_ns
        path_datapath_delay_ns
        path_logic_delay_ns
        path_route_delay_ns
        path_route_delay_from_netdelays_ns
        source_cell
        source_ref
        source_pin
        source_ref_pin
        sink_cell
        sink_ref
        sink_pin
        sink_ref_pin
        net
        fanout
        interconnect_delay_ps
        source_loc
        source_bel
        source_site
        sink_loc
        sink_bel
        sink_site
    }

    puts $fh "${indent}{"

    set n [llength $fields]
    for {set i 0} {$i < $n} {incr i} {
        set key [lindex $fields $i]
        set raw [dict_get_default $cand $key ""]

        if {[lsearch -exact $numeric_fields $key] >= 0} {
            set val [json_num_or_null $raw]
        } else {
            set val [json_escape $raw]
        }

        set comma ","
        if {$i == [expr {$n - 1}]} {
            set comma ""
        }

        puts $fh "${indent}  \"${key}\": ${val}${comma}"
    }

    puts $fh "${indent}}${comma_after}"
}

# -------------------------
# Argument parsing
# -------------------------

if {[llength $argv] < 1} {
    puts "ERROR: usage: vivado -mode batch -source phase1_extract_lut_edges.tcl -tclargs <dcp> <out_dir> <max_paths> <nworst>"
    exit 1
}

set baseline_dcp [file normalize [lindex $argv 0]]

if {[llength $argv] >= 2} {
    set out_dir [file normalize [lindex $argv 1]]
} else {
    set out_dir [file normalize "./phase1_timing_edges"]
}

if {[llength $argv] >= 3} {
    set max_paths [lindex $argv 2]
} else {
    set max_paths 10
}

if {[llength $argv] >= 4} {
    set nworst [lindex $argv 3]
} else {
    set nworst 10
}

file mkdir $out_dir

set out_json [file join $out_dir "phase1_lut_timing_edges.json"]
set out_csv  [file join $out_dir "phase1_lut_timing_edges.csv"]
set out_rpt  [file join $out_dir "phase1_timing_paths.rpt"]
set out_log  [file join $out_dir "phase1_extract.log"]

set logfh [open $out_log w]

puts $logfh "FASE 1 extractie gestart"
puts $logfh "baseline_dcp = $baseline_dcp"
puts $logfh "out_dir      = $out_dir"
puts $logfh "max_paths    = $max_paths"
puts $logfh "nworst       = $nworst"

if {![file exists $baseline_dcp]} {
    puts $logfh "ERROR: DCP bestaat niet: $baseline_dcp"
    close $logfh
    exit 1
}

open_checkpoint $baseline_dcp

set part ""
if {![catch {set part [current_part]}]} {
    # ok
} else {
    set part [safe_get_property PART [current_design] ""]
}

puts $logfh "part = $part"

# Timing paths ophalen.
# -setup = max delay paths.
# -no_report_unconstrained voorkomt dat unconstrained paths meedoen.
set paths [get_timing_paths -setup -max_paths $max_paths -nworst $nworst -sort_by slack -no_report_unconstrained]

set num_paths [llength $paths]
puts $logfh "num_timing_paths = $num_paths"

if {$num_paths == 0} {
    puts $logfh "ERROR: geen constrained setup timing paths gevonden."
    close $logfh
    exit 2
}

# Bewijsrapport schrijven.
report_timing -of_objects $paths -path_type full -file $out_rpt -append

set all_candidates {}

set path_index 0
foreach path $paths {
    incr path_index

    set path_slack [safe_get_property SLACK $path ""]
    set path_datapath [safe_get_property DATAPATH_DELAY $path ""]
    set parsed [parse_logic_route_from_report_timing $path]

    set path_total_from_report [dict get $parsed total]
    set path_logic [dict get $parsed logic]
    set path_route [dict get $parsed route]

    if {$path_datapath eq "" && $path_total_from_report ne ""} {
        set path_datapath $path_total_from_report
    }

    puts $logfh "PATH $path_index: slack=$path_slack ns datapath=$path_datapath ns logic=$path_logic ns route=$path_route ns"

    # Alle pins en nets op dit timing path.
    set path_pin_names {}
    foreach p [get_pins -quiet -of_objects $path] {
        lappend path_pin_names [obj_name $p]
    }

    set path_nets [get_nets -quiet -of_objects $path]

    set path_route_sum_ps 0.0

    foreach net $path_nets {
        if {[is_control_like_net $net]} {
            continue
        }

        set net_name [obj_name $net]

        set drivers [get_pins -quiet -of_objects $net -filter {DIRECTION == OUT}]
        set loads   [get_pins -quiet -of_objects $net -filter {DIRECTION == IN}]

        # Voor deze fase willen we eenvoudige, eenduidige netten.
        if {[llength $drivers] != 1} {
            continue
        }

        set driver_pin [lindex $drivers 0]
        set driver_pin_name [obj_name $driver_pin]

        # Driver moet effectief op het timing path liggen.
        if {[lsearch -exact $path_pin_names $driver_pin_name] < 0} {
            continue
        }

        set driver_cells [get_cells -quiet -of_objects $driver_pin]
        if {[llength $driver_cells] != 1} {
            continue
        }

        set source_cell [lindex $driver_cells 0]

        # Eerste versie: alleen gewone LUT1-LUT6, geen LUT6_2.
        if {![is_simple_lut_cell $source_cell]} {
            continue
        }
        if {[is_lut6_2_cell $source_cell]} {
            continue
        }
        if {![is_lut_output_pin $driver_pin]} {
            continue
        }

        foreach load_pin $loads {
            set load_pin_name [obj_name $load_pin]

            # Alleen de load die effectief op dit timing path zit.
            if {[lsearch -exact $path_pin_names $load_pin_name] < 0} {
                continue
            }

            set sink_cells [get_cells -quiet -of_objects $load_pin]
            if {[llength $sink_cells] != 1} {
                continue
            }

            set sink_cell [lindex $sink_cells 0]

            # Eerste versie: alleen gewone LUT1-LUT6, geen LUT6_2.
            if {![is_simple_lut_cell $sink_cell]} {
                continue
            }
            if {[is_lut6_2_cell $sink_cell]} {
                continue
            }
            if {![is_lut_input_pin $load_pin]} {
                continue
            }

            set delay_ps [get_interconnect_delay_ps $net $load_pin]

            # FASE 1 eist niet-nul interconnect delay.
            if {$delay_ps eq ""} {
                continue
            }
            if {![string is double -strict $delay_ps] && ![string is integer -strict $delay_ps]} {
                continue
            }
            if {$delay_ps <= 0} {
                continue
            }

            set path_route_sum_ps [expr {$path_route_sum_ps + $delay_ps}]

            set fanout [llength $loads]

            set cand [dict create \
                path_index $path_index \
                path_slack_ns $path_slack \
                path_datapath_delay_ns $path_datapath \
                path_logic_delay_ns $path_logic \
                path_route_delay_ns $path_route \
                path_route_delay_from_netdelays_ns [expr {$path_route_sum_ps / 1000.0}] \
                source_cell [obj_name $source_cell] \
                source_ref [safe_get_property REF_NAME $source_cell ""] \
                source_pin $driver_pin_name \
                source_ref_pin [safe_get_property REF_PIN_NAME $driver_pin ""] \
                sink_cell [obj_name $sink_cell] \
                sink_ref [safe_get_property REF_NAME $sink_cell ""] \
                sink_pin $load_pin_name \
                sink_ref_pin [safe_get_property REF_PIN_NAME $load_pin ""] \
                net $net_name \
                fanout $fanout \
                interconnect_delay_ps $delay_ps \
                source_loc [safe_get_property LOC $source_cell ""] \
                source_bel [safe_get_property BEL $source_cell ""] \
                source_site [get_cell_site_name $source_cell] \
                sink_loc [safe_get_property LOC $sink_cell ""] \
                sink_bel [safe_get_property BEL $sink_cell ""] \
                sink_site [get_cell_site_name $sink_cell] \
            ]

            lappend all_candidates $cand
        }
    }
}

set num_candidates [llength $all_candidates]
puts $logfh "num_lut_to_lut_candidates = $num_candidates"

if {$num_candidates == 0} {
    puts $logfh "ERROR: geen LUT-output -> LUT-input kandidaten gevonden op de geselecteerde timing paths."
}

set sorted_candidates [lsort -command compare_candidate_delay_desc $all_candidates]

if {$num_candidates > 0} {
    set selected [lindex $sorted_candidates 0]
} else {
    set selected [dict create]
}

# CSV schrijven.
set csvfh [open $out_csv w]
puts $csvfh "rank,path_index,path_slack_ns,path_datapath_delay_ns,path_logic_delay_ns,path_route_delay_ns,source_cell,source_ref,source_pin,source_ref_pin,sink_cell,sink_ref,sink_pin,sink_ref_pin,net,fanout,interconnect_delay_ps,source_loc,source_bel,source_site,sink_loc,sink_bel,sink_site"

set rank 0
foreach cand $sorted_candidates {
    incr rank
    set row [list \
        $rank \
        [dict_get_default $cand path_index ""] \
        [dict_get_default $cand path_slack_ns ""] \
        [dict_get_default $cand path_datapath_delay_ns ""] \
        [dict_get_default $cand path_logic_delay_ns ""] \
        [dict_get_default $cand path_route_delay_ns ""] \
        [dict_get_default $cand source_cell ""] \
        [dict_get_default $cand source_ref ""] \
        [dict_get_default $cand source_pin ""] \
        [dict_get_default $cand source_ref_pin ""] \
        [dict_get_default $cand sink_cell ""] \
        [dict_get_default $cand sink_ref ""] \
        [dict_get_default $cand sink_pin ""] \
        [dict_get_default $cand sink_ref_pin ""] \
        [dict_get_default $cand net ""] \
        [dict_get_default $cand fanout ""] \
        [dict_get_default $cand interconnect_delay_ps ""] \
        [dict_get_default $cand source_loc ""] \
        [dict_get_default $cand source_bel ""] \
        [dict_get_default $cand source_site ""] \
        [dict_get_default $cand sink_loc ""] \
        [dict_get_default $cand sink_bel ""] \
        [dict_get_default $cand sink_site ""] \
    ]

    set escaped {}
    foreach item $row {
        lappend escaped [csv_escape $item]
    }
    puts $csvfh [join $escaped ","]
}
close $csvfh

# JSON schrijven.
set jsonfh [open $out_json w]

puts $jsonfh "{"
puts $jsonfh "  \"phase\": \"FASE 1\","
puts $jsonfh "  \"phase1_status\": [json_escape [expr {$num_candidates > 0 ? "PASS" : "FAIL"}]],"
puts $jsonfh "  \"baseline_dcp\": [json_escape $baseline_dcp],"
puts $jsonfh "  \"part\": [json_escape $part],"
puts $jsonfh "  \"num_timing_paths\": [json_num_or_null $num_paths],"
puts $jsonfh "  \"num_lut_to_lut_candidates\": [json_num_or_null $num_candidates],"

if {$num_candidates > 0} {
    puts $jsonfh {  "selected_edge":}
    write_candidate_json $jsonfh $selected "  " ","
} else {
    puts $jsonfh {  "selected_edge": null,}
}

# Belangrijk:
# Gebruik braces {...} voor deze regel, want '[' heeft speciale betekenis in Tcl.
puts $jsonfh {  "candidates": [}

set n [llength $sorted_candidates]
for {set i 0} {$i < $n} {incr i} {
    set cand [lindex $sorted_candidates $i]

    set comma ","
    if {$i == [expr {$n - 1}]} {
        set comma ""
    }

    write_candidate_json $jsonfh $cand "    " $comma
}

puts $jsonfh {  ]}
puts $jsonfh "}"

close $jsonfh
puts $logfh "json geschreven: $out_json"
puts $logfh "csv geschreven : $out_csv"
puts $logfh "rpt geschreven : $out_rpt"

close $logfh

if {$num_candidates == 0} {
    puts "PHASE1_FAIL: geen geldige LUT-to-LUT kandidaat gevonden."
    puts "Zie log: $out_log"
    exit 3
}

puts "PHASE1_PASS: $num_candidates geldige LUT-to-LUT kandidaat/kandidaten gevonden."
puts "Output JSON: $out_json"
puts "Output CSV : $out_csv"
puts "Timing RPT : $out_rpt"
puts "Beste kandidaat:"
puts "  source = [dict get $selected source_cell] / [dict get $selected source_ref_pin]"
puts "  sink   = [dict get $selected sink_cell] / [dict get $selected sink_ref_pin]"
puts "  net    = [dict get $selected net]"
puts "  delay  = [dict get $selected interconnect_delay_ps] ps"
