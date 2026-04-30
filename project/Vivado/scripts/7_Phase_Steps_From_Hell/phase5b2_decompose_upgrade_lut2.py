#!/usr/bin/env python3
"""
FASE 5B.2 — Exacte decompositie met LUT2 -> LUT6 upgrade toegestaan.

Doel:
  Zoek exacte decomposities van de 12-input / 1-output windowfunctie met drie
  fysieke LUT-sites, waarbij alle drie logisch als LUT6 gebruikt mogen worden.

Belangrijk:
  - Geen approximation.
  - Truth-table equivalentie over alle 4096 vectors verplicht.
  - Root/output-LUT mag wisselen.
  - De oorspronkelijke LUT2 mag logisch als LUT6 gebruikt worden.
  - Placement blijft vast.
  - Output is een candidate.json voor FASE 6.

Decompositievorm:
    F(B1..B12) = R(H1(S1), H2(S2), D)

waar:
    R  = root LUT6
    H1 = helper LUT6
    H2 = helper LUT6
    |D| = 4
    S1 en S2 zijn disjuncte subsets van de overige 8 inputs
    1 <= |S1| <= 6
    1 <= |S2| <= 6
    S1 ∪ S2 ∪ D = alle 12 boundary inputs

Gebruik:
  python3 phase5b2_decompose_upgrade_lut2.py \
      <phase3_window_info.json> \
      <truth_table_compact.json> \
      <out_dir> \
      [max_templates_to_solve] \
      [solver_timeout_ms]

Voorbeeld:
  python3 ~/Masterproef/project/Vivado/scripts/phase5b2_decompose_upgrade_lut2.py \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase3_window_info/phase3_window_info.json \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase4_truth_table/truth_table_compact.json \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase5b2_upgrade_lut2 \
      5000 \
      1000

Opmerking:
  max_templates_to_solve = -1 betekent alle templates oplossen.
  Dat kan lang duren. Start eerst met 5000 of 20000.
"""

import csv
import heapq
import itertools
import json
import os
import re
import sys
import time

try:
    import z3
except ImportError:
    print("ERROR: z3-solver is niet geïnstalleerd.", file=sys.stderr)
    print("Installeer met: python3 -m pip install --user z3-solver", file=sys.stderr)
    sys.exit(1)


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
    m = re.fullmatch(r"LUT([1-6])", ref.strip())
    if not m:
        raise ValueError(f"Unsupported LUT ref: {ref}")
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


def eval_lut(init_value: int, input_bits):
    idx = 0
    for i, bit in enumerate(input_bits):
        idx |= (int(bit) & 1) << i
    return (init_value >> idx) & 1


def format_init(value: int, width: int = 64) -> str:
    hex_digits = max(1, width // 4)
    return f"{width}'h{value:0{hex_digits}X}"


def project_assignment(row_index: int, boundary_indices):
    out = 0
    for local_i, bidx in enumerate(boundary_indices):
        bit = (row_index >> (bidx - 1)) & 1
        out |= bit << local_i
    return out


def expand_support_init_to_lut6(init_value: int, support_size: int) -> int:
    """
    Embed een k-input functie in een LUT6 INIT.
    De support gebruikt I0..I(k-1).
    I(k)..I5 worden don't-care en dus gerepliceerd.
    """
    if support_size > 6:
        raise ValueError("support_size > 6")

    expanded = 0

    for idx6 in range(64):
        small_idx = idx6 & ((1 << support_size) - 1)
        bit = (init_value >> small_idx) & 1
        expanded |= bit << idx6

    return expanded


def root_index(h1_out, h2_out, d_assignment, d_size=4):
    idx = (h1_out << 0) | (h2_out << 1)

    for i in range(d_size):
        bit = (d_assignment >> i) & 1
        idx |= bit << (i + 2)

    return idx


def solve_template_z3(output_sequence, boundary_count, s1, s2, d, timeout_ms):
    """
    Exacte SAT/SMT-check voor:
        F = R(H1(S1), H2(S2), D)

    H1, H2 en R zijn onbekende truth tables.
    """
    s1_size = len(s1)
    s2_size = len(s2)
    d_size = len(d)

    if s1_size > 6 or s2_size > 6 or d_size != 4:
        return None, "invalid_template_shape"

    solver = z3.Solver()
    solver.set("timeout", timeout_ms)

    h1_bits = [z3.Bool(f"h1_{i}") for i in range(1 << s1_size)]
    h2_bits = [z3.Bool(f"h2_{i}") for i in range(1 << s2_size)]
    r_bits = [z3.Bool(f"r_{i}") for i in range(64)]

    for row in range(1 << boundary_count):
        h1_idx = project_assignment(row, s1)
        h2_idx = project_assignment(row, s2)
        d_idx = project_assignment(row, d)

        h1 = h1_bits[h1_idx]
        h2 = h2_bits[h2_idx]
        expected = z3.BoolVal(output_sequence[row] == "1")

        for a in (False, True):
            for b in (False, True):
                ridx = root_index(int(a), int(b), d_idx, d_size)
                solver.add(
                    z3.Implies(
                        z3.And(h1 == z3.BoolVal(a), h2 == z3.BoolVal(b)),
                        r_bits[ridx] == expected,
                    )
                )

    result = solver.check()

    if result == z3.unknown:
        return None, "solver_unknown_or_timeout"

    if result != z3.sat:
        return None, "unsat"

    model = solver.model()

    h1_init = 0
    for i, bit in enumerate(h1_bits):
        if z3.is_true(model.eval(bit, model_completion=True)):
            h1_init |= 1 << i

    h2_init = 0
    for i, bit in enumerate(h2_bits):
        if z3.is_true(model.eval(bit, model_completion=True)):
            h2_init |= 1 << i

    root_init = 0
    for i, bit in enumerate(r_bits):
        if z3.is_true(model.eval(bit, model_completion=True)):
            root_init |= 1 << i

    return {
        "h1_init_int_small": h1_init,
        "h2_init_int_small": h2_init,
        "h1_init_int_64": expand_support_init_to_lut6(h1_init, s1_size),
        "h2_init_int_64": expand_support_init_to_lut6(h2_init, s2_size),
        "root_init_int_64": root_init,
        "solver_result": "sat",
    }, "sat"


def simulate_candidate(output_sequence, boundary_count, s1, s2, d, h1_init_64, h2_init_64, root_init_64):
    mismatches = []

    for row in range(1 << boundary_count):
        h1_idx_small = project_assignment(row, s1)
        h2_idx_small = project_assignment(row, s2)
        d_idx = project_assignment(row, d)

        h1_out = (h1_init_64 >> h1_idx_small) & 1
        h2_out = (h2_init_64 >> h2_idx_small) & 1

        root_inputs = [
            h1_out,
            h2_out,
            (d_idx >> 0) & 1,
            (d_idx >> 1) & 1,
            (d_idx >> 2) & 1,
            (d_idx >> 3) & 1,
        ]

        y = eval_lut(root_init_64, root_inputs)
        expected = int(output_sequence[row])

        if y != expected:
            mismatches.append({"row": row, "expected": expected, "actual": y})
            if len(mismatches) >= 20:
                break

    return mismatches


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


def template_cost(template, phase3):
    """
    Voorselectie-score zonder solver.
    """
    boundary_by_index = boundary_by_index_map(phase3)

    root = template["root"]
    h1 = template["h1"]
    h2 = template["h2"]
    s1 = template["S1"]
    s2 = template["S2"]
    d = template["D"]

    internal_m1 = manhattan(h1["site"], root["site"])
    internal_m2 = manhattan(h2["site"], root["site"])

    internal_total = (internal_m1 or 0) + (internal_m2 or 0)
    internal_max = max(internal_m1 or 0, internal_m2 or 0)

    boundary_total = 0
    boundary_missing = 0

    def add_boundary(bidx, sink_site):
        nonlocal boundary_total, boundary_missing

        src_site = boundary_by_index[int(bidx)].get("driver_site", "")
        m = manhattan(src_site, sink_site)

        if m is None:
            boundary_missing += 1
        else:
            boundary_total += m

    for b in s1:
        add_boundary(b, h1["site"])

    for b in s2:
        add_boundary(b, h2["site"])

    for b in d:
        add_boundary(b, root["site"])

    current_root = phase3["boundary_outputs"][0]["source_cell"]
    output_driver_changed = root["cell"] != current_root

    upgraded_cells = []
    for slot, support_size in [(root, 6), (h1, len(s1)), (h2, len(s2))]:
        original_cap = ref_capacity(slot["ref"])
        if original_cap < support_size or slot["ref"] != "LUT6":
            upgraded_cells.append(slot["cell"])

    upgrade_count = len(set(upgraded_cells))

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

    return {
        "internal_manhattan_h1_to_root": internal_m1,
        "internal_manhattan_h2_to_root": internal_m2,
        "internal_manhattan_total": internal_total,
        "internal_manhattan_max": internal_max,
        "boundary_manhattan_total": boundary_total,
        "boundary_manhattan_missing": boundary_missing,
        "output_driver_changed": output_driver_changed,
        "upgrade_count": upgrade_count,
        "upgraded_cells": sorted(set(upgraded_cells)),
        "score_without_penalties": score_without_penalties,
        "score_with_penalties": score_with_penalties,
    }


def compute_changed_pins(candidate, phase3):
    boundary_by_index = boundary_by_index_map(phase3)
    old_pin_map = build_old_pin_map(phase3)

    root = candidate["root"]
    h1 = candidate["h1"]
    h2 = candidate["h2"]

    new_pin_map = {}

    for i, bidx in enumerate(candidate["S1"]):
        new_pin_map[(h1["cell"], f"I{i}")] = new_source_id_from_boundary(bidx, boundary_by_index)

    for i, bidx in enumerate(candidate["S2"]):
        new_pin_map[(h2["cell"], f"I{i}")] = new_source_id_from_boundary(bidx, boundary_by_index)

    new_pin_map[(root["cell"], "I0")] = f"INT:{h1['cell']}/O"
    new_pin_map[(root["cell"], "I1")] = f"INT:{h2['cell']}/O"

    for i, bidx in enumerate(candidate["D"]):
        new_pin_map[(root["cell"], f"I{i + 2}")] = new_source_id_from_boundary(bidx, boundary_by_index)

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


def infer_baseline_score(phase3):
    """
    Baseline-score uit de bestaande phase3-structuur benaderen.
    """
    edges = phase3.get("internal_edges", [])
    internal_total = 0
    internal_max = 0

    for e in edges:
        m = e.get("manhattan_distance", 0)
        try:
            m = int(m)
        except Exception:
            m = 0
        internal_total += m
        internal_max = max(internal_max, m)

    boundary_total = 0
    boundary_by_net = {b["net"]: b for b in phase3.get("boundary_inputs", [])}

    for pin in phase3.get("lut_input_pins", []):
        if pin.get("classification") != "boundary_input":
            continue

        src = boundary_by_net.get(pin.get("net", ""))
        sink_cell = pin.get("sink_cell", "")
        sink_site = ""

        for l in phase3.get("luts", []):
            if l["cell"] == sink_cell:
                sink_site = l.get("site", "")

        if src:
            m = manhattan(src.get("driver_site", ""), sink_site)
            if m is not None:
                boundary_total += m

    return internal_max * 1000 + internal_total * 100 + boundary_total


def generate_templates(phase3):
    luts = phase3.get("luts", [])
    all_inputs = tuple(range(1, 13))

    role_id = 0

    for root in luts:
        helpers = [x for x in luts if x["cell"] != root["cell"]]

        for h1, h2 in itertools.permutations(helpers, 2):
            role_id += 1

            for d in itertools.combinations(all_inputs, 4):
                remaining = tuple(x for x in all_inputs if x not in d)

                # Partition remaining 8 inputs over H1/H2.
                # Non-overlap, both support sizes <= 6.
                for k in range(2, 7):
                    for s1 in itertools.combinations(remaining, k):
                        s2 = tuple(x for x in remaining if x not in s1)

                        if len(s2) < 1 or len(s2) > 6:
                            continue

                        template = {
                            "role_id": role_id,
                            "root": root,
                            "h1": h1,
                            "h2": h2,
                            "D": tuple(d),
                            "S1": tuple(s1),
                            "S2": tuple(s2),
                        }

                        cost = template_cost(template, phase3)
                        template.update(cost)

                        yield template


def main():
    if len(sys.argv) < 4:
        fail(
            "usage: python3 phase5b2_decompose_upgrade_lut2.py "
            "<phase3_window_info.json> <truth_table_compact.json> <out_dir> "
            "[max_templates_to_solve] [solver_timeout_ms]"
        )

    phase3_path = os.path.abspath(sys.argv[1])
    phase4_path = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])

    max_templates_to_solve = int(sys.argv[4]) if len(sys.argv) >= 5 else 5000
    solver_timeout_ms = int(sys.argv[5]) if len(sys.argv) >= 6 else 1000

    ensure_dir(out_dir)

    with open(phase3_path, "r") as f:
        phase3 = json.load(f)

    with open(phase4_path, "r") as f:
        phase4 = json.load(f)

    checks = []

    add_check(checks, "phase3_status", "PASS" if phase3.get("phase3_status") == "PASS" else "FAIL", phase3.get("phase3_status", ""))
    add_check(checks, "phase4_status", "PASS" if phase4.get("phase4_status") == "PASS" else "FAIL", phase4.get("phase4_status", ""))

    boundary_count = int(phase4["num_boundary_inputs"])
    output_sequence = phase4["output_sequence"]

    if boundary_count != 12:
        add_check(checks, "boundary_count_is_12", "FAIL", f"boundary_count={boundary_count}")
    else:
        add_check(checks, "boundary_count_is_12", "PASS", "12")

    if int(phase4["num_boundary_outputs"]) != 1:
        add_check(checks, "single_output", "FAIL", str(phase4["num_boundary_outputs"]))
    else:
        add_check(checks, "single_output", "PASS", "1")

    if len(phase3.get("luts", [])) != 3:
        add_check(checks, "three_luts", "FAIL", f"{len(phase3.get('luts', []))}")
    else:
        add_check(checks, "three_luts", "PASS", "3")

    if any(c["status"] == "FAIL" for c in checks):
        write_csv(os.path.join(out_dir, "phase5b2_validation_checks.csv"), ["check", "status", "detail"], checks)
        fail("pre-checks failed")

    baseline_score = infer_baseline_score(phase3)

    start = time.time()

    # Genereer alle templates, sorteer op cost, los dan de beste N op.
    templates = list(generate_templates(phase3))
    total_template_count = len(templates)

    templates.sort(key=lambda t: (t["score_without_penalties"], t["score_with_penalties"]))

    if max_templates_to_solve >= 0:
        templates_to_solve = templates[:max_templates_to_solve]
    else:
        templates_to_solve = templates

    add_check(checks, "templates_generated", "PASS", f"total={total_template_count}, solving={len(templates_to_solve)}")
    add_check(checks, "z3_available", "PASS", z3.get_version_string())

    solved_rows = []
    candidate_rows = []
    candidates = []

    status_counts = {}

    for idx, template in enumerate(templates_to_solve):
        result, status = solve_template_z3(
            output_sequence,
            boundary_count,
            template["S1"],
            template["S2"],
            template["D"],
            solver_timeout_ms,
        )

        status_counts[status] = status_counts.get(status, 0) + 1

        solved_rows.append({
            "solve_index": idx,
            "status": status,
            "role_id": template["role_id"],
            "root_cell": template["root"]["cell"],
            "h1_cell": template["h1"]["cell"],
            "h2_cell": template["h2"]["cell"],
            "S1": "|".join(map(str, template["S1"])),
            "S2": "|".join(map(str, template["S2"])),
            "D": "|".join(map(str, template["D"])),
            "score_without_penalties": template["score_without_penalties"],
            "score_with_penalties": template["score_with_penalties"],
            "internal_manhattan_max": template["internal_manhattan_max"],
            "boundary_manhattan_total": template["boundary_manhattan_total"],
            "upgrade_count": template["upgrade_count"],
            "upgraded_cells": "|".join(template["upgraded_cells"]),
            "output_driver_changed": int(template["output_driver_changed"]),
        })

        if result is None:
            continue

        mismatches = simulate_candidate(
            output_sequence,
            boundary_count,
            template["S1"],
            template["S2"],
            template["D"],
            result["h1_init_int_64"],
            result["h2_init_int_64"],
            result["root_init_int_64"],
        )

        if mismatches:
            status_counts["post_sim_mismatch"] = status_counts.get("post_sim_mismatch", 0) + 1
            continue

        candidate_id = f"phase5b2_exact_{len(candidates):05d}"

        changed_pins = compute_changed_pins(template, phase3)

        candidate = {
            "candidate_id": candidate_id,
            "family": "root_free_lut2_to_lut6_exact_decomposition",
            "root": template["root"],
            "h1": template["h1"],
            "h2": template["h2"],
            "S1": template["S1"],
            "S2": template["S2"],
            "D": template["D"],
            "h1_init_64": result["h1_init_int_64"],
            "h2_init_64": result["h2_init_int_64"],
            "root_init_64": result["root_init_int_64"],
            "h1_init": format_init(result["h1_init_int_64"], 64),
            "h2_init": format_init(result["h2_init_int_64"], 64),
            "root_init": format_init(result["root_init_int_64"], 64),
            "truth_table_equivalence": True,
            "num_checked_vectors": 1 << boundary_count,
            "window_depth": 2,
            "changed_pins": changed_pins,
            "changed_pin_count": len(changed_pins),
            **{k: template[k] for k in [
                "score_without_penalties",
                "score_with_penalties",
                "internal_manhattan_h1_to_root",
                "internal_manhattan_h2_to_root",
                "internal_manhattan_total",
                "internal_manhattan_max",
                "boundary_manhattan_total",
                "boundary_manhattan_missing",
                "output_driver_changed",
                "upgrade_count",
                "upgraded_cells",
            ]},
        }

        candidates.append(candidate)

    if candidates:
        add_check(checks, "exact_candidates_found", "PASS", str(len(candidates)))
    else:
        add_check(checks, "exact_candidates_found", "FAIL", "0")

    candidates.sort(key=lambda c: (c["score_without_penalties"], c["score_with_penalties"], c["changed_pin_count"]))

    best = candidates[0] if candidates else None

    if best:
        estimated_improvement = best["score_without_penalties"] < baseline_score
        add_check(checks, "best_candidate_selected", "PASS", f"{best['candidate_id']} score={best['score_without_penalties']} baseline={baseline_score}")
    else:
        estimated_improvement = False
        add_check(checks, "best_candidate_selected", "FAIL", "none")

    if best and estimated_improvement:
        phase_status = "PASS_IMPROVED_ESTIMATE"
    elif best:
        phase_status = "PASS_NO_ESTIMATED_IMPROVEMENT"
    else:
        phase_status = "FAIL"

    for c in candidates:
        candidate_rows.append({
            "candidate_id": c["candidate_id"],
            "root_cell": c["root"]["cell"],
            "root_original_ref": c["root"]["ref"],
            "h1_cell": c["h1"]["cell"],
            "h1_original_ref": c["h1"]["ref"],
            "h2_cell": c["h2"]["cell"],
            "h2_original_ref": c["h2"]["ref"],
            "S1": "|".join(map(str, c["S1"])),
            "S2": "|".join(map(str, c["S2"])),
            "D": "|".join(map(str, c["D"])),
            "root_init": c["root_init"],
            "h1_init": c["h1_init"],
            "h2_init": c["h2_init"],
            "truth_table_equivalence": int(c["truth_table_equivalence"]),
            "num_checked_vectors": c["num_checked_vectors"],
            "changed_pin_count": c["changed_pin_count"],
            "upgrade_count": c["upgrade_count"],
            "upgraded_cells": "|".join(c["upgraded_cells"]),
            "output_driver_changed": int(c["output_driver_changed"]),
            "internal_manhattan_h1_to_root": c["internal_manhattan_h1_to_root"],
            "internal_manhattan_h2_to_root": c["internal_manhattan_h2_to_root"],
            "internal_manhattan_max": c["internal_manhattan_max"],
            "boundary_manhattan_total": c["boundary_manhattan_total"],
            "score_without_penalties": c["score_without_penalties"],
            "score_with_penalties": c["score_with_penalties"],
        })

    write_csv(
        os.path.join(out_dir, "phase5b2_solved_templates.csv"),
        [
            "solve_index", "status", "role_id", "root_cell", "h1_cell", "h2_cell",
            "S1", "S2", "D", "score_without_penalties", "score_with_penalties",
            "internal_manhattan_max", "boundary_manhattan_total",
            "upgrade_count", "upgraded_cells", "output_driver_changed"
        ],
        solved_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5b2_candidates.csv"),
        [
            "candidate_id", "root_cell", "root_original_ref",
            "h1_cell", "h1_original_ref", "h2_cell", "h2_original_ref",
            "S1", "S2", "D", "root_init", "h1_init", "h2_init",
            "truth_table_equivalence", "num_checked_vectors", "changed_pin_count",
            "upgrade_count", "upgraded_cells", "output_driver_changed",
            "internal_manhattan_h1_to_root", "internal_manhattan_h2_to_root",
            "internal_manhattan_max", "boundary_manhattan_total",
            "score_without_penalties", "score_with_penalties"
        ],
        candidate_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5b2_validation_checks.csv"),
        ["check", "status", "detail"],
        checks,
    )

    selected_path = os.path.join(out_dir, "phase5b2_selected_candidate.json")

    selected_payload = None

    if best:
        selected_payload = {
            "phase": "FASE 5B.2",
            "phase5b2_status": phase_status,
            "candidate_id": best["candidate_id"],
            "family": best["family"],
            "same_lut_positions": True,
            "same_window_boundary": True,
            "root_free": True,
            "lut2_upgrade_allowed": True,
            "all_roles_logical_lut6": True,
            "truth_table_equivalence": True,
            "num_checked_vectors": best["num_checked_vectors"],
            "window_depth": 2,
            "estimated_improvement": estimated_improvement,
            "baseline_score": baseline_score,
            "score_without_penalties": best["score_without_penalties"],
            "score_with_penalties": best["score_with_penalties"],
            "upgraded_cells": best["upgraded_cells"],
            "upgrade_count": best["upgrade_count"],
            "output_driver_changed": best["output_driver_changed"],
            "roles": {
                "root": {
                    "role": "R",
                    "cell": best["root"]["cell"],
                    "original_ref": best["root"]["ref"],
                    "logical_ref": "LUT6",
                    "site": best["root"]["site"],
                    "bel": best["root"]["bel"],
                    "new_INIT": best["root_init"],
                    "inputs": (
                        [
                            {"sink_pin": "I0", "source": "helper1/O", "source_cell": best["h1"]["cell"]},
                            {"sink_pin": "I1", "source": "helper2/O", "source_cell": best["h2"]["cell"]},
                        ]
                        + [
                            {"sink_pin": f"I{i+2}", "boundary_index": int(b)}
                            for i, b in enumerate(best["D"])
                        ]
                    ),
                },
                "helper1": {
                    "role": "H1",
                    "cell": best["h1"]["cell"],
                    "original_ref": best["h1"]["ref"],
                    "logical_ref": "LUT6",
                    "site": best["h1"]["site"],
                    "bel": best["h1"]["bel"],
                    "new_INIT": best["h1_init"],
                    "inputs": [
                        {"sink_pin": f"I{i}", "boundary_index": int(b)}
                        for i, b in enumerate(best["S1"])
                    ],
                },
                "helper2": {
                    "role": "H2",
                    "cell": best["h2"]["cell"],
                    "original_ref": best["h2"]["ref"],
                    "logical_ref": "LUT6",
                    "site": best["h2"]["site"],
                    "bel": best["h2"]["bel"],
                    "new_INIT": best["h2_init"],
                    "inputs": [
                        {"sink_pin": f"I{i}", "boundary_index": int(b)}
                        for i, b in enumerate(best["S2"])
                    ],
                },
            },
            "changed_pins": best["changed_pins"],
            "cost": {
                "internal_manhattan_h1_to_root": best["internal_manhattan_h1_to_root"],
                "internal_manhattan_h2_to_root": best["internal_manhattan_h2_to_root"],
                "internal_manhattan_total": best["internal_manhattan_total"],
                "internal_manhattan_max": best["internal_manhattan_max"],
                "boundary_manhattan_total": best["boundary_manhattan_total"],
                "boundary_manhattan_missing": best["boundary_manhattan_missing"],
                "changed_pin_count": best["changed_pin_count"],
            },
        }

    with open(selected_path, "w") as f:
        json.dump(selected_payload, f, indent=2)

    summary_json = {
        "phase": "FASE 5B.2",
        "phase5b2_status": phase_status,
        "phase3_json": phase3_path,
        "truth_table_compact_json": phase4_path,
        "total_template_count": total_template_count,
        "templates_solved": len(templates_to_solve),
        "max_templates_to_solve": max_templates_to_solve,
        "solver_timeout_ms": solver_timeout_ms,
        "z3_version": z3.get_version_string(),
        "status_counts": status_counts,
        "exact_candidate_count": len(candidates),
        "baseline_score": baseline_score,
        "best_candidate_id": best["candidate_id"] if best else None,
        "best_score_without_penalties": best["score_without_penalties"] if best else None,
        "best_score_with_penalties": best["score_with_penalties"] if best else None,
        "estimated_improvement": estimated_improvement,
        "elapsed_seconds": round(time.time() - start, 3),
        "validation_checks": checks,
    }

    with open(os.path.join(out_dir, "phase5b2_summary.json"), "w") as f:
        json.dump(summary_json, f, indent=2)

    with open(os.path.join(out_dir, "phase5b2_summary.txt"), "w") as f:
        f.write(f"phase5b2_status={phase_status}\n")
        f.write(f"total_template_count={total_template_count}\n")
        f.write(f"templates_solved={len(templates_to_solve)}\n")
        f.write(f"max_templates_to_solve={max_templates_to_solve}\n")
        f.write(f"solver_timeout_ms={solver_timeout_ms}\n")
        f.write(f"status_counts={status_counts}\n")
        f.write(f"exact_candidate_count={len(candidates)}\n")
        f.write(f"baseline_score={baseline_score}\n")
        f.write(f"best_candidate_id={best['candidate_id'] if best else ''}\n")
        f.write(f"best_score_without_penalties={best['score_without_penalties'] if best else ''}\n")
        f.write(f"best_score_with_penalties={best['score_with_penalties'] if best else ''}\n")
        f.write(f"estimated_improvement={int(estimated_improvement)}\n")
        f.write(f"selected_candidate_json={selected_path}\n")
        f.write(f"elapsed_seconds={round(time.time() - start, 3)}\n")

    print(f"PHASE5B2_{phase_status}")
    print(f"Total templates : {total_template_count}")
    print(f"Solved templates: {len(templates_to_solve)}")
    print(f"Exact candidates: {len(candidates)}")
    print(f"Selected JSON   : {selected_path}")


if __name__ == "__main__":
    main()
