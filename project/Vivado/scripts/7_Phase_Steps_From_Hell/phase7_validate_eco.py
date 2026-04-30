#!/usr/bin/env python3
"""
FASE 7 — ECO delay/timing/effect validatie.

Doel:
  Vergelijk baseline DCP met ECO DCP:
    - route status
    - DRC
    - timing summary
    - worst timing paths
    - oude selected edge
    - nieuwe replacement edges
    - output-driver check

Gebruik:
  python3 phase7_validate_eco.py \
    <baseline.dcp> \
    <eco.dcp> \
    <phase1_lut_timing_edges.json> \
    <phase3_window_info.json> \
    <phase5b2_fast_selected_candidate.json> \
    <out_dir> \
    [--run-vivado]

Voorbeeld:
  python3 ~/Masterproef/project/Vivado/scripts/phase7_validate_eco.py \
    ~/Masterproef/project/results/run_lut_insertion/TestDirectory/baseline_impl/checkpoints/post_route_timingexp.dcp \
    ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase6b2_full_eco_patch1/phase6b2_eco_routed.dcp \
    ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase1_timing_edges/phase1_lut_timing_edges.json \
    ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase3_window_info/phase3_window_info.json \
    ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase5b2_fast_100000/phase5b2_fast_selected_candidate.json \
    ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase7_validation \
    --run-vivado
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def tcl_brace(s):
    s = str(s)
    s = s.replace("\\", "\\\\").replace("}", "\\}")
    return "{" + s + "}"


def read_json(path):
    with open(path, "r") as f:
        return json.load(f)


def parse_route_status(path):
    result = {
        "fully_routed_nets": None,
        "nets_with_routing_errors": None,
        "nets_with_unrouted_pins": None,
    }

    if not os.path.exists(path):
        return result

    txt = Path(path).read_text(errors="ignore")

    m = re.search(r"# of fully routed nets\.*\s*:\s*(\d+)", txt)
    if m:
        result["fully_routed_nets"] = int(m.group(1))

    m = re.search(r"# of nets with routing errors\.*\s*:\s*(\d+)", txt)
    if m:
        result["nets_with_routing_errors"] = int(m.group(1))

    m = re.search(r"# of nets with some unrouted pins\.*\s*:\s*(\d+)", txt)
    if m:
        result["nets_with_unrouted_pins"] = int(m.group(1))

    return result


def parse_drc(path):
    result = {
        "violations_found": None,
        "error_rules": [],
        "critical_warning_rules": [],
        "raw_error_count": 0,
    }

    if not os.path.exists(path):
        return result

    txt = Path(path).read_text(errors="ignore")

    m = re.search(r"Violations found:\s*(\d+)", txt)
    if m:
        result["violations_found"] = int(m.group(1))

    # Table lines look like:
    # | NSTD-1 | Critical Warning | ...
    for line in txt.splitlines():
        m = re.match(r"\|\s*([A-Z0-9-]+)\s*\|\s*(Error|Critical Warning)\s*\|", line)
        if not m:
            continue

        rule = m.group(1)
        sev = m.group(2)

        if sev == "Error":
            result["error_rules"].append(rule)
        elif sev == "Critical Warning":
            result["critical_warning_rules"].append(rule)

    result["raw_error_count"] = len(result["error_rules"])
    result["error_rules"] = sorted(set(result["error_rules"]))
    result["critical_warning_rules"] = sorted(set(result["critical_warning_rules"]))

    return result


def parse_timing_summary(path):
    result = {
        "wns": None,
        "tns": None,
        "setup_failing_endpoints": None,
    }

    if not os.path.exists(path):
        return result

    txt = Path(path).read_text(errors="ignore")

    # Common compact line:
    # Setup : 128 Failing Endpoints, Worst Slack -8.312ns, Total Violation -680.539ns
    m = re.search(
        r"Setup\s*:\s*(\d+)\s+Failing Endpoints,\s*Worst Slack\s*(-?\d+(?:\.\d+)?)ns,\s*Total Violation\s*(-?\d+(?:\.\d+)?)ns",
        txt,
    )

    if m:
        result["setup_failing_endpoints"] = int(m.group(1))
        result["wns"] = float(m.group(2))
        result["tns"] = float(m.group(3))
        return result

    # Fallback: search Worst Slack and Total Violation separately.
    m = re.search(r"Worst Slack\s+(-?\d+(?:\.\d+)?)ns", txt)
    if m:
        result["wns"] = float(m.group(1))

    m = re.search(r"Total Violation\s+(-?\d+(?:\.\d+)?)ns", txt)
    if m:
        result["tns"] = float(m.group(1))

    return result


def parse_worst_path(path):
    result = {
        "slack": None,
        "data_path_delay": None,
        "logic_delay": None,
        "route_delay": None,
    }

    if not os.path.exists(path):
        return result

    txt = Path(path).read_text(errors="ignore")

    m = re.search(r"Slack\s+\(VIOLATED\)\s*:\s*(-?\d+(?:\.\d+)?)ns", txt)
    if not m:
        m = re.search(r"Slack\s*:\s*(-?\d+(?:\.\d+)?)ns", txt)

    if m:
        result["slack"] = float(m.group(1))

    m = re.search(
        r"Data Path Delay:\s*(-?\d+(?:\.\d+)?)ns\s*\(logic\s*(-?\d+(?:\.\d+)?)ns.*?route\s*(-?\d+(?:\.\d+)?)ns",
        txt,
    )

    if m:
        result["data_path_delay"] = float(m.group(1))
        result["logic_delay"] = float(m.group(2))
        result["route_delay"] = float(m.group(3))

    return result


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def write_txt(path, lines):
    with open(path, "w") as f:
        for line in lines:
            f.write(str(line) + "\n")


def build_edges(phase1, phase3, candidate):
    selected = phase1["selected_edge"]

    edges = []

    # Old critical edge from phase 1.
    edges.append({
        "edge_name": "old_selected_edge",
        "source_pin": selected["source_pin"],
        "sink_pin": selected["sink_pin"],
        "baseline_expected": "connected",
        "eco_expected": "disconnected",
    })

    # New internal edges from candidate root inputs.
    root = candidate["roles"]["root"]

    for inp in root["inputs"]:
        if "source_cell" in inp:
            source_pin = inp["source_cell"] + "/O"
            sink_pin = root["cell"] + "/" + inp["sink_pin"]

            edges.append({
                "edge_name": "new_internal_" + inp["source_cell"].replace("[", "_").replace("]", "_").replace("/", "_") + "_to_root_" + inp["sink_pin"],
                "source_pin": source_pin,
                "sink_pin": sink_pin,
                "baseline_expected": "not_required",
                "eco_expected": "connected",
            })

    # Output edge check.
    boundary_outputs = phase3["boundary_outputs"]
    if len(boundary_outputs) == 1:
        old_output_net = boundary_outputs[0]["net"]
        new_driver = root["cell"] + "/O"

        edges.append({
            "edge_name": "new_output_driver_to_" + old_output_net,
            "source_pin": new_driver,
            "sink_pin": "",
            "baseline_expected": "not_required",
            "eco_expected": "driver_of_output_net",
            "output_net": old_output_net,
        })

    return edges


def generate_tcl(baseline_dcp, eco_dcp, edges, out_dir):
    tcl_path = os.path.join(out_dir, "phase7_extract_vivado.tcl")

    edge_lines = []
    for e in edges:
        edge_lines.append(
            "  "
            + tcl_brace(e["edge_name"])
            + " "
            + tcl_brace(e["source_pin"])
            + " "
            + tcl_brace(e.get("sink_pin", ""))
            + " "
            + tcl_brace(e.get("output_net", ""))
        )

    edge_list = "{\n" + "\n".join(edge_lines) + "\n}"

    with open(tcl_path, "w") as f:
        f.write("# Auto-generated FASE 7 Vivado extraction script\n")
        f.write(f"set out_dir {tcl_brace(out_dir)}\n")
        f.write("file mkdir $out_dir\n\n")

        f.write(r'''
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
''')

        f.write("\n")
        f.write(f"set edge_specs {edge_list}\n\n")
        f.write(f"analyze_design baseline {tcl_brace(baseline_dcp)} $edge_specs $out_dir\n")
        f.write(f"analyze_design eco {tcl_brace(eco_dcp)} $edge_specs $out_dir\n")
        f.write('puts "PHASE7_VIVADO_EXTRACTION_DONE"\n')
        f.write('puts "Output dir: $out_dir"\n')

    return tcl_path


def compare_results(out_dir):
    baseline_dir = os.path.join(out_dir, "baseline")
    eco_dir = os.path.join(out_dir, "eco")

    baseline = {
        "route_status": parse_route_status(os.path.join(baseline_dir, "baseline_route_status.rpt")),
        "drc": parse_drc(os.path.join(baseline_dir, "baseline_drc.rpt")),
        "timing_summary": parse_timing_summary(os.path.join(baseline_dir, "baseline_timing_summary.rpt")),
        "worst_path": parse_worst_path(os.path.join(baseline_dir, "baseline_worst_paths.rpt")),
        "edge_checks": read_csv(os.path.join(baseline_dir, "baseline_edge_checks.csv")),
        "timing_paths": read_csv(os.path.join(baseline_dir, "baseline_timing_paths.csv")),
    }

    eco = {
        "route_status": parse_route_status(os.path.join(eco_dir, "eco_route_status.rpt")),
        "drc": parse_drc(os.path.join(eco_dir, "eco_drc.rpt")),
        "timing_summary": parse_timing_summary(os.path.join(eco_dir, "eco_timing_summary.rpt")),
        "worst_path": parse_worst_path(os.path.join(eco_dir, "eco_worst_paths.rpt")),
        "edge_checks": read_csv(os.path.join(eco_dir, "eco_edge_checks.csv")),
        "timing_paths": read_csv(os.path.join(eco_dir, "eco_timing_paths.csv")),
    }

    b_wns = baseline["timing_summary"]["wns"]
    e_wns = eco["timing_summary"]["wns"]

    b_tns = baseline["timing_summary"]["tns"]
    e_tns = eco["timing_summary"]["tns"]

    delta_wns = None if b_wns is None or e_wns is None else e_wns - b_wns
    delta_tns = None if b_tns is None or e_tns is None else e_tns - b_tns

    b_route_errors = baseline["route_status"]["nets_with_routing_errors"]
    e_route_errors = eco["route_status"]["nets_with_routing_errors"]

    b_errors = set(baseline["drc"]["error_rules"])
    e_errors = set(eco["drc"]["error_rules"])

    # Ignore NSTD/UCIO as known baseline warnings if they are only critical warnings.
    new_error_rules = sorted(e_errors - b_errors)

    status = "UNKNOWN"

    if e_route_errors is not None and e_route_errors != 0:
        status = "FAIL_ROUTE_ERRORS"
    elif new_error_rules:
        status = "FAIL_NEW_DRC_ERRORS"
    elif delta_wns is not None and delta_wns > 0:
        status = "PASS_WNS_IMPROVED"
    elif delta_wns is not None and delta_wns == 0:
        status = "PASS_NO_WNS_CHANGE"
    elif delta_wns is not None and delta_wns < 0:
        status = "NEGATIVE_WNS_WORSE"
    else:
        status = "PASS_NEEDS_MANUAL_TIMING_REVIEW"

    comparison = {
        "phase": "FASE 7",
        "phase7_status": status,
        "baseline": baseline,
        "eco": eco,
        "delta": {
            "wns": delta_wns,
            "tns": delta_tns,
        },
        "new_drc_error_rules": new_error_rules,
    }

    write_json(os.path.join(out_dir, "phase7_comparison.json"), comparison)

    lines = []
    lines.append(f"phase7_status={status}")
    lines.append(f"baseline_wns={b_wns}")
    lines.append(f"eco_wns={e_wns}")
    lines.append(f"delta_wns={delta_wns}")
    lines.append(f"baseline_tns={b_tns}")
    lines.append(f"eco_tns={e_tns}")
    lines.append(f"delta_tns={delta_tns}")
    lines.append(f"baseline_route_errors={b_route_errors}")
    lines.append(f"eco_route_errors={e_route_errors}")
    lines.append(f"baseline_drc_errors={'|'.join(sorted(b_errors))}")
    lines.append(f"eco_drc_errors={'|'.join(sorted(e_errors))}")
    lines.append(f"new_drc_error_rules={'|'.join(new_error_rules)}")
    lines.append("")
    lines.append("baseline_edge_checks:")
    for r in baseline["edge_checks"]:
        lines.append(
            f"  {r.get('edge_name')} connected={r.get('connected')} "
            f"sink_net={r.get('sink_net')} drivers={r.get('driver_names')}"
        )
    lines.append("")
    lines.append("eco_edge_checks:")
    for r in eco["edge_checks"]:
        lines.append(
            f"  {r.get('edge_name')} connected={r.get('connected')} "
            f"sink_net={r.get('sink_net')} drivers={r.get('driver_names')}"
        )

    write_txt(os.path.join(out_dir, "phase7_summary.txt"), lines)

    return comparison


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline_dcp")
    ap.add_argument("eco_dcp")
    ap.add_argument("phase1_json")
    ap.add_argument("phase3_json")
    ap.add_argument("candidate_json")
    ap.add_argument("out_dir")
    ap.add_argument("--run-vivado", action="store_true")
    ap.add_argument("--vivado", default="vivado")
    args = ap.parse_args()

    baseline_dcp = os.path.abspath(args.baseline_dcp)
    eco_dcp = os.path.abspath(args.eco_dcp)
    phase1_json = os.path.abspath(args.phase1_json)
    phase3_json = os.path.abspath(args.phase3_json)
    candidate_json = os.path.abspath(args.candidate_json)
    out_dir = os.path.abspath(args.out_dir)

    for p in [baseline_dcp, eco_dcp, phase1_json, phase3_json, candidate_json]:
        if not os.path.exists(p):
            fail(f"bestand bestaat niet: {p}")

    os.makedirs(out_dir, exist_ok=True)

    phase1 = read_json(phase1_json)
    phase3 = read_json(phase3_json)
    candidate = read_json(candidate_json)

    edges = build_edges(phase1, phase3, candidate)

    with open(os.path.join(out_dir, "phase7_edge_specs.json"), "w") as f:
        json.dump(edges, f, indent=2)

    tcl_path = generate_tcl(baseline_dcp, eco_dcp, edges, out_dir)

    print(f"PHASE7_TCL_CREATED: {tcl_path}")

    if args.run_vivado:
        print("[INFO] Running Vivado extraction...")
        cmd = [args.vivado, "-mode", "batch", "-source", tcl_path]
        print("[CMD] " + " ".join(cmd))

        proc = subprocess.run(cmd, cwd=out_dir)
        if proc.returncode != 0:
            fail(f"Vivado extraction failed with return code {proc.returncode}")

        comparison = compare_results(out_dir)

        print("PHASE7_COMPARE_DONE")
        print(f"Summary: {os.path.join(out_dir, 'phase7_summary.txt')}")
        print(f"JSON   : {os.path.join(out_dir, 'phase7_comparison.json')}")
        print(f"Status : {comparison['phase7_status']}")
    else:
        print("Run Vivado manually with:")
        print(f"vivado -mode batch -source {tcl_path}")
        print("Then run this script again with --run-vivado, or manually inspect reports.")


if __name__ == "__main__":
    main()
