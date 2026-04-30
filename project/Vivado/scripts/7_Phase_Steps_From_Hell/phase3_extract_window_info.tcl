# phase3_extract_window_info.tcl
#
# FASE 3 — Extractie van volledige windowinformatie.
#
# Doel:
#   Alle logische en fysieke gegevens verzamelen die nodig zijn om
#   het window in FASE 4 exact te simuleren.
#
# Gebruik:
#   vivado -mode batch -source phase3_extract_window_info.tcl -tclargs \
#     <post_route.dcp> <phase2_window_dir> <out_dir>
#
# Voorbeeld:
#   vivado -mode batch -source phase3_extract_window_info.tcl -tclargs \
#     ~/Masterproef/project/results/run_lut_insertion/TestDirectory/baseline_impl/checkpoints/post_route_timingexp.dcp \
#     ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase2_window \
#     ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase3_window_info

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

proc read_lines {path} {
    set fh [open $path r]
    set txt [read $fh]
    close $fh
    set lines [split $txt "\n"]
    return $lines
}

proc read_window_cells_from_phase2 {csv_path} {
    set cells {}
    set lines [read_lines $csv_path]
    set first 1

    foreach line $lines {
        set line [string trim $line]
        if {$line eq ""} {
            continue
        }

        if {$first} {
            set first 0
            continue
        }

        # window_luts.csv heeft geen komma's in cell names.
        set cols [split $line ","]
        set cell_name [lindex $cols 0]
        if {$cell_name ne ""} {
            lappend cells $cell_name
        }
    }

    return $cells
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

proc compare_pin_ref_name {a b} {
    set ra [safe_get_property REF_PIN_NAME $a ""]
    set rb [safe_get_property REF_PIN_NAME $b ""]
    return [string compare $ra $rb]
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

proc get_driver_pins_of_net {net} {
    return [get_pins -quiet -of_objects $net -filter {DIRECTION == OUT}]
}

proc get_driver_pin_of_net {net} {
    set drivers [get_driver_pins_of_net $net]
    if {[llength $drivers] == 1} {
        return [lindex $drivers 0]
    }
    return ""
}

proc get_cell_site_name {cell} {
    if {![catch {set sites [get_sites -quiet -of_objects $cell]}]} {
        if {[llength $sites] > 0} {
            return [obj_name [lindex $sites 0]]
        }
    }
    return [safe_get_property LOC $cell ""]
}

proc get_cell_tile_name {cell} {
    if {![catch {set sites [get_sites -quiet -of_objects $cell]}]} {
        if {[llength $sites] > 0} {
            set site [lindex $sites 0]
            set tiles [get_tiles -quiet -of_objects $site]
            if {[llength $tiles] > 0} {
                return [obj_name [lindex $tiles 0]]
            }
        }
    }
    return ""
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
    if {$net eq "" || $sink_pin eq ""} {
        return ""
    }

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

proc get_design_part_name {} {
    if {![catch {set p [current_part]}]} {
        if {$p ne ""} {
            return $p
        }
    }

    if {![catch {set p [get_property PART [current_design]]}]} {
        if {$p ne ""} {
            return $p
        }
    }

    return ""
}

proc add_validation {validations_var check status detail} {
    upvar $validations_var validations
    lappend validations [dict create check $check status $status detail $detail]
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

# -------------------------
# Args
# -------------------------

if {[llength $argv] < 3} {
    puts "ERROR: usage: vivado -mode batch -source phase3_extract_window_info.tcl -tclargs <dcp> <phase2_window_dir> <out_dir>"
    exit 1
}

set baseline_dcp [file normalize [lindex $argv 0]]
set phase2_dir   [file normalize [lindex $argv 1]]
set out_dir      [file normalize [lindex $argv 2]]

file mkdir $out_dir

set phase2_luts_csv [file join $phase2_dir "window_luts.csv"]

set out_summary  [file join $out_dir "phase3_summary.txt"]
set out_json     [file join $out_dir "phase3_window_info.json"]
set out_cells    [file join $out_dir "lut_cells.csv"]
set out_inputs   [file join $out_dir "lut_input_pins.csv"]
set out_outputs  [file join $out_dir "lut_output_pins.csv"]
set out_edges    [file join $out_dir "window_edges_all.csv"]
set out_bin      [file join $out_dir "boundary_inputs.csv"]
set out_bout     [file join $out_dir "boundary_outputs.csv"]
set out_sites    [file join $out_dir "physical_sites.csv"]
set out_checks   [file join $out_dir "validation_checks.csv"]
set out_manifest [file join $out_dir "simulation_manifest.txt"]
set out_pinorder [file join $out_dir "lut_pin_order_assumption.txt"]
set out_dot      [file join $out_dir "window_graph_detailed.dot"]
set out_log      [file join $out_dir "phase3_extract.log"]

set logfh [open $out_log w]

puts $logfh "FASE 3 extractie gestart"
puts $logfh "baseline_dcp = $baseline_dcp"
puts $logfh "phase2_dir   = $phase2_dir"
puts $logfh "out_dir      = $out_dir"

if {![file exists $baseline_dcp]} {
    puts $logfh "ERROR: DCP bestaat niet: $baseline_dcp"
    close $logfh
    exit 1
}

if {![file exists $phase2_luts_csv]} {
    puts $logfh "ERROR: phase2 window_luts.csv bestaat niet: $phase2_luts_csv"
    close $logfh
    exit 1
}

set window_cell_names [read_window_cells_from_phase2 $phase2_luts_csv]

if {[llength $window_cell_names] == 0} {
    puts $logfh "ERROR: geen window cells gevonden in $phase2_luts_csv"
    close $logfh
    exit 2
}

puts $logfh "window cells uit FASE 2:"
foreach c $window_cell_names {
    puts $logfh "  $c"
}

open_checkpoint $baseline_dcp

set part [get_design_part_name]

array set in_window {}
foreach cname $window_cell_names {
    set in_window($cname) 1
}

set validations {}

# -------------------------
# Resolve cells
# -------------------------

set window_cells {}
foreach cname $window_cell_names {
    set cs [get_cells -quiet $cname]

    if {[llength $cs] != 1} {
        add_validation validations "cell_exists:$cname" "FAIL" "cell not found or not unique"
    } else {
        add_validation validations "cell_exists:$cname" "PASS" "cell found"
        lappend window_cells [lindex $cs 0]
    }
}

if {[llength $window_cells] != [llength $window_cell_names]} {
    set fh [open $out_summary w]
    puts $fh "phase3_status=FAIL"
    puts $fh "reason=not_all_cells_found"
    close $fh
    close $logfh
    exit 3
}

# -------------------------
# Extract cell metadata
# -------------------------

set cell_items {}
set site_items {}
array set site_seen {}

set contains_only_luts 1
set contains_lut6_2 0
set contains_forbidden 0
set all_inits_present 1
set all_locations_present 1

foreach cell $window_cells {
    set cname [obj_name $cell]
    set ref [safe_get_property REF_NAME $cell ""]
    set loc [safe_get_property LOC $cell ""]
    set bel [safe_get_property BEL $cell ""]
    set site [get_cell_site_name $cell]
    set tile [get_cell_tile_name $cell]
    set xy [site_xy $site]
    set init [safe_get_property INIT $cell ""]

    if {![is_simple_lut_cell $cell]} {
        set contains_only_luts 0
    }

    if {[is_lut6_2_cell $cell]} {
        set contains_lut6_2 1
    }

    if {[is_forbidden_cell_type $cell]} {
        set contains_forbidden 1
    }

    if {$init eq ""} {
        set all_inits_present 0
    }

    if {$loc eq "" || $bel eq "" || $site eq ""} {
        set all_locations_present 0
    }

    set input_pins [get_input_pins_sorted $cell]
    set output_pins [get_output_pins_sorted $cell]

    set item [dict create \
        cell $cname \
        ref $ref \
        loc $loc \
        bel $bel \
        site $site \
        tile $tile \
        site_x [lindex $xy 0] \
        site_y [lindex $xy 1] \
        init $init \
        num_lut_inputs [llength $input_pins] \
        num_lut_outputs [llength $output_pins] \
    ]

    lappend cell_items $item

    if {![info exists site_seen($site)]} {
        set site_seen($site) 1
        lappend site_items [dict create \
            site $site \
            tile $tile \
            site_x [lindex $xy 0] \
            site_y [lindex $xy 1] \
            cells_on_site $cname \
        ]
    } else {
        # Voor eenvoud schrijven we cells_on_site niet achteraf samen.
        # Het belangrijkste is dat elke gebruikte site bekend is.
    }
}

# -------------------------
# Extract input pins, edges, boundary inputs
# -------------------------

set input_items {}
set edge_items {}
set boundary_input_items {}

array set boundary_input_seen {}
set boundary_index_counter 0

set all_inputs_classified 1
set all_internal_edges_single_driver 1

foreach sink_cell $window_cells {
    set sink_cell_name [obj_name $sink_cell]
    set sink_site [get_cell_site_name $sink_cell]

    foreach inpin [get_input_pins_sorted $sink_cell] {
        set sink_pin_name [obj_name $inpin]
        set sink_ref_pin [safe_get_property REF_PIN_NAME $inpin ""]
        set input_index ""

        if {[regexp {I([0-5])} $sink_ref_pin -> idx]} {
            set input_index $idx
        }

        set net [get_pin_net_obj $inpin]
        set net_name ""
        set connected 0
        set driver_kind "UNCONNECTED"
        set driver_cell_name ""
        set driver_cell_ref ""
        set driver_pin_name ""
        set driver_ref_pin ""
        set driver_port_name ""
        set driver_site ""
        set classification "unconnected"
        set inter_delay_ps ""
        set manhattan ""
        set net_fanout 0
        set driver_count 0

        if {$net ne ""} {
            set connected 1
            set net_name [obj_name $net]
            set drivers [get_driver_pins_of_net $net]
            set driver_count [llength $drivers]
            set loads [get_pins -quiet -of_objects $net -filter {DIRECTION == IN}]
            set net_fanout [llength $loads]

            if {$driver_count != 1} {
                set all_internal_edges_single_driver 0
            }

            set dpin [get_driver_pin_of_net $net]

            if {$dpin ne ""} {
                set driver_pin_name [obj_name $dpin]
                set driver_ref_pin [safe_get_property REF_PIN_NAME $dpin ""]
                set dcells [get_cells -quiet -of_objects $dpin]

                if {[llength $dcells] == 1} {
                    set dcell [lindex $dcells 0]
                    set driver_cell_name [obj_name $dcell]
                    set driver_cell_ref [safe_get_property REF_NAME $dcell ""]
                    set driver_site [get_cell_site_name $dcell]

                    if {[info exists in_window($driver_cell_name)]} {
                        set driver_kind "INTERNAL_LUT"
                        set classification "internal"
                        set manhattan [manhattan_between_sites $driver_site $sink_site]
                        set inter_delay_ps [get_interconnect_delay_ps $net $inpin]
                    } else {
                        set driver_kind "EXTERNAL_CELL"
                        set classification "boundary_input"
                    }
                }
            } else {
                set ports [get_ports -quiet -of_objects $net -filter {DIRECTION == IN}]
                if {[llength $ports] > 0} {
                    set driver_kind "PORT"
                    set driver_port_name [obj_name [lindex $ports 0]]
                    set classification "boundary_input"
                } else {
                    set net_type [safe_get_property TYPE $net ""]
                    if {[regexp -nocase {const|gnd|vcc} $net_name] || [regexp -nocase {POWER|GROUND} $net_type]} {
                        set driver_kind "CONST"
                        set classification "boundary_input"
                    } else {
                        set driver_kind "UNKNOWN"
                        set classification "boundary_input"
                    }
                }
            }
        }

        if {$classification eq ""} {
            set all_inputs_classified 0
        }

        lappend input_items [dict create \
            sink_cell $sink_cell_name \
            sink_ref [safe_get_property REF_NAME $sink_cell ""] \
            sink_pin $sink_pin_name \
            sink_ref_pin $sink_ref_pin \
            input_index $input_index \
            connected $connected \
            net $net_name \
            classification $classification \
            driver_kind $driver_kind \
            driver_cell $driver_cell_name \
            driver_ref $driver_cell_ref \
            driver_pin $driver_pin_name \
            driver_ref_pin $driver_ref_pin \
            driver_port $driver_port_name \
            driver_site $driver_site \
            net_fanout $net_fanout \
            driver_count $driver_count \
            interconnect_delay_ps $inter_delay_ps \
            manhattan_distance $manhattan \
        ]

        if {$classification eq "internal"} {
            lappend edge_items [dict create \
                edge_kind "internal" \
                source_cell $driver_cell_name \
                source_ref $driver_cell_ref \
                source_pin $driver_pin_name \
                source_ref_pin $driver_ref_pin \
                sink_cell $sink_cell_name \
                sink_ref [safe_get_property REF_NAME $sink_cell ""] \
                sink_pin $sink_pin_name \
                sink_ref_pin $sink_ref_pin \
                net $net_name \
                net_fanout $net_fanout \
                driver_count $driver_count \
                interconnect_delay_ps $inter_delay_ps \
                manhattan_distance $manhattan \
                inside_window 1 \
            ]
        } elseif {$classification eq "boundary_input"} {
            set bkey $net_name
            if {$bkey eq ""} {
                set bkey "UNCONNECTED:$sink_pin_name"
            }

            if {![info exists boundary_input_seen($bkey)]} {
                incr boundary_index_counter
                set boundary_input_seen($bkey) $boundary_index_counter

                lappend boundary_input_items [dict create \
                    boundary_index $boundary_index_counter \
                    net $net_name \
                    driver_kind $driver_kind \
                    driver_cell $driver_cell_name \
                    driver_ref $driver_cell_ref \
                    driver_pin $driver_pin_name \
                    driver_ref_pin $driver_ref_pin \
                    driver_port $driver_port_name \
                    driver_site $driver_site \
                    connection_count 0 \
                ]
            }
        }
    }
}

# Boundary input connection counts.
array set bconn_count {}
foreach b $boundary_input_items {
    set idx [dict get $b boundary_index]
    set bconn_count($idx) 0
}

foreach inp $input_items {
    if {[dict get $inp classification] eq "boundary_input"} {
        set net [dict get $inp net]
        set key $net
        if {$key eq ""} {
            set key "UNCONNECTED:[dict get $inp sink_pin]"
        }

        if {[info exists boundary_input_seen($key)]} {
            set idx $boundary_input_seen($key)
            incr bconn_count($idx)
        }
    }
}

set boundary_input_items_updated {}
foreach b $boundary_input_items {
    set idx [dict get $b boundary_index]
    dict set b connection_count $bconn_count($idx)
    lappend boundary_input_items_updated $b
}
set boundary_input_items $boundary_input_items_updated

# -------------------------
# Extract outputs and boundary outputs
# -------------------------

set output_items {}
set boundary_output_items {}
set boundary_output_index 0

foreach source_cell $window_cells {
    set source_cell_name [obj_name $source_cell]
    set source_site [get_cell_site_name $source_cell]

    foreach outpin [get_output_pins_sorted $source_cell] {
        set outpin_name [obj_name $outpin]
        set out_ref_pin [safe_get_property REF_PIN_NAME $outpin ""]
        set net [get_pin_net_obj $outpin]

        set net_name ""
        set net_fanout 0
        set inside_loads {}
        set outside_loads {}
        set outside_ports {}

        if {$net ne ""} {
            set net_name [obj_name $net]
            set loads [get_pins -quiet -of_objects $net -filter {DIRECTION == IN}]
            set net_fanout [llength $loads]

            foreach lp $loads {
                set lcells [get_cells -quiet -of_objects $lp]
                if {[llength $lcells] == 1} {
                    set lcell [lindex $lcells 0]
                    set lname [obj_name $lcell]

                    if {[info exists in_window($lname)]} {
                        lappend inside_loads [obj_name $lp]
                    } else {
                        lappend outside_loads [obj_name $lp]
                    }
                }
            }

            set ports [get_ports -quiet -of_objects $net -filter {DIRECTION == OUT}]
            foreach p $ports {
                lappend outside_ports [obj_name $p]
            }
        }

        set is_boundary_output 0
        if {[llength $outside_loads] > 0 || [llength $outside_ports] > 0} {
            set is_boundary_output 1
        }

        lappend output_items [dict create \
            source_cell $source_cell_name \
            source_ref [safe_get_property REF_NAME $source_cell ""] \
            source_pin $outpin_name \
            source_ref_pin $out_ref_pin \
            net $net_name \
            net_fanout $net_fanout \
            inside_load_count [llength $inside_loads] \
            inside_loads [join $inside_loads "|"] \
            outside_load_count [llength $outside_loads] \
            outside_loads [join $outside_loads "|"] \
            outside_port_count [llength $outside_ports] \
            outside_ports [join $outside_ports "|"] \
            is_boundary_output $is_boundary_output \
        ]

        if {$is_boundary_output} {
            incr boundary_output_index

            lappend boundary_output_items [dict create \
                boundary_index $boundary_output_index \
                source_cell $source_cell_name \
                source_ref [safe_get_property REF_NAME $source_cell ""] \
                source_pin $outpin_name \
                source_ref_pin $out_ref_pin \
                net $net_name \
                net_fanout $net_fanout \
                outside_load_count [llength $outside_loads] \
                outside_loads [join $outside_loads "|"] \
                outside_port_count [llength $outside_ports] \
                outside_ports [join $outside_ports "|"] \
            ]
        }
    }
}

# -------------------------
# Validation checks
# -------------------------

set num_luts [llength $cell_items]
set num_inputs [llength $input_items]
set num_outputs [llength $output_items]
set num_internal_edges [llength $edge_items]
set num_boundary_inputs [llength $boundary_input_items]
set num_boundary_outputs [llength $boundary_output_items]
set num_sites [llength $site_items]

if {$contains_only_luts} {
    add_validation validations "contains_only_luts" "PASS" "all cells are LUT1-LUT6"
} else {
    add_validation validations "contains_only_luts" "FAIL" "non-LUT found"
}

if {!$contains_lut6_2} {
    add_validation validations "no_lut6_2" "PASS" "no LUT6_2 found"
} else {
    add_validation validations "no_lut6_2" "FAIL" "LUT6_2 found"
}

if {!$contains_forbidden} {
    add_validation validations "no_forbidden_primitives" "PASS" "no CARRY/DSP/BRAM/SRL/RAMD/FF found"
} else {
    add_validation validations "no_forbidden_primitives" "FAIL" "forbidden primitive found"
}

if {$all_inits_present} {
    add_validation validations "all_luts_have_init" "PASS" "INIT present for each LUT"
} else {
    add_validation validations "all_luts_have_init" "FAIL" "missing INIT"
}

if {$all_locations_present} {
    add_validation validations "all_locations_present" "PASS" "LOC/BEL/SITE present for each LUT"
} else {
    add_validation validations "all_locations_present" "FAIL" "missing LOC/BEL/SITE"
}

if {$all_inputs_classified} {
    add_validation validations "all_lut_inputs_classified" "PASS" "each LUT input classified"
} else {
    add_validation validations "all_lut_inputs_classified" "FAIL" "unclassified LUT input"
}

if {$all_internal_edges_single_driver} {
    add_validation validations "all_nets_have_single_driver_where_needed" "PASS" "no multi-driver net observed on LUT inputs"
} else {
    add_validation validations "all_nets_have_single_driver_where_needed" "FAIL" "multi-driver or ambiguous driver observed"
}

if {$num_boundary_outputs >= 1} {
    add_validation validations "has_boundary_output" "PASS" "boundary output count=$num_boundary_outputs"
} else {
    add_validation validations "has_boundary_output" "FAIL" "no boundary output found"
}

if {$num_boundary_inputs <= 12} {
    add_validation validations "boundary_input_limit_for_truth_table" "PASS" "num_boundary_inputs=$num_boundary_inputs <= 12"
} else {
    add_validation validations "boundary_input_limit_for_truth_table" "FAIL" "num_boundary_inputs=$num_boundary_inputs > 12"
}

# FASE 3 pass only if all checks pass.
set phase3_pass 1
foreach v $validations {
    if {[dict get $v status] eq "FAIL"} {
        set phase3_pass 0
    }
}

if {$phase3_pass} {
    set phase3_status "PASS"
} else {
    set phase3_status "FAIL"
}

# -------------------------
# Write CSV files
# -------------------------

set fh [open $out_cells w]
write_csv_row $fh {cell ref loc bel site tile site_x site_y init num_lut_inputs num_lut_outputs}
foreach item $cell_items {
    write_csv_row $fh [list \
        [dict get $item cell] \
        [dict get $item ref] \
        [dict get $item loc] \
        [dict get $item bel] \
        [dict get $item site] \
        [dict get $item tile] \
        [dict get $item site_x] \
        [dict get $item site_y] \
        [dict get $item init] \
        [dict get $item num_lut_inputs] \
        [dict get $item num_lut_outputs] \
    ]
}
close $fh

set fh [open $out_inputs w]
write_csv_row $fh {sink_cell sink_ref sink_pin sink_ref_pin input_index connected net classification driver_kind driver_cell driver_ref driver_pin driver_ref_pin driver_port driver_site net_fanout driver_count interconnect_delay_ps manhattan_distance}
foreach item $input_items {
    write_csv_row $fh [list \
        [dict get $item sink_cell] \
        [dict get $item sink_ref] \
        [dict get $item sink_pin] \
        [dict get $item sink_ref_pin] \
        [dict get $item input_index] \
        [dict get $item connected] \
        [dict get $item net] \
        [dict get $item classification] \
        [dict get $item driver_kind] \
        [dict get $item driver_cell] \
        [dict get $item driver_ref] \
        [dict get $item driver_pin] \
        [dict get $item driver_ref_pin] \
        [dict get $item driver_port] \
        [dict get $item driver_site] \
        [dict get $item net_fanout] \
        [dict get $item driver_count] \
        [dict get $item interconnect_delay_ps] \
        [dict get $item manhattan_distance] \
    ]
}
close $fh

set fh [open $out_outputs w]
write_csv_row $fh {source_cell source_ref source_pin source_ref_pin net net_fanout inside_load_count inside_loads outside_load_count outside_loads outside_port_count outside_ports is_boundary_output}
foreach item $output_items {
    write_csv_row $fh [list \
        [dict get $item source_cell] \
        [dict get $item source_ref] \
        [dict get $item source_pin] \
        [dict get $item source_ref_pin] \
        [dict get $item net] \
        [dict get $item net_fanout] \
        [dict get $item inside_load_count] \
        [dict get $item inside_loads] \
        [dict get $item outside_load_count] \
        [dict get $item outside_loads] \
        [dict get $item outside_port_count] \
        [dict get $item outside_ports] \
        [dict get $item is_boundary_output] \
    ]
}
close $fh

set fh [open $out_edges w]
write_csv_row $fh {edge_kind source_cell source_ref source_pin source_ref_pin sink_cell sink_ref sink_pin sink_ref_pin net net_fanout driver_count interconnect_delay_ps manhattan_distance inside_window}
foreach item $edge_items {
    write_csv_row $fh [list \
        [dict get $item edge_kind] \
        [dict get $item source_cell] \
        [dict get $item source_ref] \
        [dict get $item source_pin] \
        [dict get $item source_ref_pin] \
        [dict get $item sink_cell] \
        [dict get $item sink_ref] \
        [dict get $item sink_pin] \
        [dict get $item sink_ref_pin] \
        [dict get $item net] \
        [dict get $item net_fanout] \
        [dict get $item driver_count] \
        [dict get $item interconnect_delay_ps] \
        [dict get $item manhattan_distance] \
        [dict get $item inside_window] \
    ]
}
close $fh

set fh [open $out_bin w]
write_csv_row $fh {boundary_index net driver_kind driver_cell driver_ref driver_pin driver_ref_pin driver_port driver_site connection_count}
foreach item $boundary_input_items {
    write_csv_row $fh [list \
        [dict get $item boundary_index] \
        [dict get $item net] \
        [dict get $item driver_kind] \
        [dict get $item driver_cell] \
        [dict get $item driver_ref] \
        [dict get $item driver_pin] \
        [dict get $item driver_ref_pin] \
        [dict get $item driver_port] \
        [dict get $item driver_site] \
        [dict get $item connection_count] \
    ]
}
close $fh

set fh [open $out_bout w]
write_csv_row $fh {boundary_index source_cell source_ref source_pin source_ref_pin net net_fanout outside_load_count outside_loads outside_port_count outside_ports}
foreach item $boundary_output_items {
    write_csv_row $fh [list \
        [dict get $item boundary_index] \
        [dict get $item source_cell] \
        [dict get $item source_ref] \
        [dict get $item source_pin] \
        [dict get $item source_ref_pin] \
        [dict get $item net] \
        [dict get $item net_fanout] \
        [dict get $item outside_load_count] \
        [dict get $item outside_loads] \
        [dict get $item outside_port_count] \
        [dict get $item outside_ports] \
    ]
}
close $fh

set fh [open $out_sites w]
write_csv_row $fh {site tile site_x site_y cells_on_site}
foreach item $site_items {
    write_csv_row $fh [list \
        [dict get $item site] \
        [dict get $item tile] \
        [dict get $item site_x] \
        [dict get $item site_y] \
        [dict get $item cells_on_site] \
    ]
}
close $fh

set fh [open $out_checks w]
write_csv_row $fh {check status detail}
foreach v $validations {
    write_csv_row $fh [list \
        [dict get $v check] \
        [dict get $v status] \
        [dict get $v detail] \
    ]
}
close $fh

# -------------------------
# Manifest and pin order notes
# -------------------------

set fh [open $out_manifest w]
puts $fh "phase3_status=$phase3_status"
puts $fh "baseline_dcp=$baseline_dcp"
puts $fh "phase2_dir=$phase2_dir"
puts $fh "part=$part"
puts $fh "num_luts=$num_luts"
puts $fh "num_input_pins=$num_inputs"
puts $fh "num_output_pins=$num_outputs"
puts $fh "num_internal_edges=$num_internal_edges"
puts $fh "num_boundary_inputs=$num_boundary_inputs"
puts $fh "num_boundary_outputs=$num_boundary_outputs"
puts $fh "num_physical_sites=$num_sites"
puts $fh "lut_cells_csv=$out_cells"
puts $fh "lut_input_pins_csv=$out_inputs"
puts $fh "lut_output_pins_csv=$out_outputs"
puts $fh "window_edges_all_csv=$out_edges"
puts $fh "boundary_inputs_csv=$out_bin"
puts $fh "boundary_outputs_csv=$out_bout"
puts $fh "physical_sites_csv=$out_sites"
close $fh

set fh [open $out_pinorder w]
puts $fh "This file records the LUT pin order that FASE 4 must use consistently."
puts $fh ""
puts $fh "Assumption for simulation:"
puts $fh "  LUT input bit index order = I0 as least significant input, then I1, I2, I3, I4, I5."
puts $fh "  INIT lookup index = I0 + 2*I1 + 4*I2 + 8*I3 + 16*I4 + 32*I5."
puts $fh ""
puts $fh "Important:"
puts $fh "  FASE 4 must validate this by re-simulating the extracted original window."
puts $fh "  This FASE 3 step only records the mapping; it does not yet prove INIT ordering."
close $fh

# -------------------------
# DOT graph
# -------------------------

set fh [open $out_dot w]
puts $fh "digraph window_detailed {"
puts $fh "  rankdir=LR;"

foreach cell $cell_items {
    set cname [dict get $cell cell]
    set label "$cname\\n[dict get $cell ref]\\n[dict get $cell site]/[dict get $cell bel]"
    puts $fh "  \"${cname}\" \[shape=box,label=\"${label}\"\];"
}

foreach b $boundary_input_items {
    set bname "BI_[dict get $b boundary_index]"
    set label "$bname\\n[dict get $b net]\\n[dict get $b driver_kind]"
    puts $fh "  \"${bname}\" \[shape=oval,label=\"${label}\"\];"
}

foreach inp $input_items {
    if {[dict get $inp classification] eq "boundary_input"} {
        set net [dict get $inp net]
        set key $net
        if {$key eq ""} {
            set key "UNCONNECTED:[dict get $inp sink_pin]"
        }

        if {[info exists boundary_input_seen($key)]} {
            set bname "BI_$boundary_input_seen($key)"
            set dst [dict get $inp sink_cell]
            set lbl "[dict get $inp sink_ref_pin]"
            puts $fh "  \"${bname}\" -> \"${dst}\" \[label=\"${lbl}\"\];"
        }
    }
}

foreach e $edge_items {
    set src [dict get $e source_cell]
    set dst [dict get $e sink_cell]
    set lbl "[dict get $e sink_ref_pin]\\n[dict get $e interconnect_delay_ps]ps\\nM=[dict get $e manhattan_distance]"
    puts $fh "  \"${src}\" -> \"${dst}\" \[label=\"${lbl}\", penwidth=2\];"
}

foreach bo $boundary_output_items {
    set boname "BO_[dict get $bo boundary_index]"
    set src [dict get $bo source_cell]
    set label "$boname\\n[dict get $bo net]\\nloads=[dict get $bo outside_load_count]"
    puts $fh "  \"${boname}\" \[shape=oval,label=\"${label}\"\];"
    puts $fh "  \"${src}\" -> \"${boname}\" \[label=\"[dict get $bo source_ref_pin]\"\];"
}

puts $fh "}"
close $fh

# -------------------------
# JSON
# -------------------------

set jsonfh [open $out_json w]
puts $jsonfh "{"
puts $jsonfh "  \"phase\": \"FASE 3\","
puts $jsonfh "  \"phase3_status\": [json_escape $phase3_status],"
puts $jsonfh "  \"baseline_dcp\": [json_escape $baseline_dcp],"
puts $jsonfh "  \"phase2_dir\": [json_escape $phase2_dir],"
puts $jsonfh "  \"part\": [json_escape $part],"
puts $jsonfh "  \"summary\": {"
puts $jsonfh "    \"num_luts\": [json_num_or_null $num_luts],"
puts $jsonfh "    \"num_input_pins\": [json_num_or_null $num_inputs],"
puts $jsonfh "    \"num_output_pins\": [json_num_or_null $num_outputs],"
puts $jsonfh "    \"num_internal_edges\": [json_num_or_null $num_internal_edges],"
puts $jsonfh "    \"num_boundary_inputs\": [json_num_or_null $num_boundary_inputs],"
puts $jsonfh "    \"num_boundary_outputs\": [json_num_or_null $num_boundary_outputs],"
puts $jsonfh "    \"num_physical_sites\": [json_num_or_null $num_sites],"
puts $jsonfh "    \"contains_only_luts\": [json_bool $contains_only_luts],"
puts $jsonfh "    \"contains_lut6_2\": [json_bool $contains_lut6_2],"
puts $jsonfh "    \"contains_forbidden\": [json_bool $contains_forbidden],"
puts $jsonfh "    \"all_inits_present\": [json_bool $all_inits_present],"
puts $jsonfh "    \"all_locations_present\": [json_bool $all_locations_present]"
puts $jsonfh "  },"

write_array_json $jsonfh "luts" $cell_items \
    {cell ref loc bel site tile site_x site_y init num_lut_inputs num_lut_outputs} \
    {site_x site_y num_lut_inputs num_lut_outputs} \
    {} \
    "  " ","

write_array_json $jsonfh "lut_input_pins" $input_items \
    {sink_cell sink_ref sink_pin sink_ref_pin input_index connected net classification driver_kind driver_cell driver_ref driver_pin driver_ref_pin driver_port driver_site net_fanout driver_count interconnect_delay_ps manhattan_distance} \
    {input_index connected net_fanout driver_count interconnect_delay_ps manhattan_distance} \
    {} \
    "  " ","

write_array_json $jsonfh "lut_output_pins" $output_items \
    {source_cell source_ref source_pin source_ref_pin net net_fanout inside_load_count inside_loads outside_load_count outside_loads outside_port_count outside_ports is_boundary_output} \
    {net_fanout inside_load_count outside_load_count outside_port_count} \
    {is_boundary_output} \
    "  " ","

write_array_json $jsonfh "internal_edges" $edge_items \
    {edge_kind source_cell source_ref source_pin source_ref_pin sink_cell sink_ref sink_pin sink_ref_pin net net_fanout driver_count interconnect_delay_ps manhattan_distance inside_window} \
    {net_fanout driver_count interconnect_delay_ps manhattan_distance inside_window} \
    {} \
    "  " ","

write_array_json $jsonfh "boundary_inputs" $boundary_input_items \
    {boundary_index net driver_kind driver_cell driver_ref driver_pin driver_ref_pin driver_port driver_site connection_count} \
    {boundary_index connection_count} \
    {} \
    "  " ","

write_array_json $jsonfh "boundary_outputs" $boundary_output_items \
    {boundary_index source_cell source_ref source_pin source_ref_pin net net_fanout outside_load_count outside_loads outside_port_count outside_ports} \
    {boundary_index net_fanout outside_load_count outside_port_count} \
    {} \
    "  " ","

write_array_json $jsonfh "physical_sites" $site_items \
    {site tile site_x site_y cells_on_site} \
    {site_x site_y} \
    {} \
    "  " ","

write_array_json $jsonfh "validation_checks" $validations \
    {check status detail} \
    {} \
    {} \
    "  " ""

puts $jsonfh "}"
close $jsonfh

# Summary
set fh [open $out_summary w]
puts $fh "phase3_status=$phase3_status"
puts $fh "baseline_dcp=$baseline_dcp"
puts $fh "phase2_dir=$phase2_dir"
puts $fh "part=$part"
puts $fh "num_luts=$num_luts"
puts $fh "num_input_pins=$num_inputs"
puts $fh "num_output_pins=$num_outputs"
puts $fh "num_internal_edges=$num_internal_edges"
puts $fh "num_boundary_inputs=$num_boundary_inputs"
puts $fh "num_boundary_outputs=$num_boundary_outputs"
puts $fh "num_physical_sites=$num_sites"
puts $fh "contains_only_luts=$contains_only_luts"
puts $fh "contains_lut6_2=$contains_lut6_2"
puts $fh "contains_forbidden=$contains_forbidden"
puts $fh "all_inits_present=$all_inits_present"
puts $fh "all_locations_present=$all_locations_present"
close $fh

puts $logfh "phase3_status=$phase3_status"
puts $logfh "summary=$out_summary"
puts $logfh "json=$out_json"
puts $logfh "cells=$out_cells"
puts $logfh "inputs=$out_inputs"
puts $logfh "outputs=$out_outputs"
puts $logfh "edges=$out_edges"
puts $logfh "boundary_inputs=$out_bin"
puts $logfh "boundary_outputs=$out_bout"
puts $logfh "sites=$out_sites"
puts $logfh "checks=$out_checks"

close $logfh

if {$phase3_pass} {
    puts "PHASE3_PASS"
} else {
    puts "PHASE3_FAIL"
}

puts "Output dir: $out_dir"
puts "Summary   : $out_summary"
puts "JSON      : $out_json"
puts "Checks    : $out_checks"
