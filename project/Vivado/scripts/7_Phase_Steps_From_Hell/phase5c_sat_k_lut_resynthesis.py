#!/usr/bin/env python3
"""
FASE 5C — SAT-gebaseerde k-LUT resynthesis voor groter LUT-window.

Eerste pragmatische versie:
- ondersteunt boundary_inputs tussen 1 en 12;
- ondersteunt 1 output;
- gebruikt bestaande LUT-sites uit het window;
- kiest één root-LUT;
- gebruikt alle andere LUTs als helpers;
- 2-level structuur:

    F(B) = R(H1(S1), H2(S2), ..., Hm(Sm), D)

waar:
- m = aantal helpers = num_luts - 1
- root heeft maximaal 6 inputs
- helper outputs nemen m root-inputs in
- D zijn directe boundary inputs naar root
- alle overige boundary inputs worden verdeeld over helper-LUTs
- elke helper heeft max 6 inputs
- exactheid wordt bewezen via Z3 over alle truth-table rows

Belangrijk:
- Dit is voorlopig analyse/FASE5-output.
- De output is nog niet drop-in compatibel met je bestaande Phase 6A,
  omdat Phase 6A nog root/helper1/helper2 hardcoded verwacht.
"""

import argparse
import csv
import heapq
import itertools
import json
import os
import re
import sys
import time
from pathlib import Path

from z3 import Solver, Bool, BoolVal, If, And, Not, sat, is_true


# -----------------------------
# Basic utilities
# -----------------------------

def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def add_check(checks, check, status, detail):
    checks.append({"check": check, "status": status, "detail": detail})


def ref_capacity(ref: str) -> int:
    m = re.fullmatch(r"LUT([1-6])", (ref or "").strip())
    if not m:
        return 0
    return int(m.group(1))


def site_xy(site: str):
    m = re.search(r"X([0-9]+)Y([0-9]+)", site or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def manhattan(site_a: str, site_b: str):
    a = site_xy(site_a)
    b = site_xy(site_b)
    if a is None or b is None:
        return None
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def format_init(value: int, width: int = 64) -> str:
    hex_digits = max(1, width // 4)
    return f"{width}'h{value:0{hex_digits}X}"


def eval_lut(init_value: int, input_bits):
    idx = 0
    for i, bit in enumerate(input_bits):
        idx |= (int(bit) & 1) << i
    return (init_value >> idx) & 1


def expand_support_init_to_lut6(init_value: int, support_size: int) -> int:
    if support_size > 6:
        raise ValueError("support_size > 6")

    expanded = 0
    mask = (1 << support_size) - 1

    for idx6 in range(64):
        small_idx = idx6 & mask
        bit = (init_value >> small_idx) & 1
        expanded |= bit << idx6

    return expanded


def project_assignment(row_index: int, boundary_indices):
    """
    boundary_indices[0] wordt LUT input I0 / LSB.
    """
    out = 0
    for local_i, bidx in enumerate(boundary_indices):
        bit = (row_index >> (int(bidx) - 1)) & 1
        out |= bit << local_i
    return out


def row_bit(row_index: int, boundary_index: int) -> int:
    return (row_index >> (int(boundary_index) - 1)) & 1


# -----------------------------
# Phase3 helpers
# -----------------------------

def boundary_by_index_map(phase3):
    return {
        int(b["boundary_index"]): b
        for b in phase3.get("boundary_inputs", [])
    }


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


def new_source_id_from_boundary(boundary_index, boundary_by_index):
    net = boundary_by_index[int(boundary_index)].get("net", "")
    return f"BI_NET:{net}"


def current_output_driver(phase3):
    outs = phase3.get("boundary_outputs", [])
    if not outs:
        return ""
    return outs[0].get("source_cell", "")


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
# Template generation
# -----------------------------

def helper_partition_assignments(inputs, helper_count, max_per_helper=6, min_per_helper=1):
    """
    Verdeel boundary inputs over helper_count helpers.

    Return:
      tuple of tuples:
        ((inputs for H1), (inputs for H2), ...)
    """
    inputs = tuple(inputs)

    for assignment in itertools.product(range(helper_count), repeat=len(inputs)):
        buckets = [[] for _ in range(helper_count)]

        for bidx, helper_idx in zip(inputs, assignment):
            buckets[helper_idx].append(bidx)

        ok = True
        for bucket in buckets:
            if len(bucket) < min_per_helper or len(bucket) > max_per_helper:
                ok = False
                break

        if not ok:
            continue

        yield tuple(tuple(bucket) for bucket in buckets)


def template_cost(template, phase3):
    boundary_by_index = boundary_by_index_map(phase3)

    root = template["root"]
    helpers = template["helpers"]
    helper_inputs = template["helper_inputs"]
    direct_inputs = template["D"]

    internal_distances = []
    for h in helpers:
        m = manhattan(h.get("site", ""), root.get("site", ""))
        internal_distances.append(m if m is not None else 0)

    internal_total = sum(internal_distances)
    internal_max = max(internal_distances) if internal_distances else 0

    boundary_total = 0
    boundary_missing = 0

    def add_boundary_cost(bidx, sink_site):
        nonlocal boundary_total, boundary_missing

        src_site = boundary_by_index[int(bidx)].get("driver_site", "")
        m = manhattan(src_site, sink_site)

        if m is None:
            boundary_missing += 1
        else:
            boundary_total += m

    for helper, h_inputs in zip(helpers, helper_inputs):
        for b in h_inputs:
            add_boundary_cost(b, helper.get("site", ""))

    for b in direct_inputs:
        add_boundary_cost(b, root.get("site", ""))

    output_driver_changed = root["cell"] != current_output_driver(phase3)

    upgraded_cells = []

    root_support_size = len(helpers) + len(direct_inputs)
    if root.get("ref", "") != "LUT6" or ref_capacity(root.get("ref", "")) < root_support_size:
        upgraded_cells.append(root["cell"])

    for helper, h_inputs in zip(helpers, helper_inputs):
        support_size = len(h_inputs)
        if helper.get("ref", "") != "LUT6" or ref_capacity(helper.get("ref", "")) < support_size:
            upgraded_cells.append(helper["cell"])

    upgraded_cells = sorted(set(upgraded_cells))
    upgrade_count = len(upgraded_cells)

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
    )

    template.update({
        "internal_distances": internal_distances,
        "internal_manhattan_total": internal_total,
        "internal_manhattan_max": internal_max,
        "boundary_manhattan_total": boundary_total,
        "boundary_manhattan_missing": boundary_missing,
        "output_driver_changed": output_driver_changed,
        "upgrade_count": upgrade_count,
        "upgraded_cells": upgraded_cells,
        "score_without_penalties": score_without_penalties,
        "score_with_penalties": score_with_penalties,
    })

    return template


def generate_templates(phase3, boundary_count, max_generated=None):
    """
    Genereer 2-level k-LUT topologieën.

    Voor elke root:
      helpers = alle andere LUTs

    Root-inputen:
      I0..I(m-1) = helper outputs
      daarna directe boundary inputs D

    Directe boundary inputs:
      |D| = 6 - helper_count
    """
    luts = phase3.get("luts", [])
    all_inputs = tuple(range(1, boundary_count + 1))

    generated = 0

    for root in luts:
        helpers = [x for x in luts if x["cell"] != root["cell"]]
        helper_count = len(helpers)

        if helper_count < 1:
            continue

        if helper_count > 5:
            continue

        direct_count = 6 - helper_count

        if direct_count < 0:
            continue

        if direct_count > boundary_count:
            direct_count = boundary_count

        remaining_count = boundary_count - direct_count

        if remaining_count < helper_count:
            continue

        if remaining_count > helper_count * 6:
            continue

        for direct_inputs in itertools.combinations(all_inputs, direct_count):
            remaining = tuple(x for x in all_inputs if x not in direct_inputs)

            for helper_inputs in helper_partition_assignments(
                remaining,
                helper_count,
                max_per_helper=6,
                min_per_helper=1,
            ):
                template = {
                    "root": root,
                    "helpers": helpers,
                    "D": tuple(direct_inputs),
                    "helper_inputs": helper_inputs,
                }

                yield template_cost(template, phase3)

                generated += 1
                if max_generated is not None and generated >= max_generated:
                    return


def collect_top_templates(phase3, boundary_count, top_n, max_generated=None):
    total = 0

    heap = []
    counter = 0

    for t in generate_templates(phase3, boundary_count, max_generated=max_generated):
        total += 1
        score = t["score_with_penalties"]

        item = (-score, counter, t)
        counter += 1

        if len(heap) < top_n:
            heapq.heappush(heap, item)
        else:
            worst_score = -heap[0][0]
            if score < worst_score:
                heapq.heapreplace(heap, item)

        if total % 100000 == 0:
            print(f"[collect] generated={total}, kept={len(heap)}", flush=True)

    templates = [item[2] for item in heap]
    templates.sort(key=lambda x: (x["score_with_penalties"], x["score_without_penalties"]))

    return templates, total

def root_lookup_expr_fast(root_table, helper_outputs, direct_assignment, helper_count):
    """
    Snelle root LUT lookup.

    Root input order:
      I0..I(helper_count-1) = helper outputs
      daarna directe boundary inputs D

    De directe boundary inputs zijn voor een bepaalde truth-table row constant.
    Daarom hoeven we alleen te muxen over de helper outputs.
    """
    # Default = helper_combo 0.
    base_idx = direct_assignment << helper_count
    result = root_table[base_idx]

    # Alleen muxen over helper-output combinaties.
    for combo in range(1, 1 << helper_count):
        conds = []

        for i, h in enumerate(helper_outputs):
            bit = (combo >> i) & 1
            conds.append(h if bit else Not(h))

        cond = And(*conds) if conds else BoolVal(True)
        idx = combo | (direct_assignment << helper_count)

        result = If(cond, root_table[idx], result)

    return result



# -----------------------------
# Z3 solving
# -----------------------------

def lut_lookup_expr(table_vars, input_exprs):
    """
    Bouw een Z3-expressie voor LUT lookup.

    input_exprs[0] is I0 / LSB.
    """
    if not table_vars:
        raise ValueError("empty LUT table")

    result = table_vars[0]

    for idx in range(len(table_vars)):
        conds = []
        for i, inp in enumerate(input_exprs):
            bit = (idx >> i) & 1
            conds.append(inp if bit else Not(inp))

        cond = And(*conds) if conds else BoolVal(True)
        result = If(cond, table_vars[idx], result)

    return result


def model_table_to_init(model, table_vars):
    init = 0
    for idx, var in enumerate(table_vars):
        if is_true(model.eval(var, model_completion=True)):
            init |= 1 << idx
    return init


def solve_template_z3(output_sequence, template, timeout_ms=2000):
    helpers = template["helpers"]
    helper_inputs = template["helper_inputs"]
    direct_inputs = template["D"]

    helper_count = len(helpers)
    direct_count = len(direct_inputs)
    root_input_count = helper_count + direct_count

    if root_input_count > 6:
        return None, "root_too_many_inputs"

    helper_tables = []

    for hi, h_inputs in enumerate(helper_inputs):
        size = len(h_inputs)

        if size > 6:
            return None, "helper_too_many_inputs"

        vars_i = [
            Bool(f"h{hi}_t{idx}")
            for idx in range(1 << size)
        ]

        helper_tables.append(vars_i)

    root_table = [
        Bool(f"r_t{idx}")
        for idx in range(1 << root_input_count)
    ]

    solver = Solver()
    solver.set("timeout", timeout_ms)

    for row, expected_char in enumerate(output_sequence):
        helper_outputs = []

        # Helper inputs zijn boundary inputs, dus per row is hun local index constant.
        for h_inputs, table_vars in zip(helper_inputs, helper_tables):
            local_idx = project_assignment(row, h_inputs)
            helper_outputs.append(table_vars[local_idx])

        # Directe root boundary inputs zijn ook constant per row.
        direct_assignment = project_assignment(row, direct_inputs)

        y = root_lookup_expr_fast(
            root_table=root_table,
            helper_outputs=helper_outputs,
            direct_assignment=direct_assignment,
            helper_count=helper_count,
        )

        expected = BoolVal(expected_char == "1")
        solver.add(y == expected)

    result = solver.check()

    if result != sat:
        return None, str(result)

    model = solver.model()

    helper_inits_small = []
    helper_inits_64 = []

    for h_inputs, table_vars in zip(helper_inputs, helper_tables):
        small = model_table_to_init(model, table_vars)
        helper_inits_small.append(small)
        helper_inits_64.append(expand_support_init_to_lut6(small, len(h_inputs)))

    root_init_small = model_table_to_init(model, root_table)
    root_init_64 = expand_support_init_to_lut6(root_init_small, root_input_count)

    return {
        "helper_inits_small": helper_inits_small,
        "helper_inits_64": helper_inits_64,
        "root_init_small": root_init_small,
        "root_init_64": root_init_64,
        "root_input_count": root_input_count,
    }, "sat"

def simulate_candidate(output_sequence, template, result):
    mismatches = []

    helper_inputs = template["helper_inputs"]
    direct_inputs = template["D"]
    helper_inits_64 = result["helper_inits_64"]
    root_init_64 = result["root_init_64"]

    for row, expected_char in enumerate(output_sequence):
        helper_outputs = []

        for h_inputs, h_init in zip(helper_inputs, helper_inits_64):
            idx = project_assignment(row, h_inputs)
            helper_outputs.append((h_init >> idx) & 1)

        root_inputs = helper_outputs + [
            row_bit(row, bidx)
            for bidx in direct_inputs
        ]

        actual = eval_lut(root_init_64, root_inputs)
        expected = 1 if expected_char == "1" else 0

        if actual != expected:
            mismatches.append({
                "row": row,
                "expected": expected,
                "actual": actual,
            })
            if len(mismatches) >= 20:
                break

    return mismatches


# -----------------------------
# Candidate formatting
# -----------------------------

def compute_changed_pins(candidate, phase3):
    boundary_by_index = boundary_by_index_map(phase3)
    old_pin_map = build_old_pin_map(phase3)

    root = candidate["root"]
    helpers = candidate["helpers"]
    helper_inputs = candidate["helper_inputs"]
    direct_inputs = candidate["D"]

    new_pin_map = {}

    for helper, h_inputs in zip(helpers, helper_inputs):
        for i, bidx in enumerate(h_inputs):
            new_pin_map[(helper["cell"], f"I{i}")] = new_source_id_from_boundary(
                bidx,
                boundary_by_index,
            )

    root_pin_idx = 0

    for helper in helpers:
        new_pin_map[(root["cell"], f"I{root_pin_idx}")] = f"INT:{helper['cell']}/O"
        root_pin_idx += 1

    for bidx in direct_inputs:
        new_pin_map[(root["cell"], f"I{root_pin_idx}")] = new_source_id_from_boundary(
            bidx,
            boundary_by_index,
        )
        root_pin_idx += 1

    changed = []

    for key, new_src in new_pin_map.items():
        old_src = old_pin_map.get(key, "")

        if old_src != new_src:
            changed.append({
                "sink_cell": key[0],
                "sink_pin": key[1],
                "old_source": old_src,
                "new_source": new_src,
            })

    return changed


def build_candidate_payload(candidate_id, template, result, phase3, output_sequence, baseline_score):
    changed_pins = compute_changed_pins(template, phase3)

    helpers_payload = []
    for idx, helper in enumerate(template["helpers"]):
        helper_inputs = template["helper_inputs"][idx]

        helpers_payload.append({
            "role": f"H{idx + 1}",
            "cell": helper["cell"],
            "original_ref": helper["ref"],
            "logical_ref": "LUT6",
            "site": helper.get("site", ""),
            "bel": helper.get("bel", ""),
            "new_INIT": format_init(result["helper_inits_64"][idx], 64),
            "inputs": [
                {
                    "sink_pin": f"I{i}",
                    "boundary_index": int(bidx),
                }
                for i, bidx in enumerate(helper_inputs)
            ],
        })

    root_inputs = []

    pin_idx = 0
    for idx, helper in enumerate(template["helpers"]):
        root_inputs.append({
            "sink_pin": f"I{pin_idx}",
            "source": f"helper{idx + 1}/O",
            "source_cell": helper["cell"],
        })
        pin_idx += 1

    for bidx in template["D"]:
        root_inputs.append({
            "sink_pin": f"I{pin_idx}",
            "boundary_index": int(bidx),
        })
        pin_idx += 1

    estimated_improvement = template["score_with_penalties"] < baseline_score

    return {
        "phase": "FASE 5C SAT",
        "phase5c_status": "PASS_IMPROVED_ESTIMATE" if estimated_improvement else "PASS_NO_ESTIMATED_IMPROVEMENT",
        "candidate_id": candidate_id,
        "family": "sat_k_lut_two_level_multihelper",
        "truth_table_equivalence": True,
        "num_checked_vectors": len(output_sequence),
        "boundary_count": int(round(len(output_sequence).bit_length() - 1)),
        "same_lut_positions": True,
        "same_window_boundary": True,
        "all_roles_logical_lut6": True,
        "estimated_improvement": estimated_improvement,
        "baseline_score": baseline_score,
        "score_without_penalties": template["score_without_penalties"],
        "score_with_penalties": template["score_with_penalties"],
        "upgraded_cells": template["upgraded_cells"],
        "upgrade_count": template["upgrade_count"],
        "output_driver_changed": template["output_driver_changed"],
        "root": {
            "role": "R",
            "cell": template["root"]["cell"],
            "original_ref": template["root"]["ref"],
            "logical_ref": "LUT6",
            "site": template["root"].get("site", ""),
            "bel": template["root"].get("bel", ""),
            "new_INIT": format_init(result["root_init_64"], 64),
            "inputs": root_inputs,
        },
        "helpers": helpers_payload,
        "changed_pins": changed_pins,
        "cost": {
            "internal_manhattan_total": template["internal_manhattan_total"],
            "internal_manhattan_max": template["internal_manhattan_max"],
            "boundary_manhattan_total": template["boundary_manhattan_total"],
            "boundary_manhattan_missing": template["boundary_manhattan_missing"],
            "changed_pin_count": len(changed_pins),
        },
    }


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase3_json")
    parser.add_argument("truth_table_compact_json")
    parser.add_argument("out_dir")
    parser.add_argument("--top-templates", type=int, default=2000)
    parser.add_argument("--max-candidates", type=int, default=50)
    parser.add_argument("--z3-timeout-ms", type=int, default=2000)
    parser.add_argument("--max-generated", type=int, default=2000000)
    parser.add_argument("--stop-on-first-improved", action="store_true")

    args = parser.parse_args()

    ensure_dir(args.out_dir)

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

    if lut_count < 3:
        add_check(checks, "at_least_three_luts", "FAIL", str(lut_count))
    elif lut_count > 6:
        add_check(checks, "max_six_luts_for_two_level_v0", "FAIL", str(lut_count))
    else:
        add_check(checks, "lut_count_supported", "PASS", str(lut_count))

    if any(c["status"] == "FAIL" for c in checks):
        write_csv(
            os.path.join(args.out_dir, "phase5c_validation_checks.csv"),
            ["check", "status", "detail"],
            checks,
        )
        fail("pre-checks failed")

    start = time.time()
    baseline_score = infer_baseline_score(phase3)

    print("[phase5c] collecting top templates...", flush=True)

    templates, total_generated = collect_top_templates(
        phase3,
        boundary_count,
        args.top_templates,
        max_generated=args.max_generated,
    )

    print(f"[phase5c] templates generated: {total_generated}", flush=True)
    print(f"[phase5c] templates selected : {len(templates)}", flush=True)
    print(f"[phase5c] baseline_score     : {baseline_score}", flush=True)

    add_check(checks, "templates_generated", "PASS", f"generated={total_generated}, selected={len(templates)}")

    solved_rows = []
    candidates = []
    status_counts = {}

    for idx, template in enumerate(templates):
        result, status = solve_template_z3(
            output_sequence,
            template,
            timeout_ms=args.z3_timeout_ms,
        )

        status_counts[status] = status_counts.get(status, 0) + 1

        row = {
            "template_index": idx,
            "status": status,
            "root_cell": template["root"]["cell"],
            "helper_cells": "|".join(h["cell"] for h in template["helpers"]),
            "D": "|".join(map(str, template["D"])),
            "helper_inputs": " / ".join("|".join(map(str, x)) for x in template["helper_inputs"]),
            "score_without_penalties": template["score_without_penalties"],
            "score_with_penalties": template["score_with_penalties"],
            "internal_manhattan_max": template["internal_manhattan_max"],
            "internal_manhattan_total": template["internal_manhattan_total"],
            "boundary_manhattan_total": template["boundary_manhattan_total"],
            "upgrade_count": template["upgrade_count"],
            "upgraded_cells": "|".join(template["upgraded_cells"]),
            "output_driver_changed": int(template["output_driver_changed"]),
        }

        if result is not None:
            mismatches = simulate_candidate(output_sequence, template, result)

            if mismatches:
                row["status"] = "post_sim_mismatch"
                status_counts["post_sim_mismatch"] = status_counts.get("post_sim_mismatch", 0) + 1
            else:
                candidate_id = f"phase5c_sat_exact_{len(candidates):05d}"
                payload = build_candidate_payload(
                    candidate_id,
                    template,
                    result,
                    phase3,
                    output_sequence,
                    baseline_score,
                )

                candidates.append(payload)

                print(
                    f"[candidate] {candidate_id} "
                    f"score_pen={payload['score_with_penalties']} "
                    f"baseline={baseline_score} "
                    f"root={payload['root']['cell']} "
                    f"helpers={'|'.join(h['cell'] for h in payload['helpers'])}",
                    flush=True,
                )

                if payload["estimated_improvement"] and args.stop_on_first_improved:
                    solved_rows.append(row)
                    break

        solved_rows.append(row)

        if idx % 100 == 0:
            print(
                f"[progress] checked={idx}/{len(templates)} "
                f"status={status} candidates={len(candidates)}",
                flush=True,
            )

    candidates.sort(key=lambda c: (
        c["score_with_penalties"],
        c["score_without_penalties"],
        c["cost"]["changed_pin_count"],
        c["candidate_id"],
    ))

    kept = candidates[:args.max_candidates]
    best = kept[0] if kept else None

    if best:
        estimated_improvement = bool(best["estimated_improvement"])
        phase_status = "PASS_IMPROVED_ESTIMATE" if estimated_improvement else "PASS_NO_ESTIMATED_IMPROVEMENT"
        add_check(checks, "exact_candidates_found", "PASS", str(len(candidates)))
        add_check(checks, "best_candidate_selected", "PASS", best["candidate_id"])
    else:
        estimated_improvement = False
        phase_status = "FAIL"
        add_check(checks, "exact_candidates_found", "FAIL", "0")
        add_check(checks, "best_candidate_selected", "FAIL", "none")

    write_csv(
        os.path.join(args.out_dir, "phase5c_solved_templates.csv"),
        [
            "template_index",
            "status",
            "root_cell",
            "helper_cells",
            "D",
            "helper_inputs",
            "score_without_penalties",
            "score_with_penalties",
            "internal_manhattan_max",
            "internal_manhattan_total",
            "boundary_manhattan_total",
            "upgrade_count",
            "upgraded_cells",
            "output_driver_changed",
        ],
        solved_rows,
    )

    candidate_rows = []
    for c in kept:
        candidate_rows.append({
            "candidate_id": c["candidate_id"],
            "status": c["phase5c_status"],
            "root_cell": c["root"]["cell"],
            "helper_cells": "|".join(h["cell"] for h in c["helpers"]),
            "score_without_penalties": c["score_without_penalties"],
            "score_with_penalties": c["score_with_penalties"],
            "baseline_score": c["baseline_score"],
            "estimated_improvement": int(c["estimated_improvement"]),
            "upgrade_count": c["upgrade_count"],
            "upgraded_cells": "|".join(c["upgraded_cells"]),
            "output_driver_changed": int(c["output_driver_changed"]),
            "changed_pin_count": c["cost"]["changed_pin_count"],
        })

    write_csv(
        os.path.join(args.out_dir, "phase5c_candidates.csv"),
        [
            "candidate_id",
            "status",
            "root_cell",
            "helper_cells",
            "score_without_penalties",
            "score_with_penalties",
            "baseline_score",
            "estimated_improvement",
            "upgrade_count",
            "upgraded_cells",
            "output_driver_changed",
            "changed_pin_count",
        ],
        candidate_rows,
    )

    write_csv(
        os.path.join(args.out_dir, "phase5c_validation_checks.csv"),
        ["check", "status", "detail"],
        checks,
    )

    selected_path = os.path.join(args.out_dir, "phase5c_selected_candidate.json")
    with open(selected_path, "w") as f:
        json.dump(best, f, indent=2)

    summary = {
        "phase": "FASE 5C SAT",
        "phase5c_status": phase_status,
        "phase3_json": os.path.abspath(args.phase3_json),
        "truth_table_compact_json": os.path.abspath(args.truth_table_compact_json),
        "boundary_count": boundary_count,
        "truth_table_length": len(output_sequence),
        "lut_count": lut_count,
        "total_templates_generated": total_generated,
        "templates_checked": len(solved_rows),
        "top_templates": args.top_templates,
        "max_generated": args.max_generated,
        "z3_timeout_ms": args.z3_timeout_ms,
        "status_counts": status_counts,
        "exact_candidate_count": len(candidates),
        "kept_candidate_count": len(kept),
        "baseline_score": baseline_score,
        "best_candidate_id": best["candidate_id"] if best else None,
        "best_score_without_penalties": best["score_without_penalties"] if best else None,
        "best_score_with_penalties": best["score_with_penalties"] if best else None,
        "estimated_improvement": estimated_improvement,
        "elapsed_seconds": round(time.time() - start, 3),
        "selected_candidate_json": selected_path,
        "validation_checks": checks,
    }

    with open(os.path.join(args.out_dir, "phase5c_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(args.out_dir, "phase5c_summary.txt"), "w") as f:
        f.write(f"phase5c_status={phase_status}\n")
        f.write(f"boundary_count={boundary_count}\n")
        f.write(f"truth_table_length={len(output_sequence)}\n")
        f.write(f"lut_count={lut_count}\n")
        f.write(f"total_templates_generated={total_generated}\n")
        f.write(f"templates_checked={len(solved_rows)}\n")
        f.write(f"top_templates={args.top_templates}\n")
        f.write(f"max_generated={args.max_generated}\n")
        f.write(f"z3_timeout_ms={args.z3_timeout_ms}\n")
        f.write(f"status_counts={status_counts}\n")
        f.write(f"exact_candidate_count={len(candidates)}\n")
        f.write(f"kept_candidate_count={len(kept)}\n")
        f.write(f"baseline_score={baseline_score}\n")
        f.write(f"best_candidate_id={best['candidate_id'] if best else ''}\n")
        f.write(f"best_score_without_penalties={best['score_without_penalties'] if best else ''}\n")
        f.write(f"best_score_with_penalties={best['score_with_penalties'] if best else ''}\n")
        f.write(f"estimated_improvement={int(estimated_improvement)}\n")
        f.write(f"selected_candidate_json={selected_path}\n")
        f.write(f"elapsed_seconds={round(time.time() - start, 3)}\n")

    print(f"PHASE5C_SAT_{phase_status}")
    print(f"Templates generated: {total_generated}")
    print(f"Templates checked  : {len(solved_rows)}")
    print(f"Exact candidates   : {len(candidates)}")
    print(f"Selected JSON      : {selected_path}")


if __name__ == "__main__":
    main()
