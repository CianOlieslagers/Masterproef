#!/usr/bin/env python3
"""
General ECO Flow Orchestrator — v0.2

Deze versie doet:
  - config laden
  - centrale outputdirectory maken
  - phase0 baseline precheck
  - phase1 timing edge extraction
  - phase2 window extraction
  - phase3 window info extraction
  - phase4 truth table generation
  - status + final_summary bijwerken

Later:
  - phase5 candidate search
  - phase6 ECO apply
  - phase7 timing validation
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is niet geïnstalleerd.", file=sys.stderr)
    print("Installeer met: python3 -m pip install --user pyyaml", file=sys.stderr)
    sys.exit(1)


PHASE_DIRS = {
    "config": "00_config",
    "logs": "00_logs",
    "status": "00_status",
    "phase1": "01_phase1_timing_edges",
    "phase2": "02_phase2_window",
    "phase3": "03_phase3_window_info",
    "phase4": "04_phase4_truth_table",
    "phase5": "05_phase5_candidate_search",
    "phase6a": "06_phase6a_manifest",
    "phase6b_stage1": "07_phase6b_stage1",
    "phase6b_rewire": "08_phase6b_rewire",
    "phase6c": "09_phase6c_fresh_route",
    "phase7": "10_phase7_validation",
}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def safe_name(name):
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return name.strip("_")


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def write_phase_status(path, rows):
    fieldnames = ["phase", "status", "detail"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def append_log(path, text):
    with open(path, "a") as f:
        f.write(text.rstrip() + "\n")


def apply_phase1_candidate_rank(phase1_json_path, candidate_rank, log_fn=print):
    """
    Selecteert een unieke LUT-to-LUT edge uit phase1_lut_timing_edges.json.

    Belangrijk:
    - De raw candidates kunnen duplicaten bevatten, omdat dezelfde edge in meerdere timing paths zit.
    - Daarom ranken we op unieke (source_pin, sink_pin, net).
    - candidate_rank is 1-based.
    """
    import json

    with open(phase1_json_path, "r") as f:
        data = json.load(f)

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"No candidates found in {phase1_json_path}")

    unique_candidates = []
    seen = set()

    for raw_index, cand in enumerate(candidates, start=1):
        key = (
            cand.get("source_pin", ""),
            cand.get("sink_pin", ""),
            cand.get("net", ""),
        )

        if key in seen:
            continue

        seen.add(key)

        cand2 = dict(cand)
        cand2["raw_candidate_index"] = raw_index
        cand2["unique_candidate_rank"] = len(unique_candidates) + 1
        unique_candidates.append(cand2)

    if candidate_rank < 1 or candidate_rank > len(unique_candidates):
        raise RuntimeError(
            f"candidate_rank={candidate_rank} is out of range. "
            f"Unique candidates available: {len(unique_candidates)}"
        )

    selected = unique_candidates[candidate_rank - 1]

    data["selected_edge"] = selected
    data["candidate_rank_requested"] = candidate_rank
    data["candidate_rank_mode"] = "unique_edge_by_source_sink_net"
    data["num_unique_lut_to_lut_candidates"] = len(unique_candidates)

    with open(phase1_json_path, "w") as f:
        json.dump(data, f, indent=2)

    log_fn(
        "[phase1] selected unique candidate_rank="
        f"{candidate_rank}/{len(unique_candidates)}: "
        f"{selected.get('source_pin')} -> {selected.get('sink_pin')} "
        f"net={selected.get('net')} "
        f"delay_ps={selected.get('interconnect_delay_ps')}"
    )

    return selected


def run_cmd(cmd, cwd, log_path, commands_log_path, allow_fail=False, timeout_sec=None):
    import time
    import signal

    append_log(commands_log_path, " ".join(cmd))
    append_log(log_path, f"\n[CMD] {' '.join(cmd)}\n")

    print(f"[CMD] {' '.join(cmd)}", flush=True)

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
        preexec_fn=os.setsid,
    )

    start = time.time()
    output_lines = []

    try:
        while True:
            line = proc.stdout.readline()

            if line:
                print(line.rstrip(), flush=True)
                output_lines.append(line)
                append_log(log_path, line.rstrip())

            if proc.poll() is not None:
                # flush remaining output
                rest = proc.stdout.read()
                if rest:
                    print(rest, flush=True)
                    output_lines.append(rest)
                    append_log(log_path, rest)
                break

            if timeout_sec is not None and (time.time() - start) > timeout_sec:
                append_log(log_path, f"[TIMEOUT] command exceeded {timeout_sec}s")
                print(f"[TIMEOUT] command exceeded {timeout_sec}s", flush=True)

                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception:
                    proc.terminate()

                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        proc.kill()

                raise RuntimeError(f"Command timed out after {timeout_sec}s: {' '.join(cmd)}")

    except KeyboardInterrupt:
        print("[INTERRUPT] stopping child process...", flush=True)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.terminate()
        raise

    rc = proc.returncode
    output_text = "".join(output_lines)

    if rc != 0 and not allow_fail:
        tail = "\n".join(output_text.splitlines()[-80:])
        raise RuntimeError(
            f"Command failed with return code {rc}: {' '.join(cmd)}\n"
            f"--- output tail ---\n{tail}\n--- end output tail ---"
        )

    return rc, output_text


def is_transient_vivado_crash(msg):
    patterns = [
        "return code 139",
        "Segmentation fault",
        "segmentation fault",
        "segfault",
        "core dumped",
        "Vivado extraction failed with return code 139",
    ]
    return any(p in msg for p in patterns)


def run_cmd_retry(cmd, cwd, log_path, commands_log_path, timeout_sec=None, retries=2):
    last_error = None

    for attempt in range(1, retries + 2):
        try:
            append_log(log_path, f"[RETRY_WRAPPER] attempt {attempt}/{retries + 1}")
            print(f"[RETRY_WRAPPER] attempt {attempt}/{retries + 1}", flush=True)

            return run_cmd(
                cmd,
                cwd=cwd,
                log_path=log_path,
                commands_log_path=commands_log_path,
                timeout_sec=timeout_sec,
            )

        except RuntimeError as e:
            last_error = e
            msg = str(e)

            if is_transient_vivado_crash(msg) and attempt <= retries:
                append_log(
                    log_path,
                    f"[WARN] Transient Vivado crash detected. Retrying attempt {attempt + 1}.",
                )
                print(
                    f"[WARN] Transient Vivado crash detected. Retrying attempt {attempt + 1}.",
                    flush=True,
                )
                continue

            raise

    raise last_error

def parse_route_status(report_path):
    result = {
        "exists": os.path.exists(report_path),
        "fully_routed_nets": None,
        "nets_with_routing_errors": None,
    }

    if not result["exists"]:
        return result

    txt = Path(report_path).read_text(errors="ignore")

    m = re.search(r"# of fully routed nets\.*\s*:\s*(\d+)", txt)
    if m:
        result["fully_routed_nets"] = int(m.group(1))

    m = re.search(r"# of nets with routing errors\.*\s*:\s*(\d+)", txt)
    if m:
        result["nets_with_routing_errors"] = int(m.group(1))

    return result


def parse_drc(report_path):
    result = {
        "exists": os.path.exists(report_path),
        "error_rules": [],
        "critical_warning_rules": [],
    }

    if not result["exists"]:
        return result

    txt = Path(report_path).read_text(errors="ignore")

    for line in txt.splitlines():
        m = re.match(r"\|\s*([A-Z0-9-]+)\s*\|\s*(Error|Critical Warning)\s*\|", line)
        if not m:
            continue

        rule = m.group(1)
        severity = m.group(2)

        if severity == "Error":
            result["error_rules"].append(rule)
        elif severity == "Critical Warning":
            result["critical_warning_rules"].append(rule)

    result["error_rules"] = sorted(set(result["error_rules"]))
    result["critical_warning_rules"] = sorted(set(result["critical_warning_rules"]))

    return result


def parse_timing_summary(report_path):
    result = {
        "exists": os.path.exists(report_path),
        "wns": None,
        "tns": None,
        "setup_failing_endpoints": None,
    }

    if not result["exists"]:
        return result

    txt = Path(report_path).read_text(errors="ignore")

    m = re.search(
        r"Setup\s*:\s*(\d+)\s+Failing Endpoints,\s*Worst Slack\s*(-?\d+(?:\.\d+)?)ns,\s*Total Violation\s*(-?\d+(?:\.\d+)?)ns",
        txt,
    )

    if m:
        result["setup_failing_endpoints"] = int(m.group(1))
        result["wns"] = float(m.group(2))
        result["tns"] = float(m.group(3))

    return result


def create_run_dir(config, config_path):
    run_cfg = config["run"]

    output_root = os.path.abspath(run_cfg["output_root"])
    run_name = safe_name(run_cfg["name"])

    if run_cfg.get("timestamped_output", True):
        run_dir_name = f"{now_stamp()}_{run_name}"
    else:
        run_dir_name = run_name

    run_dir = os.path.join(output_root, run_dir_name)
    ensure_dir(run_dir)

    dirs = {}

    for key, sub in PHASE_DIRS.items():
        p = os.path.join(run_dir, sub)
        ensure_dir(p)
        dirs[key] = p

    copied_config = os.path.join(dirs["config"], "config.yaml")
    shutil.copy2(config_path, copied_config)

    return run_dir, dirs, copied_config


def validate_basic_paths(config):
    checks = []

    def check_file(label, path):
        ok = os.path.isfile(path)
        checks.append({
            "phase": "precheck",
            "status": "PASS" if ok else "FAIL",
            "detail": f"{label}: {path}",
        })
        return ok

    def check_dir(label, path):
        ok = os.path.isdir(path)
        checks.append({
            "phase": "precheck",
            "status": "PASS" if ok else "FAIL",
            "detail": f"{label}: {path}",
        })
        return ok

    design = config["design"]
    tools = config["tools"]
    scripts = config.get("scripts", {})

    check_file("baseline_dcp", design["baseline_dcp"])
    check_dir("baseline_reports_dir", design["baseline_reports_dir"])
    check_file("rapidwright_jar", tools["rapidwright_jar"])
    check_dir("java_scripts_dir", tools["java_scripts_dir"])
    check_dir("vivado_scripts_dir", tools["vivado_scripts_dir"])

    # Phase scripts
    for key in ["phase1_tcl", "phase2_tcl", "phase3_tcl", "phase4_py", "phase5b2_fast_py", "phase6a_py",
    "phase6b2_rewire_py","phase7_py"]:
        if key in scripts:
            check_file(key, scripts[key])
        else:
            checks.append({
                "phase": "precheck",
                "status": "FAIL",
                "detail": f"scripts.{key} missing in config",
            })

    return checks


def phase0_check_baseline(config, dirs):
    rows = []

    reports_dir = config["design"]["baseline_reports_dir"]

    route_report = os.path.join(reports_dir, "post_route_status_timingexp.rpt")
    drc_report = os.path.join(reports_dir, "post_route_drc_timingexp.rpt")
    timing_report = os.path.join(reports_dir, "post_route_timing_timingexp.rpt")

    route = parse_route_status(route_report)
    drc = parse_drc(drc_report)
    timing = parse_timing_summary(timing_report)

    phase0_dir = os.path.join(dirs["status"], "phase0")
    ensure_dir(phase0_dir)

    summary = {
        "phase": "FASE 0",
        "route_report": route_report,
        "drc_report": drc_report,
        "timing_report": timing_report,
        "route": route,
        "drc": drc,
        "timing": timing,
    }

    write_json(os.path.join(phase0_dir, "phase0_summary.json"), summary)

    if not route["exists"]:
        rows.append({"phase": "phase0", "status": "FAIL", "detail": f"route report missing: {route_report}"})
    elif route["nets_with_routing_errors"] == 0:
        rows.append({"phase": "phase0", "status": "PASS", "detail": "route_errors=0"})
    else:
        rows.append({"phase": "phase0", "status": "FAIL", "detail": f"route_errors={route['nets_with_routing_errors']}"})

    if not drc["exists"]:
        rows.append({"phase": "phase0", "status": "FAIL", "detail": f"drc report missing: {drc_report}"})
    elif len(drc["error_rules"]) == 0:
        rows.append({"phase": "phase0", "status": "PASS", "detail": "no DRC Error rules"})
    else:
        rows.append({"phase": "phase0", "status": "FAIL", "detail": f"DRC errors={drc['error_rules']}"})

    if not timing["exists"]:
        rows.append({"phase": "phase0", "status": "FAIL", "detail": f"timing report missing: {timing_report}"})
    elif timing["wns"] is not None:
        rows.append({"phase": "phase0", "status": "PASS", "detail": f"WNS={timing['wns']}, TNS={timing['tns']}"})
    else:
        rows.append({"phase": "phase0", "status": "WARN", "detail": "timing report exists but WNS/TNS not parsed"})

    return rows


def require_file(path, phase, rows, label):
    if os.path.exists(path):
        rows.append({"phase": phase, "status": "PASS", "detail": f"{label}: {path}"})
        return True

    rows.append({"phase": phase, "status": "FAIL", "detail": f"missing {label}: {path}"})
    return False


def load_json_if_exists(path):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def phase1_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase1"

    if not config.get("phase1", {}).get("enabled", True):
        rows.append({"phase": phase, "status": "SKIP", "detail": "disabled"})
        return rows

    script = config["scripts"]["phase1_tcl"]
    baseline_dcp = config["design"]["baseline_dcp"]
    out_dir = dirs["phase1"]

    top_paths = str(config["phase1"].get("top_paths", 10))
    nworst = str(config["phase1"].get("nworst", 10))

    cmd= [
        config["tools"].get("vivado_bin", "vivado"),
        "-mode", "batch",
        "-source", script,
        "-tclargs",
        baseline_dcp,
        out_dir,
        top_paths,
        nworst,
    ]

    run_cmd_retry(
        cmd,
        cwd=out_dir,
        log_path=log_path,
        commands_log_path=commands_log,
        timeout_sec=config.get("timeouts", {}).get("phase1_sec", 1800),
        retries=config.get("tools", {}).get("vivado_retries", 3),
    )
    
    phase1_json = os.path.join(out_dir, "phase1_lut_timing_edges.json")
    phase1_csv = os.path.join(out_dir, "phase1_lut_timing_edges.csv")

    # --- NIEUW: Rank toepassen vóór de file-checks en de volgende fase ---
    if os.path.exists(phase1_json):
        candidate_rank = int(config.get("phase1", {}).get("candidate_rank", 1))
        
        def local_log(msg):
            print(msg, flush=True)
            append_log(log_path, msg)

        apply_phase1_candidate_rank(
            phase1_json,
            candidate_rank,
            log_fn=local_log
        )
    # ----------------------------------------------------------------------

    require_file(phase1_json, phase, rows, "phase1_json")
    require_file(phase1_csv, phase, rows, "phase1_csv")
    data = load_json_if_exists(phase1_json)
    if data:
        status = data.get("phase1_status", "")
        n = data.get("num_lut_to_lut_candidates", "")
        selected = data.get("selected_edge", {})
        rows.append({
            "phase": phase,
            "status": "PASS" if status.startswith("PASS") else "WARN",
            "detail": f"status={status}, candidates={n}, selected_net={selected.get('net', '')}",
        })

    return rows


def phase2_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase2"

    phase2_cfg = config.get("phase2", {})

    if not phase2_cfg.get("enabled", True):
        rows.append({"phase": phase, "status": "SKIP", "detail": "disabled"})
        return rows

    script = config["scripts"]["phase2_tcl"]
    baseline_dcp = config["design"]["baseline_dcp"]
    phase1_json = os.path.join(dirs["phase1"], "phase1_lut_timing_edges.json")
    out_dir = dirs["phase2"]

    max_luts = str(phase2_cfg.get("max_luts", 5))
    max_boundary_inputs = str(phase2_cfg.get("max_boundary_inputs", 12))
    max_boundary_outputs = str(phase2_cfg.get("max_boundary_outputs", 2))

    # Nieuwe optionele Phase 2 windowing-parameters.
    # Backward compatible: als deze niet in de config staan,
    # blijft het oude gedrag behouden.
    window_mode = str(phase2_cfg.get("window_mode", "sink_direct_fanin"))
    target_luts = str(phase2_cfg.get("target_luts", phase2_cfg.get("max_luts", 5)))
    max_growth_iterations = str(phase2_cfg.get("max_growth_iterations", 50))

    cmd = [
        config["tools"].get("vivado_bin", "vivado"),
        "-mode", "batch",
        "-source", script,
        "-tclargs",
        baseline_dcp,
        phase1_json,
        out_dir,
        max_luts,
        max_boundary_inputs,
        max_boundary_outputs,
        window_mode,
        target_luts,
        max_growth_iterations,
    ]

    run_cmd_retry(
        cmd,
        cwd=out_dir,
        log_path=log_path,
        commands_log_path=commands_log,
        timeout_sec=config.get("timeouts", {}).get("phase2_sec", 1800),
        retries=config.get("tools", {}).get("vivado_retries", 3),
    )

    phase2_json = os.path.join(out_dir, "phase2_window.json")
    summary = os.path.join(out_dir, "phase2_window_summary.txt")
    checks = os.path.join(out_dir, "validation_checks.csv")
    growth_trace = os.path.join(out_dir, "growth_trace.csv")

    require_file(phase2_json, phase, rows, "phase2_window_json")
    require_file(summary, phase, rows, "phase2_summary")
    require_file(checks, phase, rows, "phase2_checks")

    # growth_trace bestaat alleen bij de gepatchte/new Phase 2.
    # Daarom niet hard failen als het ontbreekt, maar wel rapporteren.
    if os.path.exists(growth_trace):
        rows.append({
            "phase": phase,
            "status": "PASS",
            "detail": "growth_trace_present",
        })
    else:
        rows.append({
            "phase": phase,
            "status": "WARN",
            "detail": "growth_trace_missing_old_phase2_or_no_growth_trace_written",
        })

    if os.path.exists(summary):
        txt = Path(summary).read_text(errors="ignore")

        m = re.search(r"phase2_status=(.*)", txt)
        status = m.group(1).strip() if m else "UNKNOWN"

        m_num_luts = re.search(r"num_luts=(.*)", txt)
        num_luts = m_num_luts.group(1).strip() if m_num_luts else "?"

        m_boundary_inputs = re.search(r"num_boundary_inputs=(.*)", txt)
        num_boundary_inputs = m_boundary_inputs.group(1).strip() if m_boundary_inputs else "?"

        m_boundary_outputs = re.search(r"num_boundary_outputs=(.*)", txt)
        num_boundary_outputs = m_boundary_outputs.group(1).strip() if m_boundary_outputs else "?"

        m_mode = re.search(r"window_mode=(.*)", txt)
        effective_window_mode = m_mode.group(1).strip() if m_mode else window_mode

        rows.append({
            "phase": phase,
            "status": "PASS" if status.startswith("PASS") else "WARN",
            "detail": (
                f"{status}; "
                f"mode={effective_window_mode}; "
                f"num_luts={num_luts}; "
                f"boundary_inputs={num_boundary_inputs}; "
                f"boundary_outputs={num_boundary_outputs}; "
                f"target_luts={target_luts}; "
                f"max_luts={max_luts}"
            ),
        })

    return rows

def phase3_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase3"

    if not config.get("phase3", {}).get("enabled", True):
        rows.append({"phase": phase, "status": "SKIP", "detail": "disabled"})
        return rows

    script = config["scripts"]["phase3_tcl"]
    baseline_dcp = config["design"]["baseline_dcp"]
    phase2_dir = dirs["phase2"]
    out_dir = dirs["phase3"]

    cmd = [
    config["tools"].get("vivado_bin", "vivado"),
    "-mode", "batch",
    "-source", script,
    "-tclargs",
    baseline_dcp,
    phase2_dir,
    out_dir,
    ]
 
    run_cmd_retry(
        cmd,
        cwd=out_dir,
        log_path=log_path,
        commands_log_path=commands_log,
        timeout_sec=config.get("timeouts", {}).get("phase3_sec", 1800),
        retries=config.get("tools", {}).get("vivado_retries", 3),
    )
    phase3_json = os.path.join(out_dir, "phase3_window_info.json")
    summary = os.path.join(out_dir, "phase3_summary.txt")
    checks = os.path.join(out_dir, "validation_checks.csv")

    require_file(phase3_json, phase, rows, "phase3_window_info_json")
    require_file(summary, phase, rows, "phase3_summary")
    require_file(checks, phase, rows, "phase3_checks")

    data = load_json_if_exists(phase3_json)
    if data:
        status = data.get("phase3_status", "")
        rows.append({
            "phase": phase,
            "status": "PASS" if status == "PASS" else "WARN",
            "detail": f"status={status}, num_luts={data.get('num_luts', '')}, inputs={data.get('num_boundary_inputs', '')}",
        })

    return rows


def phase4_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase4"

    if not config.get("phase4", {}).get("enabled", True):
        rows.append({"phase": phase, "status": "SKIP", "detail": "disabled"})
        return rows

    script = config["scripts"]["phase4_py"]
    phase3_json = os.path.join(dirs["phase3"], "phase3_window_info.json")
    out_dir = dirs["phase4"]

    cmd = [
        "python3",
        script,
        phase3_json,
        out_dir,
    ]

    run_cmd_retry(
    cmd,
    cwd=out_dir,
    log_path=log_path,
    commands_log_path=commands_log,
    timeout_sec=config.get("timeouts", {}).get("phase4_sec", 1800),
    retries=config.get("tools", {}).get("vivado_retries", 3),
    )


    compact = os.path.join(out_dir, "truth_table_compact.json")
    truth_csv = os.path.join(out_dir, "truth_table.csv")
    summary = os.path.join(out_dir, "phase4_summary.txt")
    checks = os.path.join(out_dir, "phase4_validation_checks.csv")

    require_file(compact, phase, rows, "truth_table_compact_json")
    require_file(truth_csv, phase, rows, "truth_table_csv")
    require_file(summary, phase, rows, "phase4_summary")
    require_file(checks, phase, rows, "phase4_checks")

    data = load_json_if_exists(compact)
    if data:
        status = data.get("phase4_status", "")
        rows.append({
            "phase": phase,
            "status": "PASS" if status == "PASS" else "WARN",
            "detail": f"status={status}, rows={data.get('num_truth_table_rows', '')}, inputs={data.get('num_boundary_inputs', '')}",
        })

    return rows



def phase5_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase5"

    if not config.get("phase5", {}).get("enabled", True):
        rows.append({"phase": phase, "status": "SKIP", "detail": "disabled"})
        return rows

    mode = config["phase5"].get("mode", "root_free_lut_upgrade_fast")

    if mode != "root_free_lut_upgrade_fast":
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": f"unsupported phase5 mode: {mode}",
        })
        return rows

    script = config["scripts"]["phase5b2_fast_py"]

    phase3_json = os.path.join(dirs["phase3"], "phase3_window_info.json")
    truth_table_json = os.path.join(dirs["phase4"], "truth_table_compact.json")
    out_dir = dirs["phase5"]

    top_templates_to_check = str(config["phase5"].get("top_templates_to_check", 100000))
    max_candidates_to_keep = str(config["phase5"].get("max_candidates_to_keep", 200))
    stop_on_first_improved = "1" if config["phase5"].get("stop_on_first_improved", True) else "0"

    cmd = [
        "python3",
        script,
        phase3_json,
        truth_table_json,
        out_dir,
        top_templates_to_check,
        max_candidates_to_keep,
        stop_on_first_improved,
    ]

    run_cmd_retry(
    cmd,
    cwd=out_dir,
    log_path=log_path,
    commands_log_path=commands_log,
    timeout_sec=config.get("timeouts", {}).get("phase5_sec", 1800),
    retries=config.get("tools", {}).get("vivado_retries", 3),
    )

    summary_txt = os.path.join(out_dir, "phase5b2_fast_summary.txt")
    summary_json = os.path.join(out_dir, "phase5b2_fast_summary.json")
    selected_json = os.path.join(out_dir, "phase5b2_fast_selected_candidate.json")
    candidates_csv = os.path.join(out_dir, "phase5b2_fast_candidates.csv")
    checks_csv = os.path.join(out_dir, "phase5b2_fast_validation_checks.csv")

    require_file(summary_txt, phase, rows, "phase5_summary_txt")
    require_file(summary_json, phase, rows, "phase5_summary_json")
    require_file(selected_json, phase, rows, "phase5_selected_candidate_json")
    require_file(candidates_csv, phase, rows, "phase5_candidates_csv")
    require_file(checks_csv, phase, rows, "phase5_checks_csv")

    data = load_json_if_exists(summary_json)

    if not data:
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": "phase5 summary JSON missing/unreadable",
        })
        return rows

    status = data.get("phase5b2_fast_status", "")
    exact_candidate_count = data.get("exact_candidate_count", 0)
    best_candidate_id = data.get("best_candidate_id", "")
    baseline_score = data.get("baseline_score", "")
    best_score = data.get("best_score_without_penalties", "")
    estimated_improvement = data.get("estimated_improvement", False)
    elapsed = data.get("elapsed_seconds", "")

    if status == "PASS_IMPROVED_ESTIMATE":
        rows.append({
            "phase": phase,
            "status": "PASS",
            "detail": (
                f"status={status}, candidate={best_candidate_id}, "
                f"exact_candidates={exact_candidate_count}, "
                f"baseline_score={baseline_score}, best_score={best_score}, "
                f"elapsed={elapsed}s"
            ),
        })
    elif status == "PASS_NO_ESTIMATED_IMPROVEMENT":
        if config["phase5"].get("require_estimated_improvement", True):
            rows.append({
                "phase": phase,
                "status": "FAIL",
                "detail": (
                    f"candidate found but no estimated improvement; "
                    f"status={status}, exact_candidates={exact_candidate_count}"
                ),
            })
        else:
            rows.append({
                "phase": phase,
                "status": "WARN",
                "detail": (
                    f"candidate found but no estimated improvement; "
                    f"status={status}, exact_candidates={exact_candidate_count}"
                ),
            })
    else:
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": (
                f"phase5 failed or no usable candidate; "
                f"status={status}, exact_candidates={exact_candidate_count}, "
                f"estimated_improvement={estimated_improvement}"
            ),
        })

    return rows




def phase6a_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase6a"

    if not config.get("phase6", {}).get("enabled", True):
        rows.append({"phase": phase, "status": "SKIP", "detail": "phase6 disabled"})
        return rows

    script = config["scripts"]["phase6a_py"]
    baseline_dcp = config["design"]["baseline_dcp"]
    phase3_json = os.path.join(dirs["phase3"], "phase3_window_info.json")
    candidate_json = os.path.join(dirs["phase5"], "phase5b2_fast_selected_candidate.json")
    out_dir = dirs["phase6a"]

    cmd = [
        "python3",
        script,
        baseline_dcp,
        phase3_json,
        candidate_json,
        out_dir,
    ]

    run_cmd_retry(
    cmd,
    cwd=out_dir,
    log_path=log_path,
    commands_log_path=commands_log,
    timeout_sec=config.get("timeouts", {}).get("phase6a_sec", 1800),
    retries=config.get("tools", {}).get("vivado_retries", 3),
    )

    manifest = os.path.join(out_dir, "phase6a_eco_manifest.json")
    summary = os.path.join(out_dir, "phase6a_summary.txt")
    ops = os.path.join(out_dir, "phase6a_operations.csv")
    rewires = os.path.join(out_dir, "phase6a_input_rewires.csv")
    tcl = os.path.join(out_dir, "phase6a_vivado_feasibility_check.tcl")

    require_file(manifest, phase, rows, "phase6a_manifest")
    require_file(summary, phase, rows, "phase6a_summary")
    require_file(ops, phase, rows, "phase6a_operations")
    require_file(rewires, phase, rows, "phase6a_input_rewires")
    require_file(tcl, phase, rows, "phase6a_feasibility_tcl")

    if config.get("phase6", {}).get("run_feasibility_check", True):
        cmd2 = [
            config["tools"].get("vivado_bin", "vivado"),
            "-mode", "batch",
            "-source", tcl,
        ]

        run_cmd_retry(
            cmd2,
            cwd=out_dir,
            log_path=log_path,
            commands_log_path=commands_log,
            timeout_sec=config.get("timeouts", {}).get("phase6a_sec", 1800),
            retries=config.get("tools", {}).get("vivado_retries", 3),
        )

        checks = os.path.join(out_dir, "phase6a_vivado_feasibility_checks.csv")
        require_file(checks, phase, rows, "phase6a_vivado_checks")

        if os.path.exists(checks):
            txt = Path(checks).read_text(errors="ignore")
            if ",FAIL," in txt:
                rows.append({
                    "phase": phase,
                    "status": "FAIL",
                    "detail": "Vivado feasibility contains FAIL",
                })
            else:
                rows.append({
                    "phase": phase,
                    "status": "PASS",
                    "detail": "manifest + Vivado feasibility PASS/WARN only",
                })
    else:
        rows.append({
            "phase": phase,
            "status": "PASS",
            "detail": "manifest created; feasibility check skipped",
        })

    return rows


def phase6b_stage1_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase6b_stage1"

    java_dir = config["tools"]["java_scripts_dir"]
    jar = config["tools"]["rapidwright_jar"]
    baseline_dcp = config["design"]["baseline_dcp"]

    candidate_json = os.path.join(dirs["phase5"], "phase5b2_fast_selected_candidate.json")
    candidate = load_json_if_exists(candidate_json)

    if not candidate:
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": f"cannot read candidate json: {candidate_json}",
        })
        return rows

    roles = candidate["roles"]

    stage1_dcp = os.path.join(dirs["phase6b_stage1"], "phase6b2_stage1_upgraded_inits.dcp")
    report_json = os.path.join(dirs["phase6b_stage1"], "phase6b2_stage1_report.json")

    java_source = os.path.join(java_dir, "Phase6B2UpgradeAndSetInits.java")
    java_class = os.path.join(java_dir, "Phase6B2UpgradeAndSetInits.class")

    if not os.path.exists(java_source):
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": f"missing Java source: {java_source}",
        })
        return rows

    compile_cmd = [
        "javac",
        "-cp",
        f".:{jar}",
        "Phase6B2UpgradeAndSetInits.java",
    ]

    run_cmd(
        compile_cmd,
        cwd=java_dir,
        log_path=log_path,
        commands_log_path=commands_log,
        timeout_sec=config.get("timeouts", {}).get("phase6b_stage1_sec", 1800),
    )

    if not os.path.exists(java_class):
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": f"Java class not created: {java_class}",
        })
        return rows

    cmd = [
        "java",
        "-cp",
        f".:{jar}",
        "Phase6B2UpgradeAndSetInits",
        baseline_dcp,
        stage1_dcp,
        report_json,
    ]

    for role_name in ["root", "helper1", "helper2"]:
        role = roles[role_name]
        cmd.extend([role["cell"], role["new_INIT"]])

    run_cmd(
        cmd,
        cwd=java_dir,
        log_path=log_path,
        commands_log_path=commands_log,
        timeout_sec=config.get("timeouts", {}).get("phase6b_stage1_sec", 1800),
    )

    require_file(stage1_dcp, phase, rows, "stage1_dcp")
    require_file(report_json, phase, rows, "stage1_report_json")

    report = load_json_if_exists(report_json)
    if report and report.get("status") == "PASS":
        rows.append({
            "phase": phase,
            "status": "PASS",
            "detail": f"stage1 DCP written: {stage1_dcp}",
        })
    else:
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": f"stage1 report not PASS: {report_json}",
        })

    return rows


def phase6b_rewire_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase6b_rewire"

    script = config["scripts"]["phase6b2_rewire_py"]

    stage1_dcp = os.path.join(dirs["phase6b_stage1"], "phase6b2_stage1_upgraded_inits.dcp")
    manifest = os.path.join(dirs["phase6a"], "phase6a_eco_manifest.json")
    out_dir = dirs["phase6b_rewire"]

    # This routed DCP is not trusted as final, but the script requires a path.
    same_session_routed_dcp = os.path.join(out_dir, "phase6b2_eco_routed_same_session.dcp")

    cmd = [
        "python3",
        script,
        stage1_dcp,
        manifest,
        out_dir,
        same_session_routed_dcp,
    ]

    run_cmd_retry(
    cmd,
    cwd=out_dir,
    log_path=log_path,
    commands_log_path=commands_log,
    timeout_sec=config.get("timeouts", {}).get("phase3_sec", 1800),
    retries=config.get("tools", {}).get("vivado_retries", 3),
    )

    tcl = os.path.join(out_dir, "phase6b2_apply_rewire_route.tcl")
    require_file(tcl, phase, rows, "phase6b2_rewire_tcl")

    cmd2 = [
        config["tools"].get("vivado_bin", "vivado"),
        "-mode", "batch",
        "-source", tcl,
    ]

    run_cmd_retry(
    cmd2,
    cwd=out_dir,
    log_path=log_path,
    commands_log_path=commands_log,
    timeout_sec=config.get("timeouts", {}).get("phase3_sec", 1800),
    retries=config.get("tools", {}).get("vivado_retries", 3),
    )

    checks = os.path.join(out_dir, "phase6b2_vivado_checks.csv")
    unrouted_dcp = os.path.join(out_dir, "phase6b2_eco_unrouted.dcp")

    require_file(checks, phase, rows, "phase6b2_vivado_checks")
    require_file(unrouted_dcp, phase, rows, "phase6b2_eco_unrouted_dcp")

    if os.path.exists(checks):
        txt = Path(checks).read_text(errors="ignore")
        critical_fails = []

        for line in txt.splitlines():
            if ",FAIL," in line:
                # We care about actual rewire failures.
                # route_design_full may fail in this same-session step; phase6c will reroute fresh.
                if "route_design_full" not in line and "route_design_preserve" not in line:
                    critical_fails.append(line)

        if critical_fails:
            rows.append({
                "phase": phase,
                "status": "FAIL",
                "detail": "rewire checks contain FAIL: " + " | ".join(critical_fails[:3]),
            })
        else:
            rows.append({
                "phase": phase,
                "status": "PASS",
                "detail": "rewire applied and reloadable-unrouted DCP written",
            })

    return rows


def write_phase6c_fresh_route_tcl(in_dcp, out_dir, out_dcp):
    tcl_path = os.path.join(out_dir, "route_from_unrouted_fresh.tcl")

    with open(tcl_path, "w") as f:
        f.write(f'set in_dcp "{in_dcp}"\n')
        f.write(f'set out_dir "{out_dir}"\n')
        f.write(f'set out_dcp "{out_dcp}"\n')
        f.write("file mkdir $out_dir\n\n")
        f.write('set checks "$out_dir/fresh_route_checks.csv"\n')
        f.write("set cf [open $checks w]\n")
        f.write('puts $cf "check,status,detail"\n\n')
        f.write("""
proc check_write {cf check status detail} {
    puts $cf "$check,$status,$detail"
    flush $cf
}
""")
        f.write("""
open_checkpoint $in_dcp
check_write $cf "open_unrouted_checkpoint" "PASS" $in_dcp

report_route_status -file "$out_dir/before_route_status.rpt"
report_drc -file "$out_dir/before_route_drc.rpt"

if {[catch {route_design} err]} {
    check_write $cf "route_design_full" "FAIL" $err
} else {
    check_write $cf "route_design_full" "PASS" "route_design"
}

report_route_status -file "$out_dir/after_route_status.rpt"
report_drc -file "$out_dir/after_route_drc.rpt"
report_timing_summary -file "$out_dir/after_route_timing_summary.rpt"
report_timing -max_paths 10 -nworst 10 -file "$out_dir/after_route_worst_paths.rpt"

write_checkpoint -force $out_dcp
check_write $cf "write_routed_checkpoint" "PASS" $out_dcp

close $cf

puts "FRESH_ROUTE_DONE"
puts "OUT_DCP=$out_dcp"
puts "CHECKS=$checks"
""")

    return tcl_path


def write_phase6c_reload_tcl(dcp, out_dir):
    tcl_path = os.path.join(out_dir, "test_open_fresh_routed.tcl")

    with open(tcl_path, "w") as f:
        f.write(f'set dcp "{dcp}"\n')
        f.write(f'set out_dir "{out_dir}"\n\n')
        f.write("""
open_checkpoint $dcp

report_route_status -file "$out_dir/reload_route_status.rpt"
report_drc -file "$out_dir/reload_drc.rpt"
report_timing_summary -file "$out_dir/reload_timing_summary.rpt"

puts "FRESH_ROUTED_RELOAD_PASS"
""")

    return tcl_path


def phase6c_fresh_route_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase6c"

    in_dcp = os.path.join(dirs["phase6b_rewire"], "phase6b2_eco_unrouted.dcp")
    out_dir = dirs["phase6c"]
    out_dcp = os.path.join(out_dir, "phase6b2_eco_routed_fresh.dcp")

    if not os.path.exists(in_dcp):
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": f"missing unrouted ECO DCP: {in_dcp}",
        })
        return rows

    route_tcl = write_phase6c_fresh_route_tcl(in_dcp, out_dir, out_dcp)

    cmd = [
        config["tools"].get("vivado_bin", "vivado"),
        "-mode", "batch",
        "-source", route_tcl,
    ]

    run_cmd_retry(
    cmd,
    cwd=out_dir,
    log_path=log_path,
    commands_log_path=commands_log,
    timeout_sec=config.get("timeouts", {}).get("phase6c_sec", 3600),
    retries=config.get("tools", {}).get("vivado_retries", 3),
    )

    checks = os.path.join(out_dir, "fresh_route_checks.csv")
    after_route = os.path.join(out_dir, "after_route_status.rpt")
    after_drc = os.path.join(out_dir, "after_route_drc.rpt")

    require_file(checks, phase, rows, "fresh_route_checks")
    require_file(out_dcp, phase, rows, "fresh_routed_dcp")
    require_file(after_route, phase, rows, "after_route_status")
    require_file(after_drc, phase, rows, "after_route_drc")

    # Reload check in a fresh Vivado process.
    reload_tcl = write_phase6c_reload_tcl(out_dcp, out_dir)

    cmd2 = [
        config["tools"].get("vivado_bin", "vivado"),
        "-mode", "batch",
        "-source", reload_tcl,
    ]

    run_cmd_retry(
        cmd2,
        cwd=out_dir,
        log_path=log_path,
        commands_log_path=commands_log,
        timeout_sec=config.get("timeouts", {}).get("phase6c_sec", 3600),
        retries=config.get("tools", {}).get("vivado_retries", 2),
   )

    reload_route = os.path.join(out_dir, "reload_route_status.rpt")
    reload_drc = os.path.join(out_dir, "reload_drc.rpt")

    require_file(reload_route, phase, rows, "reload_route_status")
    require_file(reload_drc, phase, rows, "reload_drc")

    route = parse_route_status(reload_route)
    drc = parse_drc(reload_drc)

    if route.get("nets_with_routing_errors") != 0:
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": f"reload route errors={route.get('nets_with_routing_errors')}",
        })
    elif drc.get("error_rules"):
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": f"reload DRC error rules={drc.get('error_rules')}",
        })
    else:
        rows.append({
            "phase": phase,
            "status": "PASS",
            "detail": f"fresh routed reloadable DCP OK: {out_dcp}",
        })

    return rows


def phase6_run(config, dirs, log_path, commands_log):
    rows = []

    rows.extend(phase6a_run(config, dirs, log_path, commands_log))

    if any(r["status"] == "FAIL" for r in rows):
        return rows

    rows.extend(phase6b_stage1_run(config, dirs, log_path, commands_log))

    if any(r["status"] == "FAIL" for r in rows):
        return rows

    rows.extend(phase6b_rewire_run(config, dirs, log_path, commands_log))

    if any(r["status"] == "FAIL" for r in rows):
        return rows

    if config.get("phase6", {}).get("fresh_route_from_unrouted", True):
        rows.extend(phase6c_fresh_route_run(config, dirs, log_path, commands_log))

    return rows


def read_key_value_summary(path):
    data = {}

    if not os.path.exists(path):
        return data

    with open(path, "r", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or "=" not in line:
                continue

            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()

    return data


def phase7_run(config, dirs, log_path, commands_log):
    rows = []
    phase = "phase7"

    if not config.get("phase7", {}).get("enabled", True):
        rows.append({"phase": phase, "status": "SKIP", "detail": "disabled"})
        return rows

    script = config["scripts"]["phase7_py"]

    baseline_dcp = config["design"]["baseline_dcp"]

    eco_dcp = os.path.join(
        dirs["phase6c"],
        "phase6b2_eco_routed_fresh.dcp",
    )

    phase1_json = os.path.join(
        dirs["phase1"],
        "phase1_lut_timing_edges.json",
    )

    phase3_json = os.path.join(
        dirs["phase3"],
        "phase3_window_info.json",
    )

    candidate_json = os.path.join(
        dirs["phase5"],
        "phase5b2_fast_selected_candidate.json",
    )

    out_dir = dirs["phase7"]

    required_inputs = [
        ("baseline_dcp", baseline_dcp),
        ("eco_dcp", eco_dcp),
        ("phase1_json", phase1_json),
        ("phase3_json", phase3_json),
        ("candidate_json", candidate_json),
    ]

    for label, path in required_inputs:
        if not os.path.exists(path):
            rows.append({
                "phase": phase,
                "status": "FAIL",
                "detail": f"missing {label}: {path}",
            })
            return rows

    cmd = [
        "python3",
        script,
        baseline_dcp,
        eco_dcp,
        phase1_json,
        phase3_json,
        candidate_json,
        out_dir,
        "--run-vivado",
    ]

    run_cmd_retry(
    cmd,
    cwd=out_dir,
    log_path=log_path,
    commands_log_path=commands_log,
    timeout_sec=config.get("timeouts", {}).get("phase3_sec", 1800),
    retries=config.get("tools", {}).get("vivado_retries", 3),
    )

    summary_txt = os.path.join(out_dir, "phase7_summary.txt")
    comparison_json = os.path.join(out_dir, "phase7_comparison.json")

    require_file(summary_txt, phase, rows, "phase7_summary")
    require_file(comparison_json, phase, rows, "phase7_comparison_json")

    summary = read_key_value_summary(summary_txt)

    phase7_status = summary.get("phase7_status", "UNKNOWN")
    baseline_wns = summary.get("baseline_wns", "")
    eco_wns = summary.get("eco_wns", "")
    delta_wns = summary.get("delta_wns", "")
    baseline_tns = summary.get("baseline_tns", "")
    eco_tns = summary.get("eco_tns", "")
    delta_tns = summary.get("delta_tns", "")
    eco_route_errors = summary.get("eco_route_errors", "")
    new_drc_error_rules = summary.get("new_drc_error_rules", "")

    require_timing_improvement = config.get("phase7", {}).get(
        "require_timing_improvement",
        False,
    )

    if phase7_status.startswith("FAIL_ROUTE") or phase7_status.startswith("FAIL_NEW_DRC"):
        rows.append({
            "phase": phase,
            "status": "FAIL",
            "detail": (
                f"phase7_status={phase7_status}, "
                f"eco_route_errors={eco_route_errors}, "
                f"new_drc_error_rules={new_drc_error_rules}"
            ),
        })

    elif phase7_status == "NEGATIVE_WNS_WORSE":
        if require_timing_improvement:
            rows.append({
                "phase": phase,
                "status": "FAIL",
                "detail": (
                    f"timing worsened; baseline_wns={baseline_wns}, "
                    f"eco_wns={eco_wns}, delta_wns={delta_wns}"
                ),
            })
        else:
            rows.append({
                "phase": phase,
                "status": "PASS",
                "detail": (
                    f"validation complete; candidate timing negative; "
                    f"baseline_wns={baseline_wns}, eco_wns={eco_wns}, "
                    f"delta_wns={delta_wns}, baseline_tns={baseline_tns}, "
                    f"eco_tns={eco_tns}, delta_tns={delta_tns}"
                ),
            })

    else:
        rows.append({
            "phase": phase,
            "status": "PASS",
            "detail": (
                f"phase7_status={phase7_status}, "
                f"baseline_wns={baseline_wns}, eco_wns={eco_wns}, "
                f"delta_wns={delta_wns}, baseline_tns={baseline_tns}, "
                f"eco_tns={eco_tns}, delta_tns={delta_tns}"
            ),
        })

    return rows



def create_final_summary(config, run_dir, dirs, copied_config, status_rows):
    failed = any(r["status"] == "FAIL" for r in status_rows)
    warnings = any(r["status"] == "WARN" for r in status_rows)
    phases_seen = {r["phase"] for r in status_rows}

    if failed:
        status = "FAIL"
    elif warnings:
        status = "PASS_WITH_WARNINGS"
    else:
        if "phase7" in phases_seen:
            status = "PASS_FULL_FLOW_PHASE0_TO_PHASE7"
        elif "phase6c" in phases_seen:
            status = "PASS_PHASE0_TO_PHASE6"
        elif "phase5" in phases_seen:
            status = "PASS_PHASE0_TO_PHASE5"
        elif "phase4" in phases_seen:
            status = "PASS_PHASE0_TO_PHASE4"
        else:
            status = "PASS_INITIAL_SETUP"

    summary = {
        "run_name": config["run"]["name"],
        "run_dir": run_dir,
        "copied_config": copied_config,
        "status": status,
        "phase_rows": status_rows,
        "important_outputs": {
            "logs": dirs["logs"],
            "status": dirs["status"],
            "phase1": dirs["phase1"],
            "phase2": dirs["phase2"],
            "phase3": dirs["phase3"],
            "phase4": dirs["phase4"],
            "phase5": dirs["phase5"],
            "phase6a": dirs["phase6a"],
            "phase6b_stage1": dirs["phase6b_stage1"],
            "phase6b_rewire": dirs["phase6b_rewire"],
            "phase6c": dirs["phase6c"],
            "phase7": dirs["phase7"],
        },
    }

    write_json(os.path.join(dirs["status"], "final_summary.json"), summary)
    write_phase_status(os.path.join(dirs["status"], "phase_status.csv"), status_rows)

    return summary

def stop_if_failed(status_rows, config):
    if not config["run"].get("stop_on_phase_fail", True):
        return

    failed = [r for r in status_rows if r["status"] == "FAIL"]
    if failed:
        details = "\n".join([f"{r['phase']}: {r['detail']}" for r in failed])
        fail(f"Stopping because a phase failed:\n{details}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", help="Path to config.yaml")
    ap.add_argument("--init-only", action="store_true", help="Only create dirs and run phase0 precheck")
    ap.add_argument(
        "--until",
        choices=["phase0", "phase1", "phase2", "phase3", "phase4","phase5","phase6","phase7"],
        default="phase7",
        help="Run until this phase",
    )
    args = ap.parse_args()

    config_path = os.path.abspath(args.config)
    if not os.path.exists(config_path):
        fail(f"Config bestaat niet: {config_path}")

    config = load_yaml(config_path)

    run_dir, dirs, copied_config = create_run_dir(config, config_path)

    run_log = os.path.join(dirs["logs"], "run.log")
    commands_log = os.path.join(dirs["logs"], "commands.log")

    append_log(run_log, f"[START] run_dir={run_dir}")
    append_log(run_log, f"[CONFIG] {copied_config}")

    status_rows = []

    status_rows.extend(validate_basic_paths(config))

    if config.get("phase0", {}).get("enabled", True):
        status_rows.extend(phase0_check_baseline(config, dirs))

    stop_if_failed(status_rows, config)

    if args.init_only or args.until == "phase0":
        summary = create_final_summary(config, run_dir, dirs, copied_config, status_rows)
        print("GENERAL_FLOW_INITIALIZED")
        print(f"run_dir={run_dir}")
        print(f"status={summary['status']}")
        print("INIT_ONLY_DONE")
        return

    status_rows.extend(phase1_run(config, dirs, run_log, commands_log))
    stop_if_failed(status_rows, config)

    if args.until == "phase1":
        summary = create_final_summary(config, run_dir, dirs, copied_config, status_rows)
        print(f"GENERAL_FLOW_DONE_UNTIL_PHASE1 run_dir={run_dir} status={summary['status']}")
        return

    status_rows.extend(phase2_run(config, dirs, run_log, commands_log))
    stop_if_failed(status_rows, config)

    if args.until == "phase2":
        summary = create_final_summary(config, run_dir, dirs, copied_config, status_rows)
        print(f"GENERAL_FLOW_DONE_UNTIL_PHASE2 run_dir={run_dir} status={summary['status']}")
        return

    status_rows.extend(phase3_run(config, dirs, run_log, commands_log))
    stop_if_failed(status_rows, config)

    if args.until == "phase3":
        summary = create_final_summary(config, run_dir, dirs, copied_config, status_rows)
        print(f"GENERAL_FLOW_DONE_UNTIL_PHASE3 run_dir={run_dir} status={summary['status']}")
        return

    status_rows.extend(phase4_run(config, dirs, run_log, commands_log))
    stop_if_failed(status_rows, config)

    if args.until == "phase4":
        summary = create_final_summary(config, run_dir, dirs, copied_config, status_rows)
        print("GENERAL_FLOW_DONE_PHASE0_TO_PHASE4")
        print(f"run_dir={run_dir}")
        print(f"status={summary['status']}")
        print(f"summary={os.path.join(dirs['status'], 'final_summary.json')}")
        print(f"phase_status={os.path.join(dirs['status'], 'phase_status.csv')}")
        return

    status_rows.extend(phase5_run(config, dirs, run_log, commands_log))
    stop_if_failed(status_rows, config)

    if args.until == "phase5":
        summary = create_final_summary(config, run_dir, dirs, copied_config, status_rows)
        print("GENERAL_FLOW_DONE_PHASE0_TO_PHASE5")
        print(f"run_dir={run_dir}")
        print(f"status={summary['status']}")
        print(f"summary={os.path.join(dirs['status'], 'final_summary.json')}")
        print(f"phase_status={os.path.join(dirs['status'], 'phase_status.csv')}")
        return

    status_rows.extend(phase6_run(config, dirs, run_log, commands_log))
    stop_if_failed(status_rows, config)

    if args.until == "phase6":
        summary = create_final_summary(config, run_dir, dirs, copied_config, status_rows)
        print("GENERAL_FLOW_DONE_PHASE0_TO_PHASE6")
        print(f"run_dir={run_dir}")
        print(f"status={summary['status']}")
        print(f"summary={os.path.join(dirs['status'], 'final_summary.json')}")
        print(f"phase_status={os.path.join(dirs['status'], 'phase_status.csv')}")
        return

    status_rows.extend(phase7_run(config, dirs, run_log, commands_log))
    stop_if_failed(status_rows, config)

    summary = create_final_summary(config, run_dir, dirs, copied_config, status_rows)

    print("GENERAL_FLOW_DONE_PHASE0_TO_PHASE7")
    print(f"run_dir={run_dir}")
    print(f"status={summary['status']}")
    print(f"summary={os.path.join(dirs['status'], 'final_summary.json')}")
    print(f"phase_status={os.path.join(dirs['status'], 'phase_status.csv')}")    
    print(f"run_dir={run_dir}")
    print(f"status={summary['status']}")
    print(f"summary={os.path.join(dirs['status'], 'final_summary.json')}")
    print(f"phase_status={os.path.join(dirs['status'], 'phase_status.csv')}")




if __name__ == "__main__":
    main()
