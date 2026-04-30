#!/usr/bin/env python3
"""
FASE 4 — Functionele afbakening van het kleine LUT-window.

Input:
  phase3_window_info.json

Output:
  Volledige truth table van de originele windowfunctie.

Belangrijk:
  Simulatie gebruikt de standaard Xilinx LUT INIT-indexering:

    index = I0 + 2*I1 + 4*I2 + 8*I3 + 16*I4 + 32*I5

  Dus I0 is de least significant bit van de INIT-index.

Gebruik:
  python3 phase4_simulate_window.py <phase3_window_info.json> <out_dir>
"""

import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict, deque


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def add_check(checks, name, status, detail):
    checks.append({
        "check": name,
        "status": status,
        "detail": detail,
    })


def lut_ref_input_count(ref: str) -> int:
    m = re.fullmatch(r"LUT([1-6])", ref.strip())
    if not m:
        raise ValueError(f"Unsupported LUT ref: {ref}")
    return int(m.group(1))


def parse_init(init_str: str, ref: str):
    """
    Parse Vivado INIT strings like:
      64'h022A2A2A0202022A
      4'h1

    Returns:
      dict with integer value and expected bit width.
    """
    if not init_str:
        raise ValueError("empty INIT")

    s = init_str.strip().replace("_", "")
    m = re.fullmatch(r"(?i)(\d+)'h([0-9a-f]+)", s)
    if not m:
        raise ValueError(f"Unsupported INIT format: {init_str}")

    declared_width = int(m.group(1))
    hex_digits = m.group(2)
    value = int(hex_digits, 16)

    num_inputs = lut_ref_input_count(ref)
    expected_bits = 1 << num_inputs

    # High bits outside the actual LUT support may not be meaningful.
    # For this first exact flow, we require that they are zero if present.
    if value >= (1 << expected_bits):
        raise ValueError(
            f"INIT {init_str} for {ref} has non-zero bits above expected {expected_bits} bits"
        )

    return {
        "init_raw": init_str,
        "init_value": value,
        "declared_width": declared_width,
        "num_inputs": num_inputs,
        "expected_bits": expected_bits,
        "normalized_hex": f"{value:0{max(1, expected_bits // 4)}X}",
        "normalized_bin_lsb_first": "".join(str((value >> i) & 1) for i in range(expected_bits)),
    }


def eval_lut(init_value: int, input_values_by_index: dict, num_inputs: int) -> int:
    """
    Evaluate a LUT using Xilinx INIT convention:
      bit index = sum(Ik << k)
    """
    idx = 0
    for i in range(num_inputs):
        bit = int(input_values_by_index.get(i, 0))
        if bit not in (0, 1):
            raise ValueError(f"Invalid LUT input value {bit}")
        idx |= (bit << i)

    return (init_value >> idx) & 1


def build_topological_order(luts, internal_edges):
    cell_names = [x["cell"] for x in luts]

    adj = defaultdict(list)
    indeg = {c: 0 for c in cell_names}

    for e in internal_edges:
        src = e["source_cell"]
        dst = e["sink_cell"]
        if src not in indeg or dst not in indeg:
            continue
        adj[src].append(dst)
        indeg[dst] += 1

    q = deque([c for c in cell_names if indeg[c] == 0])
    order = []

    while q:
        c = q.popleft()
        order.append(c)
        for nxt in adj[c]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)

    if len(order) != len(cell_names):
        raise ValueError("Cycle detected in LUT window graph")

    return order


def compute_depths(topo_order, internal_edges):
    incoming = defaultdict(list)
    for e in internal_edges:
        incoming[e["sink_cell"]].append(e["source_cell"])

    depth = {}
    for c in topo_order:
        if not incoming[c]:
            depth[c] = 1
        else:
            depth[c] = max(depth[src] for src in incoming[c]) + 1

    return depth


def main():
    if len(sys.argv) != 3:
        fail("usage: python3 phase4_simulate_window.py <phase3_window_info.json> <out_dir>")

    phase3_json = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    ensure_dir(out_dir)

    if not os.path.exists(phase3_json):
        fail(f"phase3 JSON bestaat niet: {phase3_json}")

    with open(phase3_json, "r") as f:
        data = json.load(f)

    checks = []

    # Output paths.
    summary_path = os.path.join(out_dir, "phase4_summary.txt")
    checks_path = os.path.join(out_dir, "phase4_validation_checks.csv")
    truth_csv_path = os.path.join(out_dir, "truth_table.csv")
    compact_json_path = os.path.join(out_dir, "truth_table_compact.json")
    init_csv_path = os.path.join(out_dir, "lut_init_parsed.csv")
    topo_csv_path = os.path.join(out_dir, "topological_order.csv")
    support_csv_path = os.path.join(out_dir, "support_analysis.csv")
    trace_csv_path = os.path.join(out_dir, "simulation_trace_sample.csv")
    manifest_path = os.path.join(out_dir, "phase4_manifest.txt")

    # Basic data.
    luts = data.get("luts", [])
    lut_input_pins = data.get("lut_input_pins", [])
    internal_edges = data.get("internal_edges", [])
    boundary_inputs = data.get("boundary_inputs", [])
    boundary_outputs = data.get("boundary_outputs", [])

    phase3_status = data.get("phase3_status", "")
    add_check(
        checks,
        "phase3_status_is_pass",
        "PASS" if phase3_status == "PASS" else "FAIL",
        f"phase3_status={phase3_status}",
    )

    if not luts:
        add_check(checks, "luts_present", "FAIL", "no LUTs found")
    else:
        add_check(checks, "luts_present", "PASS", f"num_luts={len(luts)}")

    if not boundary_inputs:
        add_check(checks, "boundary_inputs_present", "FAIL", "no boundary inputs found")
    else:
        add_check(checks, "boundary_inputs_present", "PASS", f"num_boundary_inputs={len(boundary_inputs)}")

    if not boundary_outputs:
        add_check(checks, "boundary_outputs_present", "FAIL", "no boundary outputs found")
    else:
        add_check(checks, "boundary_outputs_present", "PASS", f"num_boundary_outputs={len(boundary_outputs)}")

    if len(boundary_inputs) <= 12:
        add_check(checks, "truth_table_size_limit", "PASS", f"2^{len(boundary_inputs)} rows")
    else:
        add_check(checks, "truth_table_size_limit", "FAIL", f"num_boundary_inputs={len(boundary_inputs)} > 12")

    # Sort boundary inputs by boundary_index.
    try:
        boundary_inputs = sorted(boundary_inputs, key=lambda x: int(x["boundary_index"]))
        expected_indices = list(range(1, len(boundary_inputs) + 1))
        actual_indices = [int(x["boundary_index"]) for x in boundary_inputs]

        if actual_indices == expected_indices:
            add_check(checks, "boundary_indices_contiguous", "PASS", str(actual_indices))
        else:
            add_check(checks, "boundary_indices_contiguous", "FAIL", f"actual={actual_indices}")
    except Exception as e:
        add_check(checks, "boundary_indices_contiguous", "FAIL", str(e))

    # Map boundary net -> boundary index.
    boundary_by_net = {}
    boundary_by_index = {}

    for b in boundary_inputs:
        idx = int(b["boundary_index"])
        net = b.get("net", "")
        boundary_by_index[idx] = b

        if net:
            if net in boundary_by_net:
                add_check(checks, "boundary_net_unique", "FAIL", f"duplicate boundary net: {net}")
            boundary_by_net[net] = idx

    add_check(checks, "boundary_net_mapping_created", "PASS", f"{len(boundary_by_net)} mapped boundary nets")

    # Parse LUT INITs.
    lut_by_cell = {}
    parsed_inits = {}
    init_rows = []

    for lut in luts:
        cell = lut["cell"]
        ref = lut["ref"]
        init_raw = lut.get("init", "")

        lut_by_cell[cell] = lut

        try:
            parsed = parse_init(init_raw, ref)
            parsed_inits[cell] = parsed

            init_rows.append({
                "cell": cell,
                "ref": ref,
                "init_raw": init_raw,
                "declared_width": parsed["declared_width"],
                "num_inputs": parsed["num_inputs"],
                "expected_bits": parsed["expected_bits"],
                "normalized_hex": parsed["normalized_hex"],
                "parse_status": "PASS",
                "detail": "",
            })
        except Exception as e:
            init_rows.append({
                "cell": cell,
                "ref": ref,
                "init_raw": init_raw,
                "declared_width": "",
                "num_inputs": "",
                "expected_bits": "",
                "normalized_hex": "",
                "parse_status": "FAIL",
                "detail": str(e),
            })

    if len(parsed_inits) == len(luts):
        add_check(checks, "all_inits_parsed", "PASS", f"{len(parsed_inits)} INITs parsed")
    else:
        add_check(checks, "all_inits_parsed", "FAIL", f"{len(parsed_inits)} of {len(luts)} INITs parsed")

    # Organise LUT inputs by sink cell and input index.
    inputs_by_cell = defaultdict(list)
    for pin in lut_input_pins:
        inputs_by_cell[pin["sink_cell"]].append(pin)

    for cell in inputs_by_cell:
        inputs_by_cell[cell].sort(key=lambda x: int(x["input_index"]))

    # Topological order and depth.
    try:
        topo_order = build_topological_order(luts, internal_edges)
        add_check(checks, "topological_order", "PASS", " -> ".join(topo_order))
    except Exception as e:
        topo_order = []
        add_check(checks, "topological_order", "FAIL", str(e))

    try:
        depths = compute_depths(topo_order, internal_edges)
        max_depth = max(depths.values()) if depths else 0
        add_check(checks, "window_depth_computed", "PASS", f"max_depth={max_depth}")
    except Exception as e:
        depths = {}
        max_depth = ""
        add_check(checks, "window_depth_computed", "FAIL", str(e))

    # Validate every LUT input has a resolvable source.
    resolvable_inputs = True

    for pin in lut_input_pins:
        classification = pin.get("classification", "")
        net = pin.get("net", "")
        sink_pin = pin.get("sink_pin", "")

        if classification == "boundary_input":
            if net not in boundary_by_net:
                resolvable_inputs = False
                add_check(
                    checks,
                    f"boundary_source_resolvable:{sink_pin}",
                    "FAIL",
                    f"net {net} not found in boundary_inputs",
                )
        elif classification == "internal":
            src = pin.get("driver_cell", "")
            if src not in lut_by_cell:
                resolvable_inputs = False
                add_check(
                    checks,
                    f"internal_source_resolvable:{sink_pin}",
                    "FAIL",
                    f"driver {src} not in window LUTs",
                )
        else:
            resolvable_inputs = False
            add_check(
                checks,
                f"input_classification_supported:{sink_pin}",
                "FAIL",
                f"classification={classification}",
            )

    if resolvable_inputs:
        add_check(checks, "all_input_sources_resolvable", "PASS", "all LUT inputs resolvable")

    # Boundary output support.
    boundary_outputs = sorted(boundary_outputs, key=lambda x: int(x["boundary_index"]))
    output_sources = []

    for bo in boundary_outputs:
        src = bo.get("source_cell", "")
        if src not in lut_by_cell:
            add_check(checks, f"boundary_output_source:{src}", "FAIL", "source cell not in window")
        else:
            output_sources.append(src)

    if output_sources:
        add_check(checks, "boundary_output_sources_resolvable", "PASS", "|".join(output_sources))

    # Warn, not fail: INIT ordering assumption.
    add_check(
        checks,
        "init_bit_order_assumption",
        "WARN",
        "Using Xilinx convention: index = I0 + 2*I1 + 4*I2 + 8*I3 + 16*I4 + 32*I5. "
        "This script records and uses the convention; later equivalence checks remain required.",
    )

    # Abort simulation if there are hard FAIL checks.
    hard_fail_before_sim = any(c["status"] == "FAIL" for c in checks)

    if hard_fail_before_sim:
        phase4_status = "FAIL"

        write_csv(
            checks_path,
            ["check", "status", "detail"],
            checks,
        )

        with open(summary_path, "w") as f:
            f.write("phase4_status=FAIL\n")
            f.write("reason=pre_simulation_validation_failed\n")
            f.write(f"phase3_json={phase3_json}\n")

        print("PHASE4_FAIL: pre-simulation validation failed")
        print(f"Checks: {checks_path}")
        sys.exit(2)

    n_inputs = len(boundary_inputs)
    n_rows = 1 << n_inputs

    # Simulation.
    truth_rows = []
    output_vectors_by_row = {}
    output_bits_compact = []

    trace_rows = []

    def simulate_one(row_index: int):
        boundary_values = {}
        for b in boundary_inputs:
            idx = int(b["boundary_index"])
            boundary_values[idx] = (row_index >> (idx - 1)) & 1

        lut_outputs = {}

        for cell in topo_order:
            lut = lut_by_cell[cell]
            ref = lut["ref"]
            parsed = parsed_inits[cell]
            num_inputs = parsed["num_inputs"]
            init_value = parsed["init_value"]

            input_values = {}

            for pin in inputs_by_cell[cell]:
                input_index = int(pin["input_index"])
                classification = pin["classification"]

                if input_index >= num_inputs:
                    raise ValueError(
                        f"{cell}: input index {input_index} outside LUT input count {num_inputs}"
                    )

                if classification == "boundary_input":
                    bidx = boundary_by_net[pin["net"]]
                    input_values[input_index] = boundary_values[bidx]
                elif classification == "internal":
                    src = pin["driver_cell"]
                    if src not in lut_outputs:
                        raise ValueError(
                            f"{cell}: internal source {src} not evaluated before sink"
                        )
                    input_values[input_index] = lut_outputs[src]
                else:
                    raise ValueError(f"{cell}: unsupported classification {classification}")

            out = eval_lut(init_value, input_values, num_inputs)
            lut_outputs[cell] = out

        outputs = []
        for bo in boundary_outputs:
            src = bo["source_cell"]
            outputs.append(lut_outputs[src])

        return boundary_values, lut_outputs, outputs

    for row_index in range(n_rows):
        boundary_values, lut_outputs, outputs = simulate_one(row_index)

        boundary_vector = "".join(str(boundary_values[i]) for i in range(1, n_inputs + 1))
        output_vector = "".join(str(x) for x in outputs)

        output_vectors_by_row[row_index] = output_vector
        output_bits_compact.append(output_vector)

        row = {
            "row_index": row_index,
            "boundary_vector_B1_to_Bn": boundary_vector,
            "output_vector": output_vector,
        }

        for i in range(1, n_inputs + 1):
            row[f"B{i}"] = boundary_values[i]

        for bo in boundary_outputs:
            out_idx = int(bo["boundary_index"])
            src = bo["source_cell"]
            row[f"OUT{out_idx}_{src}"] = lut_outputs[src]

        truth_rows.append(row)

        if row_index < 32:
            trace = {
                "row_index": row_index,
                "boundary_vector_B1_to_Bn": boundary_vector,
                "output_vector": output_vector,
            }

            for cell in topo_order:
                trace[f"LUTOUT_{cell}"] = lut_outputs[cell]

            trace_rows.append(trace)

    # Determinism check: simulate again and compare hashable result.
    output_sequence = "".join(output_bits_compact)
    truth_hash = hashlib.sha256(output_sequence.encode("ascii")).hexdigest()

    second_sequence = []
    for row_index in range(n_rows):
        _, _, outputs2 = simulate_one(row_index)
        second_sequence.append("".join(str(x) for x in outputs2))

    deterministic = "".join(second_sequence) == output_sequence

    if deterministic:
        add_check(checks, "simulation_deterministic", "PASS", "second simulation matched first")
    else:
        add_check(checks, "simulation_deterministic", "FAIL", "second simulation differed")

    if len(truth_rows) == n_rows:
        add_check(checks, "truth_table_row_count", "PASS", f"{len(truth_rows)} rows")
    else:
        add_check(checks, "truth_table_row_count", "FAIL", f"{len(truth_rows)} rows, expected {n_rows}")

    unknown_outputs = any(
        row["output_vector"] == "" or any(ch not in "01" for ch in row["output_vector"])
        for row in truth_rows
    )

    if not unknown_outputs:
        add_check(checks, "no_unknown_outputs", "PASS", "all outputs are 0/1")
    else:
        add_check(checks, "no_unknown_outputs", "FAIL", "unknown output found")

    # Support analysis.
    support_rows = []

    for b in boundary_inputs:
        idx = int(b["boundary_index"])
        toggle_mask = 1 << (idx - 1)
        changes = 0
        comparisons = 0

        for row_index in range(n_rows):
            if row_index & toggle_mask:
                continue

            other = row_index ^ toggle_mask
            comparisons += 1

            if output_vectors_by_row[row_index] != output_vectors_by_row[other]:
                changes += 1

        support_rows.append({
            "boundary_index": idx,
            "net": b.get("net", ""),
            "driver_kind": b.get("driver_kind", ""),
            "driver_cell": b.get("driver_cell", ""),
            "driver_pin": b.get("driver_pin", ""),
            "comparisons": comparisons,
            "output_changes_when_toggled": changes,
            "in_support": 1 if changes > 0 else 0,
        })

    used_support_count = sum(int(r["in_support"]) for r in support_rows)

    # Single-output stats.
    if len(boundary_outputs) == 1:
        ones = sum(1 for x in output_bits_compact if x == "1")
        zeros = sum(1 for x in output_bits_compact if x == "0")
    else:
        ones = ""
        zeros = ""

    # Final status.
    phase4_failed = any(c["status"] == "FAIL" for c in checks)
    phase4_status = "FAIL" if phase4_failed else "PASS"

    # Write outputs.
    truth_fields = (
        ["row_index", "boundary_vector_B1_to_Bn"]
        + [f"B{i}" for i in range(1, n_inputs + 1)]
        + [f"OUT{int(bo['boundary_index'])}_{bo['source_cell']}" for bo in boundary_outputs]
        + ["output_vector"]
    )

    write_csv(truth_csv_path, truth_fields, truth_rows)

    write_csv(
        checks_path,
        ["check", "status", "detail"],
        checks,
    )

    write_csv(
        init_csv_path,
        [
            "cell",
            "ref",
            "init_raw",
            "declared_width",
            "num_inputs",
            "expected_bits",
            "normalized_hex",
            "parse_status",
            "detail",
        ],
        init_rows,
    )

    topo_rows = []
    for order_idx, cell in enumerate(topo_order):
        topo_rows.append({
            "topological_order": order_idx,
            "cell": cell,
            "ref": lut_by_cell[cell]["ref"],
            "depth": depths.get(cell, ""),
            "site": lut_by_cell[cell].get("site", ""),
            "bel": lut_by_cell[cell].get("bel", ""),
        })

    write_csv(
        topo_csv_path,
        ["topological_order", "cell", "ref", "depth", "site", "bel"],
        topo_rows,
    )

    write_csv(
        support_csv_path,
        [
            "boundary_index",
            "net",
            "driver_kind",
            "driver_cell",
            "driver_pin",
            "comparisons",
            "output_changes_when_toggled",
            "in_support",
        ],
        support_rows,
    )

    trace_fields = (
        ["row_index", "boundary_vector_B1_to_Bn"]
        + [f"LUTOUT_{cell}" for cell in topo_order]
        + ["output_vector"]
    )

    write_csv(trace_csv_path, trace_fields, trace_rows)

    compact = {
        "phase": "FASE 4",
        "phase4_status": phase4_status,
        "phase3_json": phase3_json,
        "num_boundary_inputs": n_inputs,
        "num_boundary_outputs": len(boundary_outputs),
        "num_rows": n_rows,
        "boundary_input_order": [
            {
                "boundary_index": int(b["boundary_index"]),
                "net": b.get("net", ""),
                "driver_kind": b.get("driver_kind", ""),
                "driver_cell": b.get("driver_cell", ""),
                "driver_pin": b.get("driver_pin", ""),
            }
            for b in boundary_inputs
        ],
        "boundary_outputs": boundary_outputs,
        "topological_order": topo_order,
        "window_depth": max_depth,
        "truth_table_encoding": {
            "row_index_meaning": "boundary input Bk = (row_index >> (k-1)) & 1",
            "boundary_vector_order": "B1,B2,...,Bn",
            "output_bits_order": "row_index 0 to 2^n-1",
            "sha256_output_sequence": truth_hash,
        },
        "single_output_stats": {
            "zeros": zeros,
            "ones": ones,
        },
        "used_support_count": used_support_count,
        "output_sequence": output_sequence,
        "validation_checks": checks,
    }

    with open(compact_json_path, "w") as f:
        json.dump(compact, f, indent=2)

    with open(summary_path, "w") as f:
        f.write(f"phase4_status={phase4_status}\n")
        f.write(f"phase3_json={phase3_json}\n")
        f.write(f"num_luts={len(luts)}\n")
        f.write(f"num_boundary_inputs={n_inputs}\n")
        f.write(f"num_boundary_outputs={len(boundary_outputs)}\n")
        f.write(f"num_truth_table_rows={n_rows}\n")
        f.write(f"window_depth={max_depth}\n")
        f.write(f"truth_table_sha256={truth_hash}\n")
        f.write(f"single_output_zeros={zeros}\n")
        f.write(f"single_output_ones={ones}\n")
        f.write(f"used_support_count={used_support_count}\n")
        f.write(f"truth_table_csv={truth_csv_path}\n")
        f.write(f"truth_table_compact_json={compact_json_path}\n")
        f.write(f"support_analysis_csv={support_csv_path}\n")
        f.write(f"topological_order_csv={topo_csv_path}\n")
        f.write(f"validation_checks_csv={checks_path}\n")

    with open(manifest_path, "w") as f:
        f.write("FASE 4 simulation manifest\n")
        f.write("==========================\n")
        f.write(f"phase4_status={phase4_status}\n")
        f.write(f"phase3_json={phase3_json}\n")
        f.write(f"truth_table_csv={truth_csv_path}\n")
        f.write(f"truth_table_compact_json={compact_json_path}\n")
        f.write(f"lut_init_parsed_csv={init_csv_path}\n")
        f.write(f"topological_order_csv={topo_csv_path}\n")
        f.write(f"support_analysis_csv={support_csv_path}\n")
        f.write(f"simulation_trace_sample_csv={trace_csv_path}\n")
        f.write("\n")
        f.write("INIT convention used:\n")
        f.write("  index = I0 + 2*I1 + 4*I2 + 8*I3 + 16*I4 + 32*I5\n")
        f.write("\n")
        f.write("Boundary input row encoding:\n")
        f.write("  Bk = (row_index >> (k-1)) & 1\n")

    print(f"PHASE4_{phase4_status}")
    print(f"Summary: {summary_path}")
    print(f"Truth table CSV: {truth_csv_path}")
    print(f"Compact JSON: {compact_json_path}")
    print(f"Checks: {checks_path}")


if __name__ == "__main__":
    main()
