#!/usr/bin/env python3
"""
FASE 5D — ABC-gebaseerde LUT-decompositie + fysieke mapping.

Doel:
  1. Neem de Phase 4 truth table van het window.
  2. Schrijf die als PLA.
  3. Laat ABC een LUT6-mapping maken.
  4. Lees mapped.blif terug in Python.
  5. Simuleer ABC-netwerk en check exacte equivalentie.
  6. Map ABC-LUT-nodes op bestaande fysieke LUT-sites uit het window.
  7. Kies de beste mapping volgens eenvoudige fysieke score.

Belangrijk:
  - Dit is voorlopig een Phase 5 candidate generator.
  - De output is nog niet direct compatibel met de bestaande hardcoded Phase 6A.
  - Daarna moeten we Phase 6 generic maken.
"""

import argparse
import csv
import itertools
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


# -----------------------------
# Basic utilities
# -----------------------------

def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def add_check(checks, check, status, detail):
    checks.append({
        "check": check,
        "status": status,
        "detail": detail,
    })


def site_xy(site):
    m = re.search(r"X([0-9]+)Y([0-9]+)", site or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def manhattan(site_a, site_b):
    a = site_xy(site_a)
    b = site_xy(site_b)
    if a is None or b is None:
        return None
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def ref_capacity(ref):
    m = re.fullmatch(r"LUT([1-6])", (ref or "").strip())
    if not m:
        return 0
    return int(m.group(1))


def format_init(value, width=64):
    hex_digits = max(1, width // 4)
    return f"{width}'h{value:0{hex_digits}X}"


def row_bit(row_index, boundary_index):
    return (row_index >> (int(boundary_index) - 1)) & 1


def eval_lut(init_value, input_bits):
    idx = 0
    for i, bit in enumerate(input_bits):
        idx |= (int(bit) & 1) << i
    return (init_value >> idx) & 1


def parse_cover_line(line):
    """
    Parse één BLIF cover line.

    Voorbeelden:
      "11 1"      -> pattern="11", value=1
      "--0000 0"  -> pattern="--0000", value=0
      "11"        -> pattern="11", value=1
      "1" bij 0-input node -> pattern="", value=1
    """
    parts = line.split()

    if len(parts) == 0:
        return "", 0

    if len(parts) == 1:
        token = parts[0]

        if token in ("0", "1"):
            return "", int(token)

        return token, 1

    pattern = parts[0]
    out_val = parts[-1]

    if out_val not in ("0", "1"):
        out_val = "1"

    return pattern, int(out_val)


def node_default_value(node):
    """
    Bepaal defaultwaarde van een .names node.

    Normale BLIF:
      alleen output-1 coverregels => default 0

    ABC kan ook alleen output-0 coverregels schrijven:
      dan interpreteren we dit als off-set cover => default 1
    """
    values = []

    for line in node.get("cover", []):
        _, val = parse_cover_line(line)
        values.append(val)

    if not values:
        return 0

    if any(v == 1 for v in values):
        return 0

    # Alleen 0-regels: off-set cover.
    return 1


def eval_blif_node_from_values(node, values):
    """
    Evalueer node op basis van reeds opgehaalde inputwaarden.
    """
    default = node_default_value(node)
    result = default

    for line in node.get("cover", []):
        pattern, out_val = parse_cover_line(line)

        # Constant node.
        if len(values) == 0:
            return out_val

        if cover_matches(pattern, values):
            result = out_val

    return result


# -----------------------------
# Phase3 helpers
# -----------------------------

def boundary_by_index_map(phase3):
    return {
        int(b["boundary_index"]): b
        for b in phase3.get("boundary_inputs", [])
    }


def boundary_name_to_index(name):
    m = re.fullmatch(r"b([0-9]+)", name)
    if not m:
        return None
    return int(m.group(1))


def current_output_driver(phase3):
    outs = phase3.get("boundary_outputs", [])
    if not outs:
        return ""
    return outs[0].get("source_cell", "")


def old_source_id(pin):
    classification = pin.get("classification", "")

    if classification == "internal":
        return f"INT:{pin.get('driver_cell', '')}/O"

    if classification == "boundary_input":
        return f"BI_NET:{pin.get('net', '')}"

    return classification


def build_old_pin_map(phase3):
    old = {}

    for pin in phase3.get("lut_input_pins", []):
        key = (pin["sink_cell"], pin["sink_ref_pin"])
        old[key] = old_source_id(pin)

    return old


def new_source_id_for_signal(signal, node_to_cell, boundary_by_index):
    bidx = boundary_name_to_index(signal)

    if bidx is not None:
        net = boundary_by_index[int(bidx)].get("net", "")
        return f"BI_NET:{net}"

    if signal in node_to_cell:
        return f"INT:{node_to_cell[signal]['cell']}/O"

    return f"UNKNOWN:{signal}"


def infer_baseline_score(phase3):
    internal_total = 0
    internal_max = 0

    for e in phase3.get("internal_edges", []):
        try:
            m = int(e.get("manhattan_distance", 0))
        except Exception:
            m = 0

        internal_total += m
        internal_max = max(internal_max, m)

    boundary_by_net = {
        b["net"]: b
        for b in phase3.get("boundary_inputs", [])
    }

    cell_site = {
        l["cell"]: l.get("site", "")
        for l in phase3.get("luts", [])
    }

    boundary_total = 0

    for pin in phase3.get("lut_input_pins", []):
        if pin.get("classification") != "boundary_input":
            continue

        src = boundary_by_net.get(pin.get("net", ""))
        sink_site = cell_site.get(pin.get("sink_cell", ""), "")

        if src:
            m = manhattan(src.get("driver_site", ""), sink_site)
            if m is not None:
                boundary_total += m

    return internal_max * 1000 + internal_total * 100 + boundary_total


# -----------------------------
# PLA export
# -----------------------------

def write_pla(path, boundary_count, output_sequence):
    with open(path, "w") as f:
        f.write(f".i {boundary_count}\n")
        f.write(".o 1\n")
        f.write(".ilb " + " ".join(f"b{i}" for i in range(1, boundary_count + 1)) + "\n")
        f.write(".ob y\n")

        ones = 0
        for row, bit in enumerate(output_sequence):
            if bit != "1":
                continue

            cube = "".join(str(row_bit(row, i)) for i in range(1, boundary_count + 1))
            f.write(f"{cube} 1\n")
            ones += 1

        f.write(".e\n")

    return ones


# -----------------------------
# ABC runner
# -----------------------------

def run_abc(abc_bin, pla_path, blif_path, log_path):
    cmd_string = (
        f"read_pla {pla_path}; "
        f"strash; "
        f"if -K 6; "
        f"write_blif {blif_path}"
    )

    cmd = [abc_bin, "-c", cmd_string]

    with open(log_path, "w") as log:
        log.write("[CMD] " + " ".join(cmd) + "\n\n")
        log.flush()

        proc = subprocess.run(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    return proc.returncode, cmd_string


# -----------------------------
# BLIF parser and simulator
# -----------------------------

def preprocess_blif_lines(text):
    logical = []
    current = ""

    for raw in text.splitlines():
        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        if line.endswith("\\"):
            current += line[:-1].strip() + " "
            continue

        if current:
            line = current + line
            current = ""

        logical.append(line)

    if current:
        logical.append(current.strip())

    return logical


def parse_blif(path):
    text = Path(path).read_text(errors="replace")
    lines = preprocess_blif_lines(text)

    model = ""
    inputs = []
    outputs = []
    nodes = []

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith(".model"):
            parts = line.split()
            model = parts[1] if len(parts) > 1 else ""
            i += 1
            continue

        if line.startswith(".inputs"):
            inputs.extend(line.split()[1:])
            i += 1
            continue

        if line.startswith(".outputs"):
            outputs.extend(line.split()[1:])
            i += 1
            continue

        if line.startswith(".names"):
            parts = line.split()
            signals = parts[1:]

            if not signals:
                fail(f"Invalid .names line: {line}")

            node_inputs = signals[:-1]
            node_output = signals[-1]
            cover = []

            i += 1
            while i < len(lines) and not lines[i].startswith("."):
                cover.append(lines[i])
                i += 1

            nodes.append({
                "inputs": node_inputs,
                "output": node_output,
                "cover": cover,
            })

            continue

        i += 1

    return {
        "model": model,
        "inputs": inputs,
        "outputs": outputs,
        "nodes": nodes,
    }


def cover_matches(pattern, values):
    if len(pattern) != len(values):
        return False

    for p, v in zip(pattern, values):
        if p == "-":
            continue
        if int(p) != int(v):
            return False

    return True

def eval_blif_node(node, env):
    inputs = node["inputs"]

    values = []

    for name in inputs:
        if name not in env:
            raise KeyError(f"Signal {name} not available when evaluating {node['output']}")
        values.append(env[name])

    return eval_blif_node_from_values(node, values)


def simulate_blif_network(blif, boundary_count, output_sequence):
    outputs = blif["outputs"]
    nodes = blif["nodes"]

    if len(outputs) != 1:
        return False, [{"error": f"Expected 1 output, got {len(outputs)}"}]

    y_name = outputs[0]
    mismatches = []

    for row, expected_char in enumerate(output_sequence):
        env = {}

        for i in range(1, boundary_count + 1):
            env[f"b{i}"] = row_bit(row, i)

        pending = list(nodes)

        while pending:
            progress = False
            next_pending = []

            for node in pending:
                if all(inp in env for inp in node["inputs"]):
                    env[node["output"]] = eval_blif_node(node, env)
                    progress = True
                else:
                    next_pending.append(node)

            if not progress:
                missing_info = []

                for node in next_pending[:5]:
                    missing = [inp for inp in node["inputs"] if inp not in env]
                    missing_info.append({
                        "node": node["output"],
                        "missing": missing,
                    })

                return False, [{
                    "error": "Could not topologically evaluate BLIF; unresolved dependencies or cycle",
                    "row": row,
                    "missing_info": missing_info,
                }]

            pending = next_pending

        if y_name not in env:
            return False, [{"error": f"Output {y_name} not driven", "row": row}]

        actual = env[y_name]
        expected = 1 if expected_char == "1" else 0

        if actual != expected:
            mismatches.append({
                "row": row,
                "expected": expected,
                "actual": actual,
            })
            if len(mismatches) >= 20:
                break

    return len(mismatches) == 0, mismatches


def node_init_64(node):
    inputs = node["inputs"]
    k = len(inputs)

    if k > 6:
        raise ValueError(f"Node {node['output']} has {k} inputs > 6")

    small_init = 0

    for idx in range(1 << k):
        values = []

        for i in range(k):
            bit = (idx >> i) & 1
            values.append(bit)

        val = eval_blif_node_from_values(node, values)

        if val:
            small_init |= 1 << idx

    expanded = 0
    mask = (1 << k) - 1 if k > 0 else 0

    for idx6 in range(64):
        small_idx = idx6 & mask if k > 0 else 0
        bit = (small_init >> small_idx) & 1
        expanded |= bit << idx6

    return small_init, expanded

# -----------------------------
# Physical mapping
# -----------------------------

def score_mapping(blif, phase3, assignment):
    """
    assignment:
      dict node_output -> physical LUT dict
    """
    boundary_by_index = boundary_by_index_map(phase3)

    internal_total = 0
    internal_max = 0
    boundary_total = 0
    boundary_missing = 0

    for node in blif["nodes"]:
        sink_cell = assignment[node["output"]]
        sink_site = sink_cell.get("site", "")

        for inp in node["inputs"]:
            bidx = boundary_name_to_index(inp)

            if bidx is not None:
                src_site = boundary_by_index[int(bidx)].get("driver_site", "")
                m = manhattan(src_site, sink_site)

                if m is None:
                    boundary_missing += 1
                else:
                    boundary_total += m
                continue

            if inp in assignment:
                src_cell = assignment[inp]
                m = manhattan(src_cell.get("site", ""), sink_site)

                if m is None:
                    m = 0

                internal_total += m
                internal_max = max(internal_max, m)

    root_node = blif["outputs"][0]
    root_cell = assignment[root_node]

    output_driver_changed = root_cell["cell"] != current_output_driver(phase3)

    upgraded_cells = []

    for node in blif["nodes"]:
        cell = assignment[node["output"]]
        needed_inputs = len(node["inputs"])
        cap = ref_capacity(cell.get("ref", ""))

        if needed_inputs > cap:
            upgraded_cells.append(cell["cell"])

    upgraded_cells = sorted(set(upgraded_cells))
    upgrade_count = len(upgraded_cells)

    old_pin_map = build_old_pin_map(phase3)
    changed_pin_count = 0

    for node in blif["nodes"]:
        cell = assignment[node["output"]]

        for i, inp in enumerate(node["inputs"]):
            key = (cell["cell"], f"I{i}")
            new_src = new_source_id_for_signal(inp, assignment, boundary_by_index)
            old_src = old_pin_map.get(key, "")

            if new_src != old_src:
                changed_pin_count += 1

    score_without_penalties = (
        internal_max * 1000
        + internal_total * 100
        + boundary_total
        + boundary_missing * 10000
    )

    score_with_penalties = (
        score_without_penalties
        + (5000 if output_driver_changed else 0)
        + upgrade_count * 3000
        + changed_pin_count * 250
    )

    return {
        "internal_manhattan_total": internal_total,
        "internal_manhattan_max": internal_max,
        "boundary_manhattan_total": boundary_total,
        "boundary_manhattan_missing": boundary_missing,
        "output_driver_changed": output_driver_changed,
        "upgrade_count": upgrade_count,
        "upgraded_cells": upgraded_cells,
        "changed_pin_count": changed_pin_count,
        "score_without_penalties": score_without_penalties,
        "score_with_penalties": score_with_penalties,
    }


def build_candidate_payload(blif, phase3, assignment, score, baseline_score, output_sequence):
    boundary_by_index = boundary_by_index_map(phase3)
    old_pin_map = build_old_pin_map(phase3)

    node_payloads = []
    changed_pins = []

    for node in blif["nodes"]:
        cell = assignment[node["output"]]
        _, init64 = node_init_64(node)

        input_payloads = []

        for i, inp in enumerate(node["inputs"]):
            bidx = boundary_name_to_index(inp)

            if bidx is not None:
                input_payloads.append({
                    "sink_pin": f"I{i}",
                    "boundary_index": int(bidx),
                    "source_signal": inp,
                })
            else:
                src_cell = assignment[inp]["cell"] if inp in assignment else ""
                input_payloads.append({
                    "sink_pin": f"I{i}",
                    "source_signal": inp,
                    "source_cell": src_cell,
                })

            key = (cell["cell"], f"I{i}")
            new_src = new_source_id_for_signal(inp, assignment, boundary_by_index)
            old_src = old_pin_map.get(key, "")

            if new_src != old_src:
                changed_pins.append({
                    "sink_cell": cell["cell"],
                    "sink_pin": f"I{i}",
                    "old_source": old_src,
                    "new_source": new_src,
                })

        node_payloads.append({
            "abc_node": node["output"],
            "physical_cell": cell["cell"],
            "original_ref": cell.get("ref", ""),
            "logical_ref": f"LUT{min(6, max(1, len(node['inputs'])))}",
            "site": cell.get("site", ""),
            "bel": cell.get("bel", ""),
            "input_count": len(node["inputs"]),
            "new_INIT": format_init(init64, 64),
            "inputs": input_payloads,
        })

    root_signal = blif["outputs"][0]
    root_cell = assignment[root_signal]

    estimated_improvement = score["score_with_penalties"] < baseline_score

    return {
        "phase": "FASE 5D ABC",
        "phase5d_status": "PASS_IMPROVED_ESTIMATE" if estimated_improvement else "PASS_NO_ESTIMATED_IMPROVEMENT",
        "candidate_id": "phase5d_abc_candidate_00000",
        "family": "abc_lut6_mapping_physical_assignment",
        "truth_table_equivalence": True,
        "num_checked_vectors": len(output_sequence),
        "same_window_boundary": True,
        "same_lut_positions": True,
        "abc_lut_count": len(blif["nodes"]),
        "window_lut_count": len(phase3.get("luts", [])),
        "estimated_improvement": estimated_improvement,
        "baseline_score": baseline_score,
        "score_without_penalties": score["score_without_penalties"],
        "score_with_penalties": score["score_with_penalties"],
        "output_signal": root_signal,
        "output_driver": {
            "abc_node": root_signal,
            "physical_cell": root_cell["cell"],
            "physical_pin": f"{root_cell['cell']}/O",
        },
        "nodes": node_payloads,
        "changed_pins": changed_pins,
        "cost": {
            **score,
            "changed_pin_count": len(changed_pins),
        },
    }


def find_best_physical_assignment(blif, phase3):
    nodes = blif["nodes"]
    luts = phase3.get("luts", [])

    if len(nodes) > len(luts):
        return None, None, f"ABC uses {len(nodes)} LUTs but window has only {len(luts)} LUTs"

    node_outputs = [n["output"] for n in nodes]

    best_assignment = None
    best_score = None

    for lut_perm in itertools.permutations(luts, len(nodes)):
        assignment = {
            node_output: lut
            for node_output, lut in zip(node_outputs, lut_perm)
        }

        try:
            score = score_mapping(blif, phase3, assignment)
        except Exception:
            continue

        if best_score is None or (
            score["score_with_penalties"],
            score["score_without_penalties"],
            score["changed_pin_count"],
        ) < (
            best_score["score_with_penalties"],
            best_score["score_without_penalties"],
            best_score["changed_pin_count"],
        ):
            best_score = score
            best_assignment = assignment

    if best_assignment is None:
        return None, None, "no valid physical assignment found"

    return best_assignment, best_score, ""


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase3_json")
    parser.add_argument("truth_table_compact_json")
    parser.add_argument("out_dir")
    parser.add_argument("--abc-bin", default="berkeley-abc")
    parser.add_argument("--keep-going-on-abc-error", action="store_true")

    args = parser.parse_args()

    start = time.time()

    out_dir = os.path.abspath(args.out_dir)
    ensure_dir(out_dir)

    abc_dir = os.path.join(out_dir, "abc")
    ensure_dir(abc_dir)

    pla_path = os.path.join(abc_dir, "window.pla")
    blif_path = os.path.join(abc_dir, "mapped.blif")
    abc_log = os.path.join(abc_dir, "abc.log")

    with open(args.phase3_json, "r") as f:
        phase3 = json.load(f)

    with open(args.truth_table_compact_json, "r") as f:
        phase4 = json.load(f)

    checks = []

    add_check(
        checks,
        "phase3_status",
        "PASS" if phase3.get("phase3_status") == "PASS" else "FAIL",
        phase3.get("phase3_status", ""),
    )

    add_check(
        checks,
        "phase4_status",
        "PASS" if phase4.get("phase4_status") == "PASS" else "FAIL",
        phase4.get("phase4_status", ""),
    )

    boundary_count = int(phase4["num_boundary_inputs"])
    output_count = int(phase4["num_boundary_outputs"])
    output_sequence = phase4["output_sequence"]
    lut_count = len(phase3.get("luts", []))

    if output_count != 1:
        add_check(checks, "single_output", "FAIL", f"output_count={output_count}")
    else:
        add_check(checks, "single_output", "PASS", "1")

    if boundary_count < 1 or boundary_count > 12:
        add_check(checks, "boundary_count_supported", "FAIL", f"boundary_count={boundary_count}")
    else:
        add_check(checks, "boundary_count_supported", "PASS", str(boundary_count))

    expected_len = 1 << boundary_count
    if len(output_sequence) != expected_len:
        add_check(checks, "truth_table_length", "FAIL", f"len={len(output_sequence)}, expected={expected_len}")
    else:
        add_check(checks, "truth_table_length", "PASS", str(expected_len))

    if lut_count < 1:
        add_check(checks, "window_luts_present", "FAIL", str(lut_count))
    else:
        add_check(checks, "window_luts_present", "PASS", str(lut_count))

    if any(c["status"] == "FAIL" for c in checks):
        write_csv(
            os.path.join(out_dir, "phase5d_validation_checks.csv"),
            ["check", "status", "detail"],
            checks,
        )
        fail("pre-checks failed")

    ones = write_pla(pla_path, boundary_count, output_sequence)
    add_check(checks, "pla_written", "PASS", f"{pla_path}; ones={ones}")

    print(f"[phase5d] PLA written: {pla_path}", flush=True)

    rc, abc_cmd = run_abc(args.abc_bin, pla_path, blif_path, abc_log)

    if rc != 0:
        add_check(checks, "abc_return_code", "FAIL", str(rc))
        if not args.keep_going_on_abc_error:
            write_csv(
                os.path.join(out_dir, "phase5d_validation_checks.csv"),
                ["check", "status", "detail"],
                checks,
            )
            fail(f"ABC failed with return code {rc}; see {abc_log}")
    else:
        add_check(checks, "abc_return_code", "PASS", str(rc))

    if not os.path.exists(blif_path):
        add_check(checks, "mapped_blif_exists", "FAIL", blif_path)
        write_csv(
            os.path.join(out_dir, "phase5d_validation_checks.csv"),
            ["check", "status", "detail"],
            checks,
        )
        fail("ABC did not produce mapped BLIF")

    add_check(checks, "mapped_blif_exists", "PASS", blif_path)

    blif = parse_blif(blif_path)

    add_check(checks, "blif_inputs", "PASS", str(len(blif["inputs"])))
    add_check(checks, "blif_outputs", "PASS" if len(blif["outputs"]) == 1 else "FAIL", str(len(blif["outputs"])))
    add_check(checks, "blif_lut_nodes", "PASS", str(len(blif["nodes"])))

    print(f"[phase5d] BLIF nodes: {len(blif['nodes'])}", flush=True)

    max_node_inputs = max((len(n["inputs"]) for n in blif["nodes"]), default=0)

    if max_node_inputs > 6:
        add_check(checks, "all_nodes_lut6_or_less", "FAIL", f"max_node_inputs={max_node_inputs}")
    else:
        add_check(checks, "all_nodes_lut6_or_less", "PASS", f"max_node_inputs={max_node_inputs}")

    equivalent, mismatches = simulate_blif_network(blif, boundary_count, output_sequence)

    if equivalent:
        add_check(checks, "blif_truth_table_equivalence", "PASS", f"rows={len(output_sequence)}")
    else:
        add_check(checks, "blif_truth_table_equivalence", "FAIL", str(mismatches[:3]))

    baseline_score = infer_baseline_score(phase3)

    candidate = None
    assignment_rows = []
    phase_status = "FAIL"
    error = ""

    if equivalent and max_node_inputs <= 6:
        assignment, score, error = find_best_physical_assignment(blif, phase3)

        if assignment is None:
            add_check(checks, "physical_assignment", "FAIL", error)
        else:
            add_check(checks, "physical_assignment", "PASS", "best assignment found")

            for node in blif["nodes"]:
                cell = assignment[node["output"]]
                assignment_rows.append({
                    "abc_node": node["output"],
                    "abc_inputs": "|".join(node["inputs"]),
                    "physical_cell": cell["cell"],
                    "physical_ref": cell.get("ref", ""),
                    "site": cell.get("site", ""),
                    "bel": cell.get("bel", ""),
                    "input_count": len(node["inputs"]),
                })

            candidate = build_candidate_payload(
                blif,
                phase3,
                assignment,
                score,
                baseline_score,
                output_sequence,
            )

            phase_status = candidate["phase5d_status"]
    else:
        error = "BLIF not equivalent or node input count > 6"

    write_csv(
        os.path.join(out_dir, "phase5d_validation_checks.csv"),
        ["check", "status", "detail"],
        checks,
    )

    write_csv(
        os.path.join(out_dir, "phase5d_assignment.csv"),
        [
            "abc_node",
            "abc_inputs",
            "physical_cell",
            "physical_ref",
            "site",
            "bel",
            "input_count",
        ],
        assignment_rows,
    )

    candidate_rows = []

    if candidate:
        candidate_rows.append({
            "candidate_id": candidate["candidate_id"],
            "phase5d_status": candidate["phase5d_status"],
            "abc_lut_count": candidate["abc_lut_count"],
            "window_lut_count": candidate["window_lut_count"],
            "baseline_score": candidate["baseline_score"],
            "score_without_penalties": candidate["score_without_penalties"],
            "score_with_penalties": candidate["score_with_penalties"],
            "estimated_improvement": int(candidate["estimated_improvement"]),
            "output_driver_cell": candidate["output_driver"]["physical_cell"],
            "changed_pin_count": candidate["cost"]["changed_pin_count"],
            "upgrade_count": candidate["cost"]["upgrade_count"],
            "upgraded_cells": "|".join(candidate["cost"]["upgraded_cells"]),
        })

    write_csv(
        os.path.join(out_dir, "phase5d_candidates.csv"),
        [
            "candidate_id",
            "phase5d_status",
            "abc_lut_count",
            "window_lut_count",
            "baseline_score",
            "score_without_penalties",
            "score_with_penalties",
            "estimated_improvement",
            "output_driver_cell",
            "changed_pin_count",
            "upgrade_count",
            "upgraded_cells",
        ],
        candidate_rows,
    )

    selected_path = os.path.join(out_dir, "phase5d_selected_candidate.json")
    with open(selected_path, "w") as f:
        json.dump(candidate, f, indent=2)

    summary = {
        "phase": "FASE 5D ABC",
        "phase5d_status": phase_status,
        "phase3_json": os.path.abspath(args.phase3_json),
        "truth_table_compact_json": os.path.abspath(args.truth_table_compact_json),
        "boundary_count": boundary_count,
        "truth_table_length": len(output_sequence),
        "truth_table_ones": ones,
        "window_lut_count": lut_count,
        "abc_command": abc_cmd,
        "abc_log": abc_log,
        "pla_path": pla_path,
        "mapped_blif": blif_path,
        "abc_lut_count": len(blif["nodes"]) if blif else None,
        "max_node_inputs": max_node_inputs,
        "truth_table_equivalence": equivalent,
        "baseline_score": baseline_score,
        "best_score_without_penalties": candidate["score_without_penalties"] if candidate else None,
        "best_score_with_penalties": candidate["score_with_penalties"] if candidate else None,
        "estimated_improvement": candidate["estimated_improvement"] if candidate else False,
        "selected_candidate_json": selected_path,
        "elapsed_seconds": round(time.time() - start, 3),
        "error": error,
        "validation_checks": checks,
    }

    with open(os.path.join(out_dir, "phase5d_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(out_dir, "phase5d_summary.txt"), "w") as f:
        f.write(f"phase5d_status={phase_status}\n")
        f.write(f"boundary_count={boundary_count}\n")
        f.write(f"truth_table_length={len(output_sequence)}\n")
        f.write(f"truth_table_ones={ones}\n")
        f.write(f"window_lut_count={lut_count}\n")
        f.write(f"abc_lut_count={len(blif['nodes']) if blif else ''}\n")
        f.write(f"max_node_inputs={max_node_inputs}\n")
        f.write(f"truth_table_equivalence={int(equivalent)}\n")
        f.write(f"baseline_score={baseline_score}\n")
        f.write(f"best_score_without_penalties={candidate['score_without_penalties'] if candidate else ''}\n")
        f.write(f"best_score_with_penalties={candidate['score_with_penalties'] if candidate else ''}\n")
        f.write(f"estimated_improvement={int(candidate['estimated_improvement']) if candidate else 0}\n")
        f.write(f"selected_candidate_json={selected_path}\n")
        f.write(f"pla_path={pla_path}\n")
        f.write(f"mapped_blif={blif_path}\n")
        f.write(f"abc_log={abc_log}\n")
        f.write(f"elapsed_seconds={round(time.time() - start, 3)}\n")
        f.write(f"error={error}\n")

    print(f"PHASE5D_ABC_{phase_status}")
    print(f"ABC LUT count        : {len(blif['nodes']) if blif else ''}")
    print(f"Window LUT count     : {lut_count}")
    print(f"Truth table equivalent: {equivalent}")
    print(f"Selected JSON        : {selected_path}")

    if candidate is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
