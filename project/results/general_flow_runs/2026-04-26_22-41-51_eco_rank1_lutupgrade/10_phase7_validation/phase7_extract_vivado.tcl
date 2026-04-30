# Auto-generated FASE 7 Vivado extraction script
set out_dir {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-26_22-41-51_eco_rank1_lutupgrade/10_phase7_validation}
file mkdir $out_dir


proc csv_escape {s} {
    set s [string trim $s]
    if {[regexp {[,\"\n\r]} $s]} {
        set s [string map [list "\"" "\"\""] $s]
        return "\"$s\""
    }
    return $s
}

proc obj_name {obj} {
    if {[catch {set n [get_property NAME $obj]}]} {
        return [string trim $obj]
    }
    if {$n eq ""} {
        return [string trim $obj]
    }
    return $n
}

proc safe_get {obj prop} {
    if {[catch {set v [get_property $prop $obj]}]} {
        return ""
    }
    return $v
}

proc write_timing_paths_csv {label out_subdir} {
    set csv [file join $out_subdir "${label}_timing_paths.csv"]
    set cf [open $csv w]
    puts $cf "path_index,slack_ns,datapath_delay_ns,logic_delay_ns,route_delay_ns,startpoint_pin,endpoint_pin,startpoint_cell,endpoint_cell"

    set paths [get_timing_paths -max_paths 10 -nworst 10 -setup]

    set idx 0
    foreach p $paths {
        set slack [safe_get $p SLACK]
        set datapath [safe_get $p DATAPATH_DELAY]
        set logic [safe_get $p LOGIC_DELAY]
        set route [safe_get $p ROUTE_DELAY]
        set sp [safe_get $p STARTPOINT_PIN]
        set ep [safe_get $p ENDPOINT_PIN]
        set sc [safe_get $p STARTPOINT_CELL]
        set ec [safe_get $p ENDPOINT_CELL]

        puts $cf "$idx,[csv_escape $slack],[csv_escape $datapath],[csv_escape $logic],[csv_escape $route],[csv_escape $sp],[csv_escape $ep],[csv_escape $sc],[csv_escape $ec]"
        incr idx
    }

    close $cf
}

proc check_edge {label edge_name source_pin sink_pin output_net out_subdir edge_csv} {
    set source_exists 0
    set sink_exists 0
    set connected 0
    set sink_net ""
    set driver_names ""
    set detail ""

    set srcp [get_pins -quiet $source_pin]
    if {[llength $srcp] == 1} {
        set source_exists 1
    }

    if {$sink_pin ne ""} {
        set sinkp [get_pins -quiet $sink_pin]
        if {[llength $sinkp] == 1} {
            set sink_exists 1
            set nets [get_nets -quiet -of_objects $sinkp]
            set net_names {}
            foreach n $nets { lappend net_names [obj_name $n] }

            if {[llength $net_names] > 0} {
                set sink_net [lindex $net_names 0]
                set n [get_nets -quiet $sink_net]
                set drivers [get_pins -quiet -of_objects $n -filter {DIRECTION == OUT}]
                set dnames {}
                foreach d $drivers { lappend dnames [obj_name $d] }
                set driver_names [join $dnames "|"]

                if {[lsearch -exact $dnames $source_pin] >= 0} {
                    set connected 1
                }
            }
        }

        set timing_file [file join $out_subdir "${label}_${edge_name}_timing.rpt"]

        if {$source_exists && $sink_exists} {
            if {[catch {report_timing -from $srcp -to $sinkp -max_paths 1 -nworst 1 -file $timing_file} err]} {
                set detail "report_timing_failed:$err"
            } else {
                set detail "report_timing_written:$timing_file"
            }
        } else {
            set detail "missing_source_or_sink"
        }

    } else {
        # Output-net driver check.
        set sink_exists 1
        set sink_net $output_net

        set n [get_nets -quiet $output_net]
        if {[llength $n] == 1} {
            set drivers [get_pins -quiet -of_objects $n -filter {DIRECTION == OUT}]
            set dnames {}
            foreach d $drivers { lappend dnames [obj_name $d] }
            set driver_names [join $dnames "|"]

            if {[lsearch -exact $dnames $source_pin] >= 0} {
                set connected 1
            }
        }

        set detail "output_net_driver_check"
    }

    puts $edge_csv "[csv_escape $label],[csv_escape $edge_name],[csv_escape $source_pin],[csv_escape $sink_pin],[csv_escape $output_net],$source_exists,$sink_exists,$connected,[csv_escape $sink_net],[csv_escape $driver_names],[csv_escape $detail]"
}

proc analyze_design {label dcp edge_specs out_dir} {
    set out_subdir [file join $out_dir $label]
    file mkdir $out_subdir

    open_checkpoint $dcp

    report_route_status -file [file join $out_subdir "${label}_route_status.rpt"]
    report_drc -file [file join $out_subdir "${label}_drc.rpt"]
    report_timing_summary -file [file join $out_subdir "${label}_timing_summary.rpt"]
    report_timing -max_paths 10 -nworst 10 -file [file join $out_subdir "${label}_worst_paths.rpt"]

    write_timing_paths_csv $label $out_subdir

    set ecsv_path [file join $out_subdir "${label}_edge_checks.csv"]
    set ecf [open $ecsv_path w]
    puts $ecf "label,edge_name,source_pin,sink_pin,output_net,source_exists,sink_exists,connected,sink_net,driver_names,detail"

    foreach spec $edge_specs {
        lassign $spec edge_name source_pin sink_pin output_net
        check_edge $label $edge_name $source_pin $sink_pin $output_net $out_subdir $ecf
    }

    close $ecf
    close_design
}

set edge_specs {
  {old_selected_edge} {f[108]_INST_0_i_7/O} {f[108]_INST_0_i_6/I0} {}
  {new_internal_f_108__INST_0_i_7_to_root_I0} {f[108]_INST_0_i_7/O} {f[108]_INST_0_i_8/I0} {}
  {new_internal_f_108__INST_0_i_6_to_root_I1} {f[108]_INST_0_i_6/O} {f[108]_INST_0_i_8/I1} {}
  {new_output_driver_to_p_124_in} {f[108]_INST_0_i_8/O} {} {p_124_in}
}

analyze_design baseline {/home/cian/Masterproef/project/results/run_lut_insertion/TestDirectory/baseline_impl/checkpoints/post_route_timingexp.dcp} $edge_specs $out_dir
analyze_design eco {/home/cian/Masterproef/project/results/general_flow_runs/2026-04-26_22-41-51_eco_rank1_lutupgrade/09_phase6c_fresh_route/phase6b2_eco_routed_fresh.dcp} $edge_specs $out_dir
puts "PHASE7_VIVADO_EXTRACTION_DONE"
puts "Output dir: $out_dir"
