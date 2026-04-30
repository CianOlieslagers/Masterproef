#!/usr/bin/env python3
"""
FASE 5E — Convert ABC candidate to Phase 6-compatible candidate JSON.

Doel:
  Neem phase5d_multi_selected_candidate.json en schrijf de legacy filenames die
  de bestaande general flow verwacht:

    phase5b2_fast_selected_candidate.json
    phase5b2_fast_summary.json
    phase5b2_fast_summary.txt
    phase5b2_fast_candidates.csv
    phase5b2_fast_validation_checks.csv

Belangrijk:
  - Deze converter ondersteunt variabel aantal LUT roles.
  - Alle roles krijgen logical_ref="LUT6", omdat Phase6B2UpgradeAndSetInits.java
    elke meegegeven cell naar LUT6 zet.
  - De ABC-logische LUT-grootte blijft bewaard als abc_logical_ref.
"""

import csv
import json
import os
import re
import sys
from collections import OrderedDict


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def add_check(checks, check, status, detail):
    checks.append({
        "check": check,
        "status": status,
        "detail": detail,
    })


def sanitize_role_name(s):
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(s))
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "node"
    return "node_" + s


def main():
    if len(sys.argv) != 3:
        fail(
            "usage: python3 phase5e_convert_abc_to_phase6_candidate.py "
            "<phase5d_multi_selected_candidate.json> <phase5_out_dir>"
        )

    abc_candidate_json = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])

    ensure_dir(out_dir)

    if not os.path.exists(abc_candidate_json):
        fail(f"ABC candidate JSON not found: {abc_candidate_json}")

    with open(abc_candidate_json, "r") as f:
        abc = json.load(f)

    checks = []

    status = abc.get("phase5d_status", "")
    add_check(
        checks,
        "abc_candidate_status",
        "PASS" if status.startswith("PASS") else "FAIL",
        status,
    )

    truth_ok = bool(abc.get("truth_table_equivalence", False))
    add_check(
        checks,
        "truth_table_equivalence",
        "PASS" if truth_ok else "FAIL",
        str(truth_ok),
    )

    nodes = abc.get("nodes", [])
    add_check(
        checks,
        "nodes_present",
        "PASS" if len(nodes) > 0 else "FAIL",
        f"nodes={len(nodes)}",
    )

    output_driver = abc.get("output_driver", {})
    output_cell = output_driver.get("physical_cell", "")
    output_pin = output_driver.get("physical_pin", "")

    if not output_cell or not output_pin:
        add_check(checks, "output_driver_present", "FAIL", str(output_driver))
    else:
        add_check(checks, "output_driver_present", "PASS", f"{output_cell}/{output_pin}")

    output_node = None
    for n in nodes:
        if n.get("physical_cell") == output_cell:
            output_node = n
            break

    if output_node is None:
        add_check(checks, "output_node_found", "FAIL", f"output_cell={output_cell}")
    else:
        add_check(checks, "output_node_found", "PASS", output_node.get("abc_node", ""))

    if any(c["status"] == "FAIL" for c in checks):
        write_csv(
            os.path.join(out_dir, "phase5b2_fast_validation_checks.csv"),
            ["check", "status", "detail"],
            checks,
        )
        fail("pre-checks failed")

    # ------------------------------------------------------------------
    # Build roles.
    # Root = ABC output node.
    # Other ABC nodes become additional roles.
    # ------------------------------------------------------------------

    ordered_nodes = []
    ordered_nodes.append(output_node)
    for n in nodes:
        if n is output_node:
            continue
        ordered_nodes.append(n)

    roles = OrderedDict()

    used_role_names = set()

    for idx, node in enumerate(ordered_nodes):
        is_root = node.get("physical_cell") == output_cell

        if is_root:
            role_name = "root"
            role_code = "R"
        else:
            role_name = sanitize_role_name(node.get("abc_node", f"n{idx}"))
            role_code = f"N{idx}"

        while role_name in used_role_names:
            role_name = role_name + "_x"

        used_role_names.add(role_name)

        role_inputs = []

        for inp in node.get("inputs", []):
            item = {
                "sink_pin": inp["sink_pin"],
            }

            if "boundary_index" in inp:
                item["boundary_index"] = int(inp["boundary_index"])
                if "source_signal" in inp:
                    item["source_signal"] = inp["source_signal"]
            elif "source_cell" in inp:
                item["source"] = f"{inp['source_cell']}/O"
                item["source_cell"] = inp["source_cell"]
                if "source_signal" in inp:
                    item["source_signal"] = inp["source_signal"]
            else:
                fail(f"Unsupported input item without boundary_index/source_cell: {inp}")

            role_inputs.append(item)

        original_ref = node.get("original_ref", "")
        abc_logical_ref = node.get("logical_ref", "")

        # Belangrijk:
        # Phase6B2UpgradeAndSetInits.java zet alles naar LUT6.
        # Daarom moet het Phase 6-contract logical_ref=LUT6 gebruiken.
        phase6_logical_ref = "LUT6"

        roles[role_name] = {
            "role": role_code,
            "abc_node": node.get("abc_node", ""),
            "cell": node["physical_cell"],
            "physical_cell": node["physical_cell"],
            "original_ref": original_ref,
            "abc_logical_ref": abc_logical_ref,
            "logical_ref": phase6_logical_ref,
            "site": node.get("site", ""),
            "bel": node.get("bel", ""),
            "input_count": node.get("input_count", len(role_inputs)),
            "new_INIT": node["new_INIT"],
            "inputs": role_inputs,
        }

    upgraded_cells = sorted({
        r["cell"]
        for r in roles.values()
        if r.get("original_ref") != "LUT6"
    })

    upgrade_count = len(upgraded_cells)

    cost = dict(abc.get("cost", {}))
    cost["upgrade_count_phase6"] = upgrade_count
    cost["upgraded_cells_phase6"] = upgraded_cells

    estimated_improvement = bool(abc.get("estimated_improvement", False))

    phase_status = (
        "PASS_IMPROVED_ESTIMATE"
        if estimated_improvement
        else "PASS_NO_ESTIMATED_IMPROVEMENT"
    )

    selected = {
        "phase": "FASE 5E ABC_TO_PHASE6",
        "phase5b2_fast_status": phase_status,
        "phase5d_status": abc.get("phase5d_status", ""),
        "candidate_id": abc.get("candidate_id", "abc_candidate"),
        "family": "abc_lut6_mapping_phase6_variable_roles",
        "source_family": abc.get("family", ""),
        "same_lut_positions": bool(abc.get("same_lut_positions", True)),
        "same_window_boundary": bool(abc.get("same_window_boundary", True)),
        "root_free": True,
        "lut2_upgrade_allowed": True,
        "all_roles_logical_lut6": True,
        "truth_table_equivalence": True,
        "num_checked_vectors": abc.get("num_checked_vectors", 0),
        "window_depth": abc.get("window_depth", ""),
        "estimated_improvement": estimated_improvement,
        "baseline_score": abc.get("baseline_score", ""),
        "score_without_penalties": abc.get("score_without_penalties", cost.get("score_without_penalties", "")),
        "score_with_penalties": abc.get("score_with_penalties", cost.get("score_with_penalties", "")),
        "abc_lut_count": abc.get("abc_lut_count", len(nodes)),
        "window_lut_count": abc.get("window_lut_count", ""),
        "upgraded_cells": upgraded_cells,
        "upgrade_count": upgrade_count,
        "output_driver_changed": bool(cost.get("output_driver_changed", abc.get("output_driver_changed", False))),
        "output_signal": abc.get("output_signal", "y"),
        "output_driver": {
            "abc_node": output_driver.get("abc_node", ""),
            "physical_cell": output_cell,
            "physical_pin": output_pin,
        },
        "roles": roles,
        "changed_pins": abc.get("changed_pins", []),
        "cost": cost,
        "recipe_name": abc.get("recipe_name", ""),
        "recipe_body": abc.get("recipe_body", ""),
        "abc_log": abc.get("abc_log", ""),
        "mapped_blif": abc.get("mapped_blif", ""),
        "source_abc_candidate_json": abc_candidate_json,
    }

    selected_path = os.path.join(out_dir, "phase5b2_fast_selected_candidate.json")
    with open(selected_path, "w") as f:
        json.dump(selected, f, indent=2)

    summary = {
        "phase": "FASE 5E ABC_TO_PHASE6",
        "phase5b2_fast_status": phase_status,
        "phase5d_status": abc.get("phase5d_status", ""),
        "source_abc_candidate_json": abc_candidate_json,
        "exact_candidate_count": 1,
        "kept_candidate_count": 1,
        "best_candidate_id": selected["candidate_id"],
        "baseline_score": selected["baseline_score"],
        "best_score_without_penalties": selected["score_without_penalties"],
        "best_score_with_penalties": selected["score_with_penalties"],
        "estimated_improvement": estimated_improvement,
        "selected_candidate_json": selected_path,
        "abc_lut_count": selected["abc_lut_count"],
        "window_lut_count": selected["window_lut_count"],
        "role_count": len(roles),
        "upgrade_count": upgrade_count,
        "upgraded_cells": upgraded_cells,
        "validation_checks": checks,
    }

    with open(os.path.join(out_dir, "phase5b2_fast_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(out_dir, "phase5b2_fast_summary.txt"), "w") as f:
        f.write(f"phase5b2_fast_status={phase_status}\n")
        f.write("total_template_count=1\n")
        f.write("templates_checked=1\n")
        f.write("top_templates_to_check=1\n")
        f.write("status_counts={'abc_bridge': 1}\n")
        f.write("exact_candidate_count=1\n")
        f.write("kept_candidate_count=1\n")
        f.write(f"baseline_score={selected['baseline_score']}\n")
        f.write(f"best_candidate_id={selected['candidate_id']}\n")
        f.write(f"best_score_without_penalties={selected['score_without_penalties']}\n")
        f.write(f"best_score_with_penalties={selected['score_with_penalties']}\n")
        f.write(f"estimated_improvement={int(estimated_improvement)}\n")
        f.write(f"selected_candidate_json={selected_path}\n")
        f.write(f"abc_lut_count={selected['abc_lut_count']}\n")
        f.write(f"window_lut_count={selected['window_lut_count']}\n")
        f.write(f"role_count={len(roles)}\n")
        f.write(f"upgrade_count={upgrade_count}\n")
        f.write(f"upgraded_cells={'|'.join(upgraded_cells)}\n")

    candidate_rows = [{
        "candidate_id": selected["candidate_id"],
        "phase5b2_fast_status": phase_status,
        "family": selected["family"],
        "abc_lut_count": selected["abc_lut_count"],
        "window_lut_count": selected["window_lut_count"],
        "role_count": len(roles),
        "baseline_score": selected["baseline_score"],
        "score_without_penalties": selected["score_without_penalties"],
        "score_with_penalties": selected["score_with_penalties"],
        "estimated_improvement": int(estimated_improvement),
        "output_driver_cell": output_cell,
        "output_driver_pin": output_pin,
        "changed_pin_count": len(selected["changed_pins"]),
        "upgrade_count": upgrade_count,
        "upgraded_cells": "|".join(upgraded_cells),
        "recipe_name": selected["recipe_name"],
    }]

    write_csv(
        os.path.join(out_dir, "phase5b2_fast_candidates.csv"),
        [
            "candidate_id",
            "phase5b2_fast_status",
            "family",
            "abc_lut_count",
            "window_lut_count",
            "role_count",
            "baseline_score",
            "score_without_penalties",
            "score_with_penalties",
            "estimated_improvement",
            "output_driver_cell",
            "output_driver_pin",
            "changed_pin_count",
            "upgrade_count",
            "upgraded_cells",
            "recipe_name",
        ],
        candidate_rows,
    )

    add_check(checks, "phase6_roles_created", "PASS", f"roles={len(roles)}")
    add_check(checks, "selected_candidate_written", "PASS", selected_path)

    write_csv(
        os.path.join(out_dir, "phase5b2_fast_validation_checks.csv"),
        ["check", "status", "detail"],
        checks,
    )

    print("PHASE5E_ABC_TO_PHASE6_PASS")
    print(f"Selected candidate: {selected_path}")
    print(f"Roles             : {len(roles)}")
    print(f"Output driver     : {output_cell}/O")
    print(f"Upgraded cells    : {'|'.join(upgraded_cells)}")


if __name__ == "__main__":
    main()
