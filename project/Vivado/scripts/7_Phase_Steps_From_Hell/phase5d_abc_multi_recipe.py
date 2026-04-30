#!/usr/bin/env python3
"""
FASE 5D multi-recipe ABC.

Doel:
  - Gebruik Phase 3/4 window truth table.
  - Draai meerdere ABC-recipes.
  - Parse elke mapped BLIF.
  - Check truth-table-equivalence.
  - Reject als ABC meer LUTs gebruikt dan beschikbaar in het window.
  - Map ABC-LUTs op fysieke window-LUTs.
  - Score elke fysieke mapping.
  - Kies de beste kandidaat.

Dit script hergebruikt functies uit:
  phase5d_abc_lut_mapping.py

Dus dat bestand moet in dezelfde map staan.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import phase5d_abc_lut_mapping as base  # noqa: E402


ABC_RECIPES = [
    {
        "name": "r01_strash_if",
        "body": "strash; if -K 6",
    },
    {
        "name": "r02_strash_dc2_if",
        "body": "strash; dc2; if -K 6",
    },
    {
        "name": "r03_rewrite_refactor_balance_if",
        "body": "strash; rewrite; refactor; balance; if -K 6",
    },
    {
        "name": "r04_rewrite_z_refactor_z_balance_if",
        "body": "strash; rewrite -z; refactor -z; balance; if -K 6",
    },
    {
        "name": "r05_dc2_rewrite_refactor_balance_if",
        "body": "strash; dc2; rewrite; refactor; balance; if -K 6",
    },
    {
        "name": "r06_dc2_rewrite_z_refactor_z_balance_if",
        "body": "strash; dc2; rewrite -z; refactor -z; balance; if -K 6",
    },
    {
        "name": "r07_rewrite_refactor_rewrite_if",
        "body": "strash; rewrite; refactor; rewrite; if -K 6",
    },
    {
        "name": "r08_dc2_balance_rewrite_z_if",
        "body": "strash; dc2; balance; rewrite -z; if -K 6",
    },
]


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def run_abc_recipe(abc_bin, pla_path, blif_path, log_path, recipe_body):
    cmd_string = f"read_pla {pla_path}; {recipe_body}; write_blif {blif_path}"
    cmd = [abc_bin, "-c", cmd_string]

    with open(log_path, "w") as log:
        log.write("[CMD] " + " ".join(cmd) + "\n\n")
        log.write("[ABC_COMMAND]\n")
        log.write(cmd_string + "\n\n")
        log.flush()

        proc = subprocess.run(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    return proc.returncode, cmd_string


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase3_json")
    parser.add_argument("truth_table_compact_json")
    parser.add_argument("out_dir")
    parser.add_argument("--abc-bin", default="berkeley-abc")
    parser.add_argument("--max-recipes", type=int, default=len(ABC_RECIPES))
    parser.add_argument("--allow-more-luts", action="store_true",
                        help="Debug only: allow ABC LUT count > window LUT count.")
    args = parser.parse_args()

    start = time.time()

    out_dir = os.path.abspath(args.out_dir)
    abc_dir = os.path.join(out_dir, "abc")
    os.makedirs(abc_dir, exist_ok=True)

    phase3 = load_json(args.phase3_json)
    phase4 = load_json(args.truth_table_compact_json)

    checks = []
    recipe_rows = []
    candidate_rows = []
    candidates = []

    boundary_count = int(phase4["num_boundary_inputs"])
    output_count = int(phase4["num_boundary_outputs"])
    output_sequence = phase4["output_sequence"]
    window_lut_count = len(phase3.get("luts", []))
    baseline_score = base.infer_baseline_score(phase3)

    base.add_check(
        checks,
        "phase3_status",
        "PASS" if phase3.get("phase3_status") == "PASS" else "FAIL",
        phase3.get("phase3_status", ""),
    )

    base.add_check(
        checks,
        "phase4_status",
        "PASS" if phase4.get("phase4_status") == "PASS" else "FAIL",
        phase4.get("phase4_status", ""),
    )

    if output_count != 1:
        base.add_check(checks, "single_output", "FAIL", f"output_count={output_count}")
    else:
        base.add_check(checks, "single_output", "PASS", "1")

    if boundary_count < 1 or boundary_count > 12:
        base.add_check(checks, "boundary_count_supported", "FAIL", str(boundary_count))
    else:
        base.add_check(checks, "boundary_count_supported", "PASS", str(boundary_count))

    expected_len = 1 << boundary_count
    if len(output_sequence) != expected_len:
        base.add_check(
            checks,
            "truth_table_length",
            "FAIL",
            f"len={len(output_sequence)}, expected={expected_len}",
        )
    else:
        base.add_check(checks, "truth_table_length", "PASS", str(expected_len))

    if window_lut_count < 1:
        base.add_check(checks, "window_luts_present", "FAIL", str(window_lut_count))
    else:
        base.add_check(checks, "window_luts_present", "PASS", str(window_lut_count))

    if any(c["status"] == "FAIL" for c in checks):
        write_csv(
            os.path.join(out_dir, "phase5d_multi_validation_checks.csv"),
            ["check", "status", "detail"],
            checks,
        )
        print("ERROR: pre-checks failed", file=sys.stderr)
        sys.exit(1)

    pla_path = os.path.join(abc_dir, "window.pla")
    ones = base.write_pla(pla_path, boundary_count, output_sequence)

    base.add_check(checks, "pla_written", "PASS", f"{pla_path}; ones={ones}")

    selected_recipes = ABC_RECIPES[: args.max_recipes]

    print(f"[phase5d-multi] PLA: {pla_path}", flush=True)
    print(f"[phase5d-multi] window_lut_count={window_lut_count}", flush=True)
    print(f"[phase5d-multi] recipes={len(selected_recipes)}", flush=True)

    for recipe_index, recipe in enumerate(selected_recipes):
        name = recipe["name"]
        body = recipe["body"]

        recipe_dir = os.path.join(abc_dir, name)
        os.makedirs(recipe_dir, exist_ok=True)

        blif_path = os.path.join(recipe_dir, "mapped.blif")
        log_path = os.path.join(recipe_dir, "abc.log")

        print(f"[recipe {recipe_index + 1}/{len(selected_recipes)}] {name}", flush=True)

        rc, abc_cmd = run_abc_recipe(
            abc_bin=args.abc_bin,
            pla_path=pla_path,
            blif_path=blif_path,
            log_path=log_path,
            recipe_body=body,
        )

        row = {
            "recipe_index": recipe_index,
            "recipe_name": name,
            "recipe_body": body,
            "abc_return_code": rc,
            "blif_path": blif_path,
            "abc_log": log_path,
            "abc_lut_count": "",
            "max_node_inputs": "",
            "truth_table_equivalence": 0,
            "physical_assignment": 0,
            "score_without_penalties": "",
            "score_with_penalties": "",
            "estimated_improvement": 0,
            "status": "",
            "error": "",
        }

        if rc != 0:
            row["status"] = "ABC_FAIL"
            row["error"] = f"return_code={rc}"
            recipe_rows.append(row)
            continue

        if not os.path.exists(blif_path):
            row["status"] = "NO_BLIF"
            row["error"] = "mapped.blif missing"
            recipe_rows.append(row)
            continue

        try:
            blif = base.parse_blif(blif_path)
        except Exception as e:
            row["status"] = "BLIF_PARSE_FAIL"
            row["error"] = str(e)
            recipe_rows.append(row)
            continue

        abc_lut_count = len(blif["nodes"])
        max_node_inputs = max((len(n["inputs"]) for n in blif["nodes"]), default=0)

        row["abc_lut_count"] = abc_lut_count
        row["max_node_inputs"] = max_node_inputs

        if max_node_inputs > 6:
            row["status"] = "REJECT_NODE_GT_LUT6"
            row["error"] = f"max_node_inputs={max_node_inputs}"
            recipe_rows.append(row)
            continue

        equivalent, mismatches = base.simulate_blif_network(
            blif,
            boundary_count,
            output_sequence,
        )

        row["truth_table_equivalence"] = int(equivalent)

        if not equivalent:
            row["status"] = "REJECT_NOT_EQUIVALENT"
            row["error"] = str(mismatches[:3])
            recipe_rows.append(row)
            continue

        if abc_lut_count > window_lut_count and not args.allow_more_luts:
            row["status"] = "REJECT_TOO_MANY_LUTS"
            row["error"] = f"abc_lut_count={abc_lut_count} > window_lut_count={window_lut_count}"
            recipe_rows.append(row)
            continue

        assignment, score, error = base.find_best_physical_assignment(blif, phase3)

        if assignment is None:
            row["status"] = "REJECT_NO_PHYSICAL_ASSIGNMENT"
            row["error"] = error
            recipe_rows.append(row)
            continue

        candidate = base.build_candidate_payload(
            blif=blif,
            phase3=phase3,
            assignment=assignment,
            score=score,
            baseline_score=baseline_score,
            output_sequence=output_sequence,
        )

        candidate_id = f"phase5d_multi_abc_{len(candidates):05d}"
        candidate["candidate_id"] = candidate_id
        candidate["recipe_name"] = name
        candidate["recipe_body"] = body
        candidate["abc_log"] = log_path
        candidate["mapped_blif"] = blif_path

        candidates.append(candidate)

        row["physical_assignment"] = 1
        row["score_without_penalties"] = candidate["score_without_penalties"]
        row["score_with_penalties"] = candidate["score_with_penalties"]
        row["estimated_improvement"] = int(candidate["estimated_improvement"])
        row["status"] = candidate["phase5d_status"]

        recipe_rows.append(row)

        print(
            f"  candidate={candidate_id} "
            f"abc_luts={abc_lut_count} "
            f"score={candidate['score_with_penalties']} "
            f"baseline={baseline_score} "
            f"improved={int(candidate['estimated_improvement'])}",
            flush=True,
        )

    candidates.sort(key=lambda c: (
        c["score_with_penalties"],
        c["score_without_penalties"],
        c["cost"]["changed_pin_count"],
        c["candidate_id"],
    ))

    best = candidates[0] if candidates else None

    if best:
        phase_status = best["phase5d_status"]
        base.add_check(checks, "usable_candidates_found", "PASS", str(len(candidates)))
        base.add_check(checks, "best_candidate_selected", "PASS", best["candidate_id"])
    else:
        phase_status = "FAIL_NO_MAPPING_WITHIN_EXISTING_LUT_BUDGET"
        base.add_check(checks, "usable_candidates_found", "FAIL", "0")
        base.add_check(checks, "best_candidate_selected", "FAIL", "none")

    for c in candidates:
        candidate_rows.append({
            "candidate_id": c["candidate_id"],
            "recipe_name": c.get("recipe_name", ""),
            "phase5d_status": c["phase5d_status"],
            "abc_lut_count": c["abc_lut_count"],
            "window_lut_count": c["window_lut_count"],
            "baseline_score": c["baseline_score"],
            "score_without_penalties": c["score_without_penalties"],
            "score_with_penalties": c["score_with_penalties"],
            "estimated_improvement": int(c["estimated_improvement"]),
            "output_driver_cell": c["output_driver"]["physical_cell"],
            "changed_pin_count": c["cost"]["changed_pin_count"],
            "upgrade_count": c["cost"]["upgrade_count"],
            "upgraded_cells": "|".join(c["cost"]["upgraded_cells"]),
            "mapped_blif": c.get("mapped_blif", ""),
            "abc_log": c.get("abc_log", ""),
        })

    write_csv(
        os.path.join(out_dir, "phase5d_multi_recipe_results.csv"),
        [
            "recipe_index",
            "recipe_name",
            "recipe_body",
            "abc_return_code",
            "blif_path",
            "abc_log",
            "abc_lut_count",
            "max_node_inputs",
            "truth_table_equivalence",
            "physical_assignment",
            "score_without_penalties",
            "score_with_penalties",
            "estimated_improvement",
            "status",
            "error",
        ],
        recipe_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5d_multi_candidates.csv"),
        [
            "candidate_id",
            "recipe_name",
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
            "mapped_blif",
            "abc_log",
        ],
        candidate_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5d_multi_validation_checks.csv"),
        ["check", "status", "detail"],
        checks,
    )

    selected_path = os.path.join(out_dir, "phase5d_multi_selected_candidate.json")
    with open(selected_path, "w") as f:
        json.dump(best, f, indent=2)

    summary = {
        "phase": "FASE 5D ABC MULTI",
        "phase5d_multi_status": phase_status,
        "phase3_json": os.path.abspath(args.phase3_json),
        "truth_table_compact_json": os.path.abspath(args.truth_table_compact_json),
        "boundary_count": boundary_count,
        "truth_table_length": len(output_sequence),
        "truth_table_ones": ones,
        "window_lut_count": window_lut_count,
        "baseline_score": baseline_score,
        "recipes_tried": len(selected_recipes),
        "usable_candidate_count": len(candidates),
        "best_candidate_id": best["candidate_id"] if best else None,
        "best_recipe_name": best.get("recipe_name", "") if best else None,
        "best_score_without_penalties": best["score_without_penalties"] if best else None,
        "best_score_with_penalties": best["score_with_penalties"] if best else None,
        "estimated_improvement": best["estimated_improvement"] if best else False,
        "selected_candidate_json": selected_path,
        "elapsed_seconds": round(time.time() - start, 3),
        "validation_checks": checks,
    }

    with open(os.path.join(out_dir, "phase5d_multi_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(out_dir, "phase5d_multi_summary.txt"), "w") as f:
        f.write(f"phase5d_multi_status={phase_status}\n")
        f.write(f"boundary_count={boundary_count}\n")
        f.write(f"truth_table_length={len(output_sequence)}\n")
        f.write(f"truth_table_ones={ones}\n")
        f.write(f"window_lut_count={window_lut_count}\n")
        f.write(f"baseline_score={baseline_score}\n")
        f.write(f"recipes_tried={len(selected_recipes)}\n")
        f.write(f"usable_candidate_count={len(candidates)}\n")
        f.write(f"best_candidate_id={best['candidate_id'] if best else ''}\n")
        f.write(f"best_recipe_name={best.get('recipe_name', '') if best else ''}\n")
        f.write(f"best_score_without_penalties={best['score_without_penalties'] if best else ''}\n")
        f.write(f"best_score_with_penalties={best['score_with_penalties'] if best else ''}\n")
        f.write(f"estimated_improvement={int(best['estimated_improvement']) if best else 0}\n")
        f.write(f"selected_candidate_json={selected_path}\n")
        f.write(f"elapsed_seconds={round(time.time() - start, 3)}\n")

    print(f"PHASE5D_MULTI_{phase_status}")
    print(f"Recipes tried          : {len(selected_recipes)}")
    print(f"Usable candidates      : {len(candidates)}")
    print(f"Selected candidate JSON: {selected_path}")

    if best is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
