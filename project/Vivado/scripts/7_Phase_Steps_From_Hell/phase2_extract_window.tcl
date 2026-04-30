# phase2_extract_window.tcl
#
# FASE 2 — Klein edge-based window bepalen rond de selected LUT-to-LUT edge.
#
# Gebruik:
#   vivado -mode batch -source phase2_extract_window.tcl -tclargs \
#     <post_route.dcp> <phase1_lut_timing_edges.json> <out_dir> \
#     <max_luts> <max_boundary_inputs> <max_boundary_outputs>
#
# Voorbeeld:
#   vivado -mode batch -source phase2_extract_window.tcl -tclargs \
#     ~/Masterproef/project/results/run_lut_insertion/2026-04-21_17-34-57/baseline_impl/checkpoints/post_route_timingexp.dcp \
#     ~/Masterproef/project/results/run_lut_insertion/2026-04-21_17-34-57/phase1_timing_edges/phase1_lut_timing_edges.json \
#     ~/Masterproef/project/results/run_lut_insertion/2026-04-21_17-34-57/phase2_window \
#     5 12 2

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

proc json_bool {v} {
    if {$v} {
        return "true"
    }
    return "false"
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

proc write_csv_row {fh fields} {
    set escaped {}
    foreach item $fields {
        lappend escaped [csv_escape $item]
    }
    puts $fh [join $escaped ","]
}

proc read_file {path} {
    set fh [open $path r]
    set txt [read $fh]
    close $fh
    return $txt
}

proc extract_json_string {txt key} {
    set pattern [format {"%s"[ \t\r\n]*:[ \t\r\n]*"([^"]*)"} $key]
    if {[regexp $pattern $txt -> val]} {
        return $val
    }
    return ""
}

proc extract_json_number {txt key} {
    set pattern [format {"%s"[ \t\r\n]*:[ \t\r\n]*([-0-9.]+)} $key]
    if {[regexp $pattern $txt -> val]} {
        return $val
    }
    return ""
}

proc is_simple_lut_cell {cell} {
    set ref [safe_get_property REF_NAME $cell ""]
    return [regexp {^LUT[1-6]$} $ref]
}

proc is_lut6_2_cell {cell} {
    set ref [safe_get_property REF_NAME $cell ""]
    return [expr {$ref eq "LUT6_2"}]
}

proc is_forbidden_cell_type {cell} {
    set ref [safe_get_property REF_NAME $cell ""]
    if {[regexp {CARRY|DSP|RAMB|BRAM|SRL|RAMD|RAMS|FDRE|FDSE|FDCE|FDPE|LATCH} $ref]} {
        return 1
    }
    return 0
}

proc is_lut_input_pin {pin} {
    set refpin [safe_get_property REF_PIN_NAME $pin ""]
    return [regexp {^I[0-5]$} $refpin]
}

proc is_lut_output_pin {pin} {
    set refpin [safe_get_property REF_PIN_NAME $pin ""]
    return [expr {$refpin eq "O" || $refpin eq "O5" || $refpin eq "O6"}]
}

proc get_cell_site_name {cell} {
    if {![catch {set sites [get_sites -quiet -of_objects $cell]}]} {
        if {[llength $sites] > 0} {
            return [obj_name [lindex $sites 0]]
        }
    }
    return [safe_get_property LOC $cell ""]
}

proc site_xy {site_name} {
    if {[regexp {X([0-9]+)Y([0-9]+)} $site_name -> x y]} {
        return [list $x $y]
    }
    return [list "" ""]
}

proc manhattan_between_sites {site_a site_b} {
    set xy_a [site_xy $site_a]
    set xy_b [site_xy $site_b]

    set ax [lindex $xy_a 0]
    set ay [lindex $xy_a 1]
    set bx [lindex $xy_b 0]
    set by [lindex $xy_b 1]

    if {$ax eq "" || $ay eq "" || $bx eq "" || $by eq ""} {
        return ""
    }

    return [expr {abs($ax - $bx) + abs($ay - $by)}]
}

proc get_input_pins_sorted {cell} {
    set pins [get_pins -quiet -of_objects $cell -filter {DIRECTION == IN}]
    set lut_inputs {}

    foreach p $pins {
        if {[is_lut_input_pin $p]} {
            lappend lut_inputs $p
        }
    }

    return [lsort -command compare_pin_ref_name $lut_inputs]
}

proc compare_pin_ref_name {a b} {
    set ra [safe_get_property REF_PIN_NAME $a ""]
    set rb [safe_get_property REF_PIN_NAME $b ""]
    return [string compare $ra $rb]
}

proc get_output_pins_sorted {cell} {
    set pins [get_pins -quiet -of_objects $cell -filter {DIRECTION == OUT}]
    set outs {}

    foreach p $pins {
        if {[is_lut_output_pin $p]} {
            lappend outs $p
        }
    }

    return [lsort -command compare_pin_ref_name $outs]
}

proc get_pin_net_obj {pin} {
    set nets [get_nets -quiet -of_objects $pin]
    if {[llength $nets] == 0} {
        return ""
    }
    return [lindex $nets 0]
}

proc get_driver_pin_of_net {net} {
    set drivers [get_pins -quiet -of_objects $net -filter {DIRECTION == OUT}]
    if {[llength $drivers] == 1} {
        return [lindex $drivers 0]
    }
    return ""
}

proc get_driver_cell_of_net {net} {
    set dp [get_driver_pin_of_net $net]
    if {$dp eq ""} {
        return ""
    }
    set cells [get_cells -quiet -of_objects $dp]
    if {[llength $cells] == 1} {
        return [lindex $cells 0]
    }
    return ""
}

proc get_driver_kind_and_name {net} {
    set dp [get_driver_pin_of_net $net]
    if {$dp ne ""} {
        set cells [get_cells -quiet -of_objects $dp]
        if {[llength $cells] == 1} {
            return [list "CELL" [obj_name [lindex $cells 0]] [obj_name $dp] ""]
        }
    }

    set ports [get_ports -quiet -of_objects $net -filter {DIRECTION == IN}]
    if {[llength $ports] > 0} {
        return [list "PORT" "" "" [obj_name [lindex $ports 0]]]
    }

    set net_type [safe_get_property TYPE $net ""]
    set nname [obj_name $net]
    if {[regexp -nocase {const|gnd|vcc} $nname] || [regexp -nocase {POWER|GROUND} $net_type]} {
        return [list "CONST" "" "" ""]
    }

    return [list "UNKNOWN" "" "" ""]
}

proc first_available_delay_property {delay_obj} {
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

    return [first_available_delay_property [lindex $delay_objs 0]]
}

proc list_contains {lst item} {
    return [expr {[lsearch -exact $lst $item] >= 0}]
}

proc add_unique {lst item} {
    if {![list_contains $lst $item]} {
        lappend lst $item
    }
    return $lst
}

proc check_acyclic {cell_names internal_edges} {
    array set indeg {}
    array set adj {}

    foreach c $cell_names {
        set indeg($c) 0
        set adj($c) {}
    }

    foreach e $internal_edges {
        set src [dict get $e source_cell]
        set dst [dict get $e sink_cell]

        if {$src eq $dst} {
            return 0
        }

        if {![info exists indeg($src)] || ![info exists indeg($dst)]} {
            continue
        }

        lappend adj($src) $dst
        incr indeg($dst)
    }

    set q {}
    foreach c $cell_names {
        if {$indeg($c) == 0} {
            lappend q $c
        }
    }

    set visited 0
    while {[llength $q] > 0} {
        set n [lindex $q 0]
        set q [lrange $q 1 end]
        incr visited

        foreach m $adj($n) {
            incr indeg($m) -1
            if {$indeg($m) == 0} {
                lappend q $m
            }
        }
    }

    return [expr {$visited == [llength $cell_names]}]
}


proc compute_window_metrics {cell_names} {
    array set in_window {}
    foreach cname $cell_names {
        set in_window($cname) 1
    }

    set internal_edges {}
    array set boundary_input_seen {}
    set boundary_inputs {}
    array set boundary_output_seen {}
    set boundary_outputs {}

    set contains_only_luts 1
    set contains_lut6_2 0
    set contains_forbidden 0

    foreach cname $cell_names {
        set cs [get_cells -quiet $cname]
        if {[llength $cs] != 1} {
            set contains_only_luts 0
            continue
        }

        set cell [lindex $cs 0]

        if {![is_simple_lut_cell $cell]} {
            set contains_only_luts 0
        }

        if {[is_lut6_2_cell $cell]} {
            set contains_lut6_2 1
        }

        if {[is_forbidden_cell_type $cell]} {
            set contains_forbidden 1
        }

        foreach inpin [get_input_pins_sorted $cell] {
            set net [get_pin_net_obj $inpin]

            if {$net eq ""} {
                set bkey "UNCONNECTED|[obj_name $inpin]"
                set boundary_input_seen($bkey) 1
                continue
            }

            set net_name [obj_name $net]
            set dcell [get_driver_cell_of_net $net]

            if {$dcell ne ""} {
                set dcell_name [obj_name $dcell]

                if {[info exists in_window($dcell_name)]} {
                    lappend internal_edges [dict create \
                        source_cell $dcell_name \
                        sink_cell $cname \
                    ]
                } else {
                    set boundary_input_seen($net_name) 1
                }
            } else {
                set boundary_input_seen($net_name) 1
            }
        }
    }

    foreach cname $cell_names {
        set cs [get_cells -quiet $cname]
        if {[llength $cs] != 1} {
            continue
        }

        set cell [lindex $cs 0]

        foreach outpin [get_output_pins_sorted $cell] {
            set net [get_pin_net_obj $outpin]
            if {$net eq ""} {
                continue
            }

            set net_name [obj_name $net]
            set loads [get_pins -quiet -of_objects $net -filter {DIRECTION == IN}]

            foreach lp $loads {
                set lcells [get_cells -quiet -of_objects $lp]
                if {[llength $lcells] != 1} {
                    continue
                }

                set lc [lindex $lcells 0]
                set lname [obj_name $lc]

                if {![info exists in_window($lname)]} {
                    set key "$cname|[obj_name $outpin]|$net_name"
                    set boundary_output_seen($key) 1
                }
            }

            set ports [get_ports -quiet -of_objects $net -filter {DIRECTION == OUT}]
            if {[llength $ports] > 0} {
                set key "$cname|[obj_name $outpin]|$net_name|PORT"
                set boundary_output_seen($key) 1
            }
        }
    }

    foreach k [array names boundary_input_seen] {
        lappend boundary_inputs $k
    }

    foreach k [array names boundary_output_seen] {
        lappend boundary_outputs $k
    }

    set acyclic [check_acyclic $cell_names $internal_edges]

    return [dict create \
        num_luts [llength $cell_names] \
        num_internal_edges [llength $internal_edges] \
        num_boundary_inputs [llength $boundary_inputs] \
        num_boundary_outputs [llength $boundary_outputs] \
        contains_only_luts $contains_only_luts \
        contains_lut6_2 $contains_lut6_2 \
        contains_forbidden $contains_forbidden \
        acyclic $acyclic \
    ]
}


proc get_fanin_lut_candidates {cell_names} {
    array set in_window {}
    foreach cname $cell_names {
        set in_window($cname) 1
    }

    set candidates {}

    foreach cname $cell_names {
        set cs [get_cells -quiet $cname]
        if {[llength $cs] != 1} {
            continue
        }

        set cell [lindex $cs 0]

        foreach inpin [get_input_pins_sorted $cell] {
            set net [get_pin_net_obj $inpin]
            if {$net eq ""} {
                continue
            }

            set dcell [get_driver_cell_of_net $net]
            if {$dcell eq ""} {
                continue
            }

            set dname [obj_name $dcell]

            if {[info exists in_window($dname)]} {
                continue
            }

            if {![is_simple_lut_cell $dcell]} {
                continue
            }

            if {[is_lut6_2_cell $dcell]} {
                continue
            }

            if {[is_forbidden_cell_type $dcell]} {
                continue
            }

            set candidates [add_unique $candidates $dname]
        }
    }

    return [lsort $candidates]
}


proc metric_value {metrics key} {
    if {[dict exists $metrics $key]} {
        return [dict get $metrics $key]
    }
    return ""
}


proc write_object_json {fh d fields numeric_fields bool_fields indent comma_after} {
    puts $fh "${indent}{"

    set n [llength $fields]
    for {set i 0} {$i < $n} {incr i} {
        set key [lindex $fields $i]

        if {[dict exists $d $key]} {
            set raw [dict get $d $key]
        } else {
            set raw ""
        }

        if {[lsearch -exact $numeric_fields $key] >= 0} {
            set val [json_num_or_null $raw]
        } elseif {[lsearch -exact $bool_fields $key] >= 0} {
            set val [json_bool $raw]
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

proc write_array_json {fh name items fields numeric_fields bool_fields indent comma_after} {
    puts $fh "${indent}\"${name}\": \["

    set n [llength $items]
    for {set i 0} {$i < $n} {incr i} {
        set item [lindex $items $i]
        set comma ","
        if {$i == [expr {$n - 1}]} {
            set comma ""
        }
        write_object_json $fh $item $fields $numeric_fields $bool_fields "${indent}  " $comma
    }

    puts $fh "${indent}\]${comma_after}"
}

proc add_validation {validations_var check status detail} {
    upvar $validations_var validations
    lappend validations [dict create check $check status $status detail $detail]
}

# -------------------------
# Argument parsing
# -------------------------

if {[llength $argv] < 3} {
    puts "ERROR: usage: vivado -mode batch -source phase2_extract_window.tcl -tclargs <dcp> <phase1_json> <out_dir> <max_luts> <max_boundary_inputs> <max_boundary_outputs>"
    exit 1
}

set baseline_dcp [file normalize [lindex $argv 0]]
set phase1_json  [file normalize [lindex $argv 1]]
set out_dir      [file normalize [lindex $argv 2]]

if {[llength $argv] >= 4} {
    set max_luts [lindex $argv 3]
} else {
    set max_luts 5
}

if {[llength $argv] >= 5} {
    set max_boundary_inputs [lindex $argv 4]
} else {
    set max_boundary_inputs 12
}

if {[llength $argv] >= 6} {
    set max_boundary_outputs [lindex $argv 5]
} else {
    set max_boundary_outputs 2
}

if {[llength $argv] >= 7} {
    set window_mode [lindex $argv 6]
} else {
    set window_mode "sink_direct_fanin"
}

if {[llength $argv] >= 8} {
    set target_luts [lindex $argv 7]
} else {
    set target_luts $max_luts
}

if {[llength $argv] >= 9} {
    set max_growth_iterations [lindex $argv 8]
} else {
    set max_growth_iterations 50
}




file mkdir $out_dir

set out_summary [file join $out_dir "phase2_window_summary.txt"]
set out_json    [file join $out_dir "phase2_window.json"]
set out_luts    [file join $out_dir "window_luts.csv"]
set out_edges   [file join $out_dir "internal_edges.csv"]
set out_bin     [file join $out_dir "boundary_inputs.csv"]
set out_binc    [file join $out_dir "boundary_input_connections.csv"]
set out_bout    [file join $out_dir "boundary_outputs.csv"]
set out_checks  [file join $out_dir "validation_checks.csv"]
set out_dot     [file join $out_dir "window_graph.dot"]
set out_growth  [file join $out_dir "growth_trace.csv"]
set out_log     [file join $out_dir "phase2_extract.log"]

set logfh [open $out_log w]

puts $logfh "FASE 2 windowextractie gestart"
puts $logfh "baseline_dcp = $baseline_dcp"
puts $logfh "phase1_json  = $phase1_json"
puts $logfh "out_dir      = $out_dir"
puts $logfh "max_luts = $max_luts"
puts $logfh "max_boundary_inputs = $max_boundary_inputs"
puts $logfh "max_boundary_outputs = $max_boundary_outputs"
puts $logfh "window_mode = $window_mode"
puts $logfh "target_luts = $target_luts"
puts $logfh "max_growth_iterations = $max_growth_iterations"
puts $logfh "growth trace csv: $out_growth"

if {![file exists $baseline_dcp]} {
    puts $logfh "ERROR: DCP bestaat niet"
    close $logfh
    exit 1
}

if {![file exists $phase1_json]} {
    puts $logfh "ERROR: phase1 JSON bestaat niet"
    close $logfh
    exit 1
}

set p1txt [read_file $phase1_json]

set source_cell_name [extract_json_string $p1txt "source_cell"]
set source_pin_name  [extract_json_string $p1txt "source_pin"]
set sink_cell_name   [extract_json_string $p1txt "sink_cell"]
set sink_pin_name    [extract_json_string $p1txt "sink_pin"]
set selected_net_name [extract_json_string $p1txt "net"]
set selected_delay_ps [extract_json_number $p1txt "interconnect_delay_ps"]

puts $logfh "selected source_cell = $source_cell_name"
puts $logfh "selected source_pin  = $source_pin_name"
puts $logfh "selected sink_cell   = $sink_cell_name"
puts $logfh "selected sink_pin    = $sink_pin_name"
puts $logfh "selected net         = $selected_net_name"
puts $logfh "selected delay ps    = $selected_delay_ps"

open_checkpoint $baseline_dcp

set part ""
if {![catch {set part [current_part]}]} {
    # ok
}

set source_cells [get_cells -quiet $source_cell_name]
set sink_cells   [get_cells -quiet $sink_cell_name]

set validations {}

if {[llength $source_cells] != 1} {
    add_validation validations "source_cell_exists" "FAIL" "source_cell niet uniek of niet gevonden"
} else {
    add_validation validations "source_cell_exists" "PASS" $source_cell_name
}

if {[llength $sink_cells] != 1} {
    add_validation validations "sink_cell_exists" "FAIL" "sink_cell niet uniek of niet gevonden"
} else {
    add_validation validations "sink_cell_exists" "PASS" $sink_cell_name
}

if {[llength $source_cells] != 1 || [llength $sink_cells] != 1} {
    set summaryfh [open $out_summary w]
    puts $summaryfh "phase2_status=FAIL"
    puts $summaryfh "reason=source_or_sink_not_found"
    close $summaryfh
    close $logfh
    exit 2
}

set source_cell [lindex $source_cells 0]
set sink_cell [lindex $sink_cells 0]

if {[is_simple_lut_cell $source_cell]} {
    add_validation validations "source_is_simple_lut" "PASS" [safe_get_property REF_NAME $source_cell ""]
} else {
    add_validation validations "source_is_simple_lut" "FAIL" [safe_get_property REF_NAME $source_cell ""]
}

if {[is_simple_lut_cell $sink_cell]} {
    add_validation validations "sink_is_simple_lut" "PASS" [safe_get_property REF_NAME $sink_cell ""]
} else {
    add_validation validations "sink_is_simple_lut" "FAIL" [safe_get_property REF_NAME $sink_cell ""]
}
# -------------------------
# Window construction
# -------------------------

set growth_trace {}

set window_cell_names {}
set window_cell_names [add_unique $window_cell_names [obj_name $source_cell]]
set window_cell_names [add_unique $window_cell_names [obj_name $sink_cell]]

lappend growth_trace [dict create \
    iteration 0 \
    candidate_cell "" \
    action "INIT" \
    reason "source_plus_sink" \
    num_luts_after [llength $window_cell_names] \
    num_boundary_inputs_after "" \
    num_boundary_outputs_after "" \
    acyclic_after "" \
]

if {$window_mode eq "sink_direct_fanin"} {

    foreach inpin [get_input_pins_sorted $sink_cell] {
        set net [get_pin_net_obj $inpin]
        if {$net eq ""} {
            continue
        }

        set dcell [get_driver_cell_of_net $net]
        if {$dcell eq ""} {
            continue
        }

        if {[is_simple_lut_cell $dcell] && ![is_lut6_2_cell $dcell] && ![is_forbidden_cell_type $dcell]} {
            set cand_name [obj_name $dcell]
            set proposed [add_unique $window_cell_names $cand_name]
            set metrics [compute_window_metrics $proposed]

            set action "ACCEPT"
            set reason "sink_direct_fanin"

            if {[metric_value $metrics num_luts] > $max_luts} {
                set action "REJECT"
                set reason "max_luts"
            } elseif {[metric_value $metrics num_boundary_inputs] > $max_boundary_inputs} {
                set action "REJECT"
                set reason "max_boundary_inputs"
            } elseif {[metric_value $metrics num_boundary_outputs] > $max_boundary_outputs} {
                set action "REJECT"
                set reason "max_boundary_outputs"
            } elseif {![metric_value $metrics acyclic]} {
                set action "REJECT"
                set reason "cycle"
            }

            if {$action eq "ACCEPT"} {
                set window_cell_names $proposed
            }

            lappend growth_trace [dict create \
                iteration 1 \
                candidate_cell $cand_name \
                action $action \
                reason $reason \
                num_luts_after [metric_value $metrics num_luts] \
                num_boundary_inputs_after [metric_value $metrics num_boundary_inputs] \
                num_boundary_outputs_after [metric_value $metrics num_boundary_outputs] \
                acyclic_after [metric_value $metrics acyclic] \
            ]
        }
    }

} elseif {$window_mode eq "grow_fanin"} {

    for {set iter 1} {$iter <= $max_growth_iterations} {incr iter} {
        if {[llength $window_cell_names] >= $target_luts} {
            lappend growth_trace [dict create \
                iteration $iter \
                candidate_cell "" \
                action "STOP" \
                reason "target_luts_reached" \
                num_luts_after [llength $window_cell_names] \
                num_boundary_inputs_after "" \
                num_boundary_outputs_after "" \
                acyclic_after "" \
            ]
            break
        }

        set candidates [get_fanin_lut_candidates $window_cell_names]

        if {[llength $candidates] == 0} {
            lappend growth_trace [dict create \
                iteration $iter \
                candidate_cell "" \
                action "STOP" \
                reason "no_more_fanin_lut_candidates" \
                num_luts_after [llength $window_cell_names] \
                num_boundary_inputs_after "" \
                num_boundary_outputs_after "" \
                acyclic_after "" \
            ]
            break
        }

        set accepted_this_iter 0

        foreach cand_name $candidates {
            set proposed [add_unique $window_cell_names $cand_name]
            set metrics [compute_window_metrics $proposed]

            set action "ACCEPT"
            set reason "grow_fanin"

            if {[metric_value $metrics num_luts] > $max_luts} {
                set action "REJECT"
                set reason "max_luts"
            } elseif {[metric_value $metrics num_boundary_inputs] > $max_boundary_inputs} {
                set action "REJECT"
                set reason "max_boundary_inputs"
            } elseif {[metric_value $metrics num_boundary_outputs] > $max_boundary_outputs} {
                set action "REJECT"
                set reason "max_boundary_outputs"
            } elseif {![metric_value $metrics contains_only_luts]} {
                set action "REJECT"
                set reason "non_lut"
            } elseif {[metric_value $metrics contains_lut6_2]} {
                set action "REJECT"
                set reason "lut6_2"
            } elseif {[metric_value $metrics contains_forbidden]} {
                set action "REJECT"
                set reason "forbidden"
            } elseif {![metric_value $metrics acyclic]} {
                set action "REJECT"
                set reason "cycle"
            }

            lappend growth_trace [dict create \
                iteration $iter \
                candidate_cell $cand_name \
                action $action \
                reason $reason \
                num_luts_after [metric_value $metrics num_luts] \
                num_boundary_inputs_after [metric_value $metrics num_boundary_inputs] \
                num_boundary_outputs_after [metric_value $metrics num_boundary_outputs] \
                acyclic_after [metric_value $metrics acyclic] \
            ]

            if {$action eq "ACCEPT"} {
                set window_cell_names $proposed
                set accepted_this_iter 1
                break
            }
        }

        if {!$accepted_this_iter} {
            lappend growth_trace [dict create \
                iteration $iter \
                candidate_cell "" \
                action "STOP" \
                reason "all_candidates_rejected" \
                num_luts_after [llength $window_cell_names] \
                num_boundary_inputs_after "" \
                num_boundary_outputs_after "" \
                acyclic_after "" \
            ]
            break
        }
    }

} else {
    puts $logfh "ERROR: unknown window_mode=$window_mode"
    close $logfh
    exit 3
}

puts $logfh "window cells after construction mode=$window_mode:"
foreach c $window_cell_names {
    puts $logfh "  $c"
}

# Objecten van windowcellen.
set window_cells {}
foreach cname $window_cell_names {
    set cs [get_cells -quiet $cname]
    if {[llength $cs] == 1} {
        lappend window_cells [lindex $cs 0]
    }
}

# Lookup set.
array set in_window {}
foreach cname $window_cell_names {
    set in_window($cname) 1
}

# -------------------------
# Extract LUT metadata
# -------------------------

set lut_items {}
set contains_only_luts 1
set contains_lut6_2 0
set contains_forbidden 0

foreach c $window_cells {
    set cname [obj_name $c]
    set ref [safe_get_property REF_NAME $c ""]
    set site [get_cell_site_name $c]
    set xy [site_xy $site]

    if {![is_simple_lut_cell $c]} {
        set contains_only_luts 0
    }

    if {[is_lut6_2_cell $c]} {
        set contains_lut6_2 1
    }

    if {[is_forbidden_cell_type $c]} {
        set contains_forbidden 1
    }

    set init [safe_get_property INIT $c ""]
    set outs [get_output_pins_sorted $c]
    set out_pin ""
    set fanout 0

    if {[llength $outs] > 0} {
        set out_pin [obj_name [lindex $outs 0]]
        set n [get_pin_net_obj [lindex $outs 0]]
        if {$n ne ""} {
            set fanout [llength [get_pins -quiet -of_objects $n -filter {DIRECTION == IN}]]
        }
    }

    set item [dict create \
        cell $cname \
        ref $ref \
        loc [safe_get_property LOC $c ""] \
        bel [safe_get_property BEL $c ""] \
        site $site \
        site_x [lindex $xy 0] \
        site_y [lindex $xy 1] \
        init $init \
        is_source [expr {$cname eq $source_cell_name}] \
        is_sink [expr {$cname eq $sink_cell_name}] \
        input_count [llength [get_input_pins_sorted $c]] \
        output_pin $out_pin \
        fanout $fanout \
    ]

    lappend lut_items $item
}

# -------------------------
# Internal edges and boundary inputs
# -------------------------

set internal_edges {}
set boundary_input_connections {}
array set boundary_input_seen {}
set boundary_inputs {}
set boundary_index_counter 0

foreach dst_cell $window_cells {
    set dst_name [obj_name $dst_cell]

    foreach inpin [get_input_pins_sorted $dst_cell] {
        set net [get_pin_net_obj $inpin]
        if {$net eq ""} {
            set bkey "UNCONNECTED|[obj_name $inpin]"
            if {![info exists boundary_input_seen($bkey)]} {
                incr boundary_index_counter
                set boundary_input_seen($bkey) $boundary_index_counter
                lappend boundary_inputs [dict create \
                    boundary_index $boundary_index_counter \
                    net "" \
                    driver_kind "UNCONNECTED" \
                    driver_cell "" \
                    driver_pin "" \
                    driver_port "" \
                    connection_count 1 \
                ]
            }

            lappend boundary_input_connections [dict create \
                boundary_index $boundary_input_seen($bkey) \
                net "" \
                sink_cell $dst_name \
                sink_pin [obj_name $inpin] \
                sink_ref_pin [safe_get_property REF_PIN_NAME $inpin ""] \
            ]
            continue
        }

        set net_name [obj_name $net]
        set dpin [get_driver_pin_of_net $net]
        set dcell ""
        set dcell_name ""
        set dpin_name ""

        if {$dpin ne ""} {
            set dpin_name [obj_name $dpin]
            set dcells [get_cells -quiet -of_objects $dpin]
            if {[llength $dcells] == 1} {
                set dcell [lindex $dcells 0]
                set dcell_name [obj_name $dcell]
            }
        }

        if {$dcell_name ne "" && [info exists in_window($dcell_name)]} {
            set src_site [get_cell_site_name $dcell]
            set dst_site [get_cell_site_name $dst_cell]

            set delay_ps [get_interconnect_delay_ps $net $inpin]
            set fanout [llength [get_pins -quiet -of_objects $net -filter {DIRECTION == IN}]]

            set is_selected 0
            if {$dcell_name eq $source_cell_name && $dst_name eq $sink_cell_name && $net_name eq $selected_net_name} {
                set is_selected 1
            }

            lappend internal_edges [dict create \
                source_cell $dcell_name \
                source_pin $dpin_name \
                source_ref_pin [safe_get_property REF_PIN_NAME $dpin ""] \
                sink_cell $dst_name \
                sink_pin [obj_name $inpin] \
                sink_ref_pin [safe_get_property REF_PIN_NAME $inpin ""] \
                net $net_name \
                fanout $fanout \
                interconnect_delay_ps $delay_ps \
                manhattan_distance [manhattan_between_sites $src_site $dst_site] \
                selected_edge $is_selected \
            ]
        } else {
            set kindinfo [get_driver_kind_and_name $net]
            set driver_kind [lindex $kindinfo 0]
            set driver_cell [lindex $kindinfo 1]
            set driver_pin  [lindex $kindinfo 2]
            set driver_port [lindex $kindinfo 3]

            set bkey $net_name
            if {![info exists boundary_input_seen($bkey)]} {
                incr boundary_index_counter
                set boundary_input_seen($bkey) $boundary_index_counter

                lappend boundary_inputs [dict create \
                    boundary_index $boundary_index_counter \
                    net $net_name \
                    driver_kind $driver_kind \
                    driver_cell $driver_cell \
                    driver_pin $driver_pin \
                    driver_port $driver_port \
                    connection_count 0 \
                ]
            }

            lappend boundary_input_connections [dict create \
                boundary_index $boundary_input_seen($bkey) \
                net $net_name \
                sink_cell $dst_name \
                sink_pin [obj_name $inpin] \
                sink_ref_pin [safe_get_property REF_PIN_NAME $inpin ""] \
            ]
        }
    }
}

# connection_count in boundary_inputs bijwerken.
array set bcount {}
foreach b $boundary_inputs {
    set idx [dict get $b boundary_index]
    set bcount($idx) 0
}

foreach c $boundary_input_connections {
    set idx [dict get $c boundary_index]
    incr bcount($idx)
}

set boundary_inputs_updated {}
foreach b $boundary_inputs {
    set idx [dict get $b boundary_index]
    dict set b connection_count $bcount($idx)
    lappend boundary_inputs_updated $b
}
set boundary_inputs $boundary_inputs_updated

# -------------------------
# Boundary outputs
# -------------------------

set boundary_outputs {}
array set boundary_output_seen {}
set boundary_output_index_counter 0

foreach src_cell $window_cells {
    set src_name [obj_name $src_cell]

    foreach outpin [get_output_pins_sorted $src_cell] {
        set net [get_pin_net_obj $outpin]
        if {$net eq ""} {
            continue
        }

        set net_name [obj_name $net]
        set loads [get_pins -quiet -of_objects $net -filter {DIRECTION == IN}]
        set outside_loads {}

        foreach lp $loads {
            set lcells [get_cells -quiet -of_objects $lp]
            if {[llength $lcells] != 1} {
                continue
            }

            set lc [lindex $lcells 0]
            set lname [obj_name $lc]

            if {![info exists in_window($lname)]} {
                lappend outside_loads [obj_name $lp]
            }
        }

        set outside_ports {}
        set ports [get_ports -quiet -of_objects $net -filter {DIRECTION == OUT}]
        foreach p $ports {
            lappend outside_ports [obj_name $p]
        }

        if {[llength $outside_loads] > 0 || [llength $outside_ports] > 0} {
            set key "$src_name|[obj_name $outpin]|$net_name"
            if {![info exists boundary_output_seen($key)]} {
                incr boundary_output_index_counter
                set boundary_output_seen($key) $boundary_output_index_counter

                lappend boundary_outputs [dict create \
                    boundary_index $boundary_output_index_counter \
                    source_cell $src_name \
                    source_pin [obj_name $outpin] \
                    source_ref_pin [safe_get_property REF_PIN_NAME $outpin ""] \
                    net $net_name \
                    outside_load_count [llength $outside_loads] \
                    outside_loads [join $outside_loads "|"] \
                    outside_port_count [llength $outside_ports] \
                    outside_ports [join $outside_ports "|"] \
                ]
            }
        }
    }
}

# -------------------------
# Validations
# -------------------------

set num_luts [llength $window_cells]
set num_boundary_inputs [llength $boundary_inputs]
set num_boundary_outputs [llength $boundary_outputs]
set num_internal_edges [llength $internal_edges]

set selected_edge_inside 0
foreach e $internal_edges {
    if {[dict get $e selected_edge]} {
        set selected_edge_inside 1
    }
}

set acyclic [check_acyclic $window_cell_names $internal_edges]

if {$num_luts <= $max_luts} {
    add_validation validations "max_luts" "PASS" "num_luts=$num_luts <= max_luts=$max_luts"
} else {
    add_validation validations "max_luts" "FAIL" "num_luts=$num_luts > max_luts=$max_luts"
}

if {$num_boundary_inputs <= $max_boundary_inputs} {
    add_validation validations "max_boundary_inputs" "PASS" "num_boundary_inputs=$num_boundary_inputs <= max_boundary_inputs=$max_boundary_inputs"
} else {
    add_validation validations "max_boundary_inputs" "FAIL" "num_boundary_inputs=$num_boundary_inputs > max_boundary_inputs=$max_boundary_inputs"
}

if {$num_boundary_outputs <= $max_boundary_outputs} {
    add_validation validations "max_boundary_outputs" "PASS" "num_boundary_outputs=$num_boundary_outputs <= max_boundary_outputs=$max_boundary_outputs"
} else {
    add_validation validations "max_boundary_outputs" "FAIL" "num_boundary_outputs=$num_boundary_outputs > max_boundary_outputs=$max_boundary_outputs"
}

if {$contains_only_luts} {
    add_validation validations "contains_only_luts" "PASS" "all included cells are LUT1-LUT6"
} else {
    add_validation validations "contains_only_luts" "FAIL" "window contains non-LUT cells"
}

if {!$contains_lut6_2} {
    add_validation validations "no_lut6_2" "PASS" "no LUT6_2 cells in window"
} else {
    add_validation validations "no_lut6_2" "FAIL" "LUT6_2 found"
}

if {!$contains_forbidden} {
    add_validation validations "no_forbidden_primitives" "PASS" "no CARRY/DSP/BRAM/SRL/RAMD/FF included"
} else {
    add_validation validations "no_forbidden_primitives" "FAIL" "forbidden primitive found"
}

if {$selected_edge_inside} {
    add_validation validations "selected_edge_inside_window" "PASS" "selected edge is an internal window edge"
} else {
    add_validation validations "selected_edge_inside_window" "FAIL" "selected edge not found as internal edge"
}

if {$acyclic} {
    add_validation validations "window_graph_acyclic" "PASS" "internal LUT graph is acyclic"
} else {
    add_validation validations "window_graph_acyclic" "FAIL" "cycle detected in internal LUT graph"
}

set all_inits_present 1
foreach item $lut_items {
    if {[dict get $item init] eq ""} {
        set all_inits_present 0
    }
}

if {$all_inits_present} {
    add_validation validations "all_luts_have_init" "PASS" "INIT present for every LUT"
} else {
    add_validation validations "all_luts_have_init" "FAIL" "at least one LUT has no INIT"
}

set all_inputs_classified 1
foreach item $lut_items {
    set cname [dict get $item cell]
    set cobj [lindex [get_cells -quiet $cname] 0]
    foreach ip [get_input_pins_sorted $cobj] {
        set found 0

        foreach e $internal_edges {
            if {[dict get $e sink_pin] eq [obj_name $ip]} {
                set found 1
            }
        }

        foreach bconn $boundary_input_connections {
            if {[dict get $bconn sink_pin] eq [obj_name $ip]} {
                set found 1
            }
        }

        if {!$found} {
            set all_inputs_classified 0
        }
    }
}

if {$all_inputs_classified} {
    add_validation validations "all_lut_inputs_classified" "PASS" "every LUT input is internal or boundary"
} else {
    add_validation validations "all_lut_inputs_classified" "FAIL" "at least one LUT input could not be classified"
}

# Eindstatus.
set phase2_pass 1
foreach v $validations {
    if {[dict get $v status] eq "FAIL"} {
        set phase2_pass 0
    }
}

if {$phase2_pass} {
    set phase2_status "PASS"
} else {
    set phase2_status "FAIL"
}

# -------------------------
# CSV outputs
# -------------------------

set fh [open $out_luts w]
write_csv_row $fh {cell ref loc bel site site_x site_y init is_source is_sink input_count output_pin fanout}
foreach item $lut_items {
    write_csv_row $fh [list \
        [dict get $item cell] \
        [dict get $item ref] \
        [dict get $item loc] \
        [dict get $item bel] \
        [dict get $item site] \
        [dict get $item site_x] \
        [dict get $item site_y] \
        [dict get $item init] \
        [dict get $item is_source] \
        [dict get $item is_sink] \
        [dict get $item input_count] \
        [dict get $item output_pin] \
        [dict get $item fanout] \
    ]
}
close $fh

set fh [open $out_edges w]
write_csv_row $fh {source_cell source_pin source_ref_pin sink_cell sink_pin sink_ref_pin net fanout interconnect_delay_ps manhattan_distance selected_edge}
foreach e $internal_edges {
    write_csv_row $fh [list \
        [dict get $e source_cell] \
        [dict get $e source_pin] \
        [dict get $e source_ref_pin] \
        [dict get $e sink_cell] \
        [dict get $e sink_pin] \
        [dict get $e sink_ref_pin] \
        [dict get $e net] \
        [dict get $e fanout] \
        [dict get $e interconnect_delay_ps] \
        [dict get $e manhattan_distance] \
        [dict get $e selected_edge] \
    ]
}
close $fh

set fh [open $out_bin w]
write_csv_row $fh {boundary_index net driver_kind driver_cell driver_pin driver_port connection_count}
foreach b $boundary_inputs {
    write_csv_row $fh [list \
        [dict get $b boundary_index] \
        [dict get $b net] \
        [dict get $b driver_kind] \
        [dict get $b driver_cell] \
        [dict get $b driver_pin] \
        [dict get $b driver_port] \
        [dict get $b connection_count] \
    ]
}
close $fh

set fh [open $out_binc w]
write_csv_row $fh {boundary_index net sink_cell sink_pin sink_ref_pin}
foreach b $boundary_input_connections {
    write_csv_row $fh [list \
        [dict get $b boundary_index] \
        [dict get $b net] \
        [dict get $b sink_cell] \
        [dict get $b sink_pin] \
        [dict get $b sink_ref_pin] \
    ]
}
close $fh

set fh [open $out_bout w]
write_csv_row $fh {boundary_index source_cell source_pin source_ref_pin net outside_load_count outside_loads outside_port_count outside_ports}
foreach b $boundary_outputs {
    write_csv_row $fh [list \
        [dict get $b boundary_index] \
        [dict get $b source_cell] \
        [dict get $b source_pin] \
        [dict get $b source_ref_pin] \
        [dict get $b net] \
        [dict get $b outside_load_count] \
        [dict get $b outside_loads] \
        [dict get $b outside_port_count] \
        [dict get $b outside_ports] \
    ]
}
close $fh

set fh [open $out_checks w]
write_csv_row $fh {check status detail}
foreach v $validations {
    write_csv_row $fh [list [dict get $v check] [dict get $v status] [dict get $v detail]]
}
close $fh

set fh [open $out_growth w]
write_csv_row $fh {iteration candidate_cell action reason num_luts_after num_boundary_inputs_after num_boundary_outputs_after acyclic_after}
foreach g $growth_trace {
    write_csv_row $fh [list \
        [dict get $g iteration] \
        [dict get $g candidate_cell] \
        [dict get $g action] \
        [dict get $g reason] \
        [dict get $g num_luts_after] \
        [dict get $g num_boundary_inputs_after] \
        [dict get $g num_boundary_outputs_after] \
        [dict get $g acyclic_after] \
    ]
}
close $fh


# DOT graph.
set fh [open $out_dot w]
puts $fh "digraph window {"
puts $fh "  rankdir=LR;"
foreach item $lut_items {
    set cname [dict get $item cell]
    set label "$cname\\n[dict get $item ref]\\n[dict get $item site]/[dict get $item bel]"
    puts $fh "  \"${cname}\" \[label=\"${label}\"\];"
}
foreach e $internal_edges {
    set src [dict get $e source_cell]
    set dst [dict get $e sink_cell]
    set lbl "[dict get $e sink_ref_pin]\\n[dict get $e interconnect_delay_ps]ps\\nM=[dict get $e manhattan_distance]"
    if {[dict get $e selected_edge]} {
        puts $fh "  \"${src}\" -> \"${dst}\" \[label=\"${lbl}\", penwidth=3\];"
    } else {
        puts $fh "  \"${src}\" -> \"${dst}\" \[label=\"${lbl}\"\];"
    }
}
puts $fh "}"
close $fh

# Summary.
set summaryfh [open $out_summary w]
puts $summaryfh "phase2_status=$phase2_status"
puts $summaryfh "baseline_dcp=$baseline_dcp"
puts $summaryfh "phase1_json=$phase1_json"
puts $summaryfh "part=$part"
puts $summaryfh "source_cell=$source_cell_name"
puts $summaryfh "source_pin=$source_pin_name"
puts $summaryfh "sink_cell=$sink_cell_name"
puts $summaryfh "sink_pin=$sink_pin_name"
puts $summaryfh "selected_net=$selected_net_name"
puts $summaryfh "selected_delay_ps=$selected_delay_ps"
puts $summaryfh "num_luts=$num_luts"
puts $summaryfh "num_internal_edges=$num_internal_edges"
puts $summaryfh "num_boundary_inputs=$num_boundary_inputs"
puts $summaryfh "num_boundary_outputs=$num_boundary_outputs"
puts $summaryfh "contains_only_luts=$contains_only_luts"
puts $summaryfh "contains_lut6_2=$contains_lut6_2"
puts $summaryfh "contains_forbidden=$contains_forbidden"
puts $summaryfh "selected_edge_inside_window=$selected_edge_inside"
puts $summaryfh "window_graph_acyclic=$acyclic"
puts $summaryfh "max_luts=$max_luts"
puts $summaryfh "max_boundary_inputs=$max_boundary_inputs"
puts $summaryfh "max_boundary_outputs=$max_boundary_outputs"
puts $summaryfh "window_mode=$window_mode"
puts $summaryfh "target_luts=$target_luts"
puts $summaryfh "max_growth_iterations=$max_growth_iterations"
close $summaryfh

# JSON.
set jsonfh [open $out_json w]
puts $jsonfh "{"
puts $jsonfh "  \"phase\": \"FASE 2\","
puts $jsonfh "  \"phase2_status\": [json_escape $phase2_status],"
puts $jsonfh "  \"baseline_dcp\": [json_escape $baseline_dcp],"
puts $jsonfh "  \"phase1_json\": [json_escape $phase1_json],"
puts $jsonfh "  \"part\": [json_escape $part],"
puts $jsonfh "  \"selected_edge\": {"
puts $jsonfh "    \"source_cell\": [json_escape $source_cell_name],"
puts $jsonfh "    \"source_pin\": [json_escape $source_pin_name],"
puts $jsonfh "    \"sink_cell\": [json_escape $sink_cell_name],"
puts $jsonfh "    \"sink_pin\": [json_escape $sink_pin_name],"
puts $jsonfh "    \"net\": [json_escape $selected_net_name],"
puts $jsonfh "    \"interconnect_delay_ps\": [json_num_or_null $selected_delay_ps]"
puts $jsonfh "  },"
puts $jsonfh "  \"limits\": {"
puts $jsonfh "    \"max_luts\": [json_num_or_null $max_luts],"
puts $jsonfh "    \"max_boundary_inputs\": [json_num_or_null $max_boundary_inputs],"
puts $jsonfh "    \"max_boundary_outputs\": [json_num_or_null $max_boundary_outputs],"
puts $jsonfh "    \"window_mode\": [json_escape $window_mode],"
puts $jsonfh "    \"target_luts\": [json_num_or_null $target_luts],"
puts $jsonfh "    \"max_growth_iterations\": [json_num_or_null $max_growth_iterations]"
puts $jsonfh "  },"
puts $jsonfh "  \"summary\": {"
puts $jsonfh "    \"num_luts\": [json_num_or_null $num_luts],"
puts $jsonfh "    \"num_internal_edges\": [json_num_or_null $num_internal_edges],"
puts $jsonfh "    \"num_boundary_inputs\": [json_num_or_null $num_boundary_inputs],"
puts $jsonfh "    \"num_boundary_outputs\": [json_num_or_null $num_boundary_outputs],"
puts $jsonfh "    \"contains_only_luts\": [json_bool $contains_only_luts],"
puts $jsonfh "    \"contains_lut6_2\": [json_bool $contains_lut6_2],"
puts $jsonfh "    \"contains_forbidden\": [json_bool $contains_forbidden],"
puts $jsonfh "    \"selected_edge_inside_window\": [json_bool $selected_edge_inside],"
puts $jsonfh "    \"window_graph_acyclic\": [json_bool $acyclic]"
puts $jsonfh "  },"

write_array_json $jsonfh "luts" $lut_items \
    {cell ref loc bel site site_x site_y init is_source is_sink input_count output_pin fanout} \
    {site_x site_y input_count fanout} \
    {is_source is_sink} \
    "  " ","

write_array_json $jsonfh "internal_edges" $internal_edges \
    {source_cell source_pin source_ref_pin sink_cell sink_pin sink_ref_pin net fanout interconnect_delay_ps manhattan_distance selected_edge} \
    {fanout interconnect_delay_ps manhattan_distance} \
    {selected_edge} \
    "  " ","

write_array_json $jsonfh "boundary_inputs" $boundary_inputs \
    {boundary_index net driver_kind driver_cell driver_pin driver_port connection_count} \
    {boundary_index connection_count} \
    {} \
    "  " ","

write_array_json $jsonfh "boundary_input_connections" $boundary_input_connections \
    {boundary_index net sink_cell sink_pin sink_ref_pin} \
    {boundary_index} \
    {} \
    "  " ","

write_array_json $jsonfh "boundary_outputs" $boundary_outputs \
    {boundary_index source_cell source_pin source_ref_pin net outside_load_count outside_loads outside_port_count outside_ports} \
    {boundary_index outside_load_count outside_port_count} \
    {} \
    "  " ","

write_array_json $jsonfh "validation_checks" $validations \
    {check status detail} \
    {} \
    {} \
    "  " ""

puts $jsonfh "}"
close $jsonfh

puts $logfh "phase2_status = $phase2_status"
puts $logfh "summary geschreven: $out_summary"
puts $logfh "json geschreven: $out_json"
puts $logfh "luts csv: $out_luts"
puts $logfh "internal edges csv: $out_edges"
puts $logfh "boundary inputs csv: $out_bin"
puts $logfh "boundary input connections csv: $out_binc"
puts $logfh "boundary outputs csv: $out_bout"
puts $logfh "validation checks csv: $out_checks"
puts $logfh "dot graph: $out_dot"

close $logfh

if {$phase2_pass} {
    puts "PHASE2_PASS"
} else {
    puts "PHASE2_FAIL"
}

puts "Output dir: $out_dir"
puts "Summary   : $out_summary"
puts "JSON      : $out_json"
puts "Checks    : $out_checks"
