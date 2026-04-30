#!/usr/bin/env python3
"""
FASE 5A — Exacte fixed-placement LUT-decompositie.

Doel:
  Zoek exacte decomposities van de originele windowfunctie:

      F(B1..Bn) = R(G1(S1), G2(S2), D)

  met:
      |S1| = 6  -> big helper LUT6
      |S2| = 2  -> small helper LUT2
      |D|  = 4  -> directe inputs naar root LUT6

  Root blijft fysiek dezelfde LUT die de boundary output aandrijft.
  LUT-capaciteiten blijven zoals in FASE 3:
      LUT6, LUT6, LUT2

Geen approximation:
  Elke kandidaat wordt over alle truth-table rows opnieuw gesimuleerd.
  Alleen exacte matches worden aanvaard.

Gebruik:
  python3 phase5a_decompose_fixed_window.py \
      <phase3_window_info.json> \
      <truth_table_compact.json> \
      <out_dir> \
      [max_exact_candidates_to_keep]

Voorbeeld:
  python3 ~/Masterproef/project/Vivado/scripts/phase5a_decompose_fixed_window.py \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase3_window_info/phase3_window_info.json \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase4_truth_table/truth_table_compact.json \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase5a_decomposition \
      200
"""

import csv
import itertools
import json
import os
import sys
from collections import defaultdict


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


def site_xy(site: str):
    import re
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


def ref_capacity(ref: str) -> int:
    if ref == "LUT6":
        return 6
    if ref == "LUT5":
        return 5
    if ref == "LUT4":
        return 4
    if ref == "LUT3":
        return 3
    if ref == "LUT2":
        return 2
    if ref == "LUT1":
        return 1
    raise ValueError(f"Unsupported LUT ref: {ref}")


def eval_lut(init_value: int, input_bits):
    idx = 0
    for i, bit in enumerate(input_bits):
        idx |= (int(bit) & 1) << i
    return (init_value >> idx) & 1


def format_init(value: int, width: int) -> str:
    hex_digits = max(1, width // 4)
    return f"{width}'h{value:0{hex_digits}X}"


def bits_from_row(row_index: int, boundary_count: int):
    return {i: (row_index >> (i - 1)) & 1 for i in range(1, boundary_count + 1)}


def project_assignment(row_index: int, boundary_indices):
    """
    Geeft assignment-index voor boundary_indices.
    boundary_indices[0] wordt LUT input I0 / LSB.
    """
    out = 0
    for local_i, bidx in enumerate(boundary_indices):
        bit = (row_index >> (bidx - 1)) & 1
        out |= bit << local_i
    return out


def build_row_index_from_parts(s1_assignment, s1, s2_assignment, s2, d_assignment, d):
    row = 0

    for local_i, bidx in enumerate(s1):
        bit = (s1_assignment >> local_i) & 1
        row |= bit << (bidx - 1)

    for local_i, bidx in enumerate(s2):
        bit = (s2_assignment >> local_i) & 1
        row |= bit << (bidx - 1)

    for local_i, bidx in enumerate(d):
        bit = (d_assignment >> local_i) & 1
        row |= bit << (bidx - 1)

    return row


def check_decomposition_for_partition(output_sequence, boundary_count, s1, s2, d, g2_mask):
    """
    Exacte constructieve test voor:

        F = R(G1(S1), G2(S2), D)

    Voor een gekozen G2-functie:
      - groepeer S2-assignments volgens G2-output.
      - Voor elke S1-assignment bereken een signature:
            per D en per G2-outputgroep moet F constant zijn.
      - Als er maximaal 2 verschillende signatures zijn, bestaat G1.
      - R wordt rechtstreeks uit de signatures afgeleid.

    Returns:
      None indien onmogelijk.
      dict met g1_init, g2_init, root_init indien mogelijk.
    """
    s1_size = len(s1)
    s2_size = len(s2)
    d_size = len(d)

    assert s1_size == 6
    assert s2_size == 2
    assert d_size == 4

    # G2 outputs voor elke S2 assignment.
    g2_values = {
        s2_assignment: (g2_mask >> s2_assignment) & 1
        for s2_assignment in range(1 << s2_size)
    }

    signatures = []
    sig_for_s1 = {}

    for s1_assignment in range(1 << s1_size):
        signature = []

        valid = True

        for d_assignment in range(1 << d_size):
            for g2_out in (0, 1):
                vals = set()

                for s2_assignment in range(1 << s2_size):
                    if g2_values[s2_assignment] != g2_out:
                        continue

                    row = build_row_index_from_parts(
                        s1_assignment, s1,
                        s2_assignment, s2,
                        d_assignment, d,
                    )

                    vals.add(int(output_sequence[row]))

                if len(vals) == 0:
                    # Deze G2-outputklasse wordt niet gebruikt.
                    signature.append(None)
                elif len(vals) == 1:
                    signature.append(next(iter(vals)))
                else:
                    valid = False
                    break

            if not valid:
                break

        if not valid:
            return None

        sig = tuple(signature)
        sig_for_s1[s1_assignment] = sig

        if sig not in signatures:
            signatures.append(sig)

            if len(signatures) > 2:
                return None

    # Assign G1 labels to signatures.
    sig_to_g1 = {sig: idx for idx, sig in enumerate(signatures)}

    # G1 INIT.
    g1_init = 0
    for s1_assignment in range(1 << s1_size):
        bit = sig_to_g1[sig_for_s1[s1_assignment]]
        g1_init |= bit << s1_assignment

    # G2 INIT is gewoon de mask voor 2 inputs.
    g2_init = g2_mask

    # Root INIT:
    # Root input order:
    #   I0 = G1 output
    #   I1 = G2 output
    #   I2 = D0
    #   I3 = D1
    #   I4 = D2
    #   I5 = D3
    root_init = 0

    for d_assignment in range(1 << d_size):
        for g2_out in (0, 1):
            for g1_out in (0, 1):
                root_idx = (
                    (g1_out << 0)
                    | (g2_out << 1)
                    | ((d_assignment & 0b0001) << 2)
                    | ((d_assignment & 0b0010) << 2)
                    | ((d_assignment & 0b0100) << 2)
                    | ((d_assignment & 0b1000) << 2)
                )

                # root_idx hierboven is equivalent aan:
                # g1 + 2*g2 + 4*d0 + 8*d1 + 16*d2 + 32*d3

                if g1_out >= len(signatures):
                    val = 0
                else:
                    sig = signatures[g1_out]
                    sig_pos = d_assignment * 2 + g2_out
                    sig_val = sig[sig_pos]
                    val = 0 if sig_val is None else sig_val

                root_init |= int(val) << root_idx

    return {
        "g1_init_int": g1_init,
        "g2_init_int": g2_init,
        "root_init_int": root_init,
        "num_signatures": len(signatures),
        "g2_mask": g2_mask,
        "signatures": signatures,
    }


def simulate_candidate(output_sequence, boundary_count, s1, s2, d, g1_init, g2_init, root_init):
    """
    Simuleer kandidaat over alle rows en vergelijk met originele F.
    """
    mismatches = []

    for row in range(1 << boundary_count):
        g1_idx = project_assignment(row, s1)
        g2_idx = project_assignment(row, s2)
        d_idx = project_assignment(row, d)

        g1_out = (g1_init >> g1_idx) & 1
        g2_out = (g2_init >> g2_idx) & 1

        root_inputs = [
            g1_out,
            g2_out,
            (d_idx >> 0) & 1,
            (d_idx >> 1) & 1,
            (d_idx >> 2) & 1,
            (d_idx >> 3) & 1,
        ]

        y = eval_lut(root_init, root_inputs)
        expected = int(output_sequence[row])

        if y != expected:
            mismatches.append({
                "row": row,
                "expected": expected,
                "actual": y,
            })

            if len(mismatches) >= 20:
                break

    return mismatches


def source_for_boundary_index(boundary_index, boundary_by_index):
    b = boundary_by_index[int(boundary_index)]
    return f"BI{boundary_index}:{b.get('net', '')}"


def old_source_id(pin):
    classification = pin.get("classification", "")
    if classification == "internal":
        return f"INT:{pin.get('driver_cell', '')}/O"
    if classification == "boundary_input":
        return f"BI_NET:{pin.get('net', '')}"
    return classification


def new_source_id_from_boundary(boundary_index, boundary_by_index):
    net = boundary_by_index[int(boundary_index)].get("net", "")
    return f"BI_NET:{net}"


def build_old_pin_map(phase3):
    old = {}
    for pin in phase3.get("lut_input_pins", []):
        key = (pin["sink_cell"], pin["sink_ref_pin"])
        old[key] = old_source_id(pin)
    return old


def compute_candidate_cost(candidate, phase3, slots):
    """
    Schatting. Dit is géén Vivado timing.
    """
    boundary_by_index = {
        int(b["boundary_index"]): b for b in phase3["boundary_inputs"]
    }

    old_pin_map = build_old_pin_map(phase3)

    big = slots["big_helper"]
    small = slots["small_helper"]
    root = slots["root"]

    big_site = big["site"]
    small_site = small["site"]
    root_site = root["site"]

    # Nieuwe canonical pin mapping.
    new_pin_map = {}

    for local_i, bidx in enumerate(candidate["S1"]):
        new_pin_map[(big["cell"], f"I{local_i}")] = new_source_id_from_boundary(bidx, boundary_by_index)

    for local_i, bidx in enumerate(candidate["S2"]):
        new_pin_map[(small["cell"], f"I{local_i}")] = new_source_id_from_boundary(bidx, boundary_by_index)

    new_pin_map[(root["cell"], "I0")] = f"INT:{big['cell']}/O"
    new_pin_map[(root["cell"], "I1")] = f"INT:{small['cell']}/O"

    for local_i, bidx in enumerate(candidate["D"]):
        new_pin_map[(root["cell"], f"I{local_i + 2}")] = new_source_id_from_boundary(bidx, boundary_by_index)

    changed_pins = []
    for key, new_src in new_pin_map.items():
        old_src = old_pin_map.get(key, "")
        if old_src != new_src:
            changed_pins.append({
                "sink_cell": key[0],
                "sink_pin": key[1],
                "old_source": old_src,
                "new_source": new_src,
            })

    # Interne Manhattan blijft in 5A meestal gelijk:
    m_big_root = manhattan(big_site, root_site)
    m_small_root = manhattan(small_site, root_site)

    internal_manhattan_total = (m_big_root or 0) + (m_small_root or 0)
    internal_manhattan_max = max(m_big_root or 0, m_small_root or 0)

    # Boundary input Manhattan proxy.
    boundary_manhattan_total = 0
    boundary_manhattan_missing = 0

    def add_boundary_cost(bidx, sink_site):
        nonlocal boundary_manhattan_total, boundary_manhattan_missing
        src_site = boundary_by_index[int(bidx)].get("driver_site", "")
        m = manhattan(src_site, sink_site)
        if m is None:
            boundary_manhattan_missing += 1
        else:
            boundary_manhattan_total += m

    for bidx in candidate["S1"]:
        add_boundary_cost(bidx, big_site)

    for bidx in candidate["S2"]:
        add_boundary_cost(bidx, small_site)

    for bidx in candidate["D"]:
        add_boundary_cost(bidx, root_site)

    # Penaliseer veel wijzigingen. Dit houdt ECO eenvoudiger.
    score = (
        internal_manhattan_max * 1000
        + internal_manhattan_total * 100
        + boundary_manhattan_total
        + len(changed_pins) * 250
        + boundary_manhattan_missing * 10000
    )

    return {
        "changed_pin_count": len(changed_pins),
        "changed_pins": changed_pins,
        "internal_manhattan_big_to_root": m_big_root,
        "internal_manhattan_small_to_root": m_small_root,
        "internal_manhattan_total": internal_manhattan_total,
        "internal_manhattan_max": internal_manhattan_max,
        "boundary_manhattan_total": boundary_manhattan_total,
        "boundary_manhattan_missing": boundary_manhattan_missing,
        "score": score,
    }


def infer_slots(phase3):
    """
    Infer:
      root = boundary output source cell
      big_helper = non-root LUT6
      small_helper = non-root LUT2
    """
    luts = phase3.get("luts", [])
    by_cell = {x["cell"]: x for x in luts}

    boundary_outputs = phase3.get("boundary_outputs", [])
    if len(boundary_outputs) != 1:
        fail(f"FASE 5A verwacht exact 1 boundary output, gevonden: {len(boundary_outputs)}")

    root_cell = boundary_outputs[0]["source_cell"]
    if root_cell not in by_cell:
        fail(f"Root cell {root_cell} niet gevonden in luts")

    root = by_cell[root_cell]

    helpers = [x for x in luts if x["cell"] != root_cell]

    big_candidates = [x for x in helpers if ref_capacity(x["ref"]) >= 6]
    small_candidates = [x for x in helpers if ref_capacity(x["ref"]) == 2]

    if len(big_candidates) != 1:
        fail(f"FASE 5A verwacht exact 1 niet-root LUT6 helper, gevonden: {len(big_candidates)}")

    if len(small_candidates) != 1:
        fail(f"FASE 5A verwacht exact 1 niet-root LUT2 helper, gevonden: {len(small_candidates)}")

    return {
        "root": root,
        "big_helper": big_candidates[0],
        "small_helper": small_candidates[0],
    }


def get_baseline_partition(phase3, slots):
    """
    Reconstrueer bestaande verdeling:
      S1 = boundary inputs op big helper
      S2 = boundary inputs op small helper
      D  = boundary inputs direct op root
    """
    net_to_bidx = {
        b["net"]: int(b["boundary_index"])
        for b in phase3.get("boundary_inputs", [])
    }

    out = {
        "S1": [],
        "S2": [],
        "D": [],
    }

    big_cell = slots["big_helper"]["cell"]
    small_cell = slots["small_helper"]["cell"]
    root_cell = slots["root"]["cell"]

    for pin in phase3.get("lut_input_pins", []):
        if pin.get("classification") != "boundary_input":
            continue

        net = pin.get("net", "")
        if net not in net_to_bidx:
            continue

        bidx = net_to_bidx[net]
        sink = pin["sink_cell"]

        if sink == big_cell:
            out["S1"].append(bidx)
        elif sink == small_cell:
            out["S2"].append(bidx)
        elif sink == root_cell:
            out["D"].append(bidx)

    out["S1"] = tuple(sorted(out["S1"]))
    out["S2"] = tuple(sorted(out["S2"]))
    out["D"] = tuple(sorted(out["D"]))

    return out


def main():
    if len(sys.argv) < 4:
        fail(
            "usage: python3 phase5a_decompose_fixed_window.py "
            "<phase3_window_info.json> <truth_table_compact.json> <out_dir> "
            "[max_exact_candidates_to_keep]"
        )

    phase3_path = os.path.abspath(sys.argv[1])
    phase4_path = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])

    if len(sys.argv) >= 5:
        max_keep = int(sys.argv[4])
    else:
        max_keep = 200

    ensure_dir(out_dir)

    if not os.path.exists(phase3_path):
        fail(f"phase3 JSON bestaat niet: {phase3_path}")

    if not os.path.exists(phase4_path):
        fail(f"truth_table_compact JSON bestaat niet: {phase4_path}")

    with open(phase3_path, "r") as f:
        phase3 = json.load(f)

    with open(phase4_path, "r") as f:
        phase4 = json.load(f)

    checks = []

    add_check(
        checks,
        "phase3_status",
        "PASS" if phase3.get("phase3_status") == "PASS" else "FAIL",
        f"phase3_status={phase3.get('phase3_status')}",
    )

    add_check(
        checks,
        "phase4_status",
        "PASS" if phase4.get("phase4_status") == "PASS" else "FAIL",
        f"phase4_status={phase4.get('phase4_status')}",
    )

    boundary_count = int(phase4["num_boundary_inputs"])
    output_count = int(phase4["num_boundary_outputs"])
    output_sequence = phase4["output_sequence"]

    if boundary_count != 12:
        add_check(checks, "boundary_count_is_12", "FAIL", f"boundary_count={boundary_count}")
    else:
        add_check(checks, "boundary_count_is_12", "PASS", "12 boundary inputs")

    if output_count != 1:
        add_check(checks, "single_output", "FAIL", f"num_boundary_outputs={output_count}")
    else:
        add_check(checks, "single_output", "PASS", "1 output")

    if len(output_sequence) != (1 << boundary_count):
        add_check(
            checks,
            "output_sequence_length",
            "FAIL",
            f"len={len(output_sequence)}, expected={1 << boundary_count}",
        )
    else:
        add_check(checks, "output_sequence_length", "PASS", f"len={len(output_sequence)}")

    slots = infer_slots(phase3)

    add_check(
        checks,
        "slot_inference",
        "PASS",
        f"root={slots['root']['cell']}, big={slots['big_helper']['cell']}, small={slots['small_helper']['cell']}",
    )

    if any(c["status"] == "FAIL" for c in checks):
        write_csv(
            os.path.join(out_dir, "phase5a_validation_checks.csv"),
            ["check", "status", "detail"],
            checks,
        )
        fail("pre-checks failed")

    baseline_partition = get_baseline_partition(phase3, slots)

    all_inputs = tuple(range(1, boundary_count + 1))

    # Baseline sanity.
    baseline_ok = False
    baseline_best = None

    for g2_mask in range(16):
        dec = check_decomposition_for_partition(
            output_sequence,
            boundary_count,
            baseline_partition["S1"],
            baseline_partition["S2"],
            baseline_partition["D"],
            g2_mask,
        )

        if dec is None:
            continue

        mismatches = simulate_candidate(
            output_sequence,
            boundary_count,
            baseline_partition["S1"],
            baseline_partition["S2"],
            baseline_partition["D"],
            dec["g1_init_int"],
            dec["g2_init_int"],
            dec["root_init_int"],
        )

        if not mismatches:
            baseline_ok = True
            baseline_best = dec
            break

    if baseline_ok:
        add_check(
            checks,
            "baseline_decomposition_reconstructed",
            "PASS",
            f"S1={baseline_partition['S1']} S2={baseline_partition['S2']} D={baseline_partition['D']}",
        )
    else:
        add_check(
            checks,
            "baseline_decomposition_reconstructed",
            "FAIL",
            f"Could not reconstruct baseline partition: {baseline_partition}",
        )

    # Search all partitions.
    exact_candidates = []
    rejected_rows = []

    template_count = 0
    sat_template_count = 0
    exact_candidate_id = 0

    for s1 in itertools.combinations(all_inputs, 6):
        remaining_after_s1 = tuple(x for x in all_inputs if x not in s1)

        for s2 in itertools.combinations(remaining_after_s1, 2):
            d = tuple(x for x in remaining_after_s1 if x not in s2)

            template_count += 1

            found_for_template = False

            for g2_mask in range(16):
                dec = check_decomposition_for_partition(
                    output_sequence,
                    boundary_count,
                    s1,
                    s2,
                    d,
                    g2_mask,
                )

                if dec is None:
                    continue

                mismatches = simulate_candidate(
                    output_sequence,
                    boundary_count,
                    s1,
                    s2,
                    d,
                    dec["g1_init_int"],
                    dec["g2_init_int"],
                    dec["root_init_int"],
                )

                if mismatches:
                    rejected_rows.append({
                        "template_id": template_count,
                        "S1": "|".join(map(str, s1)),
                        "S2": "|".join(map(str, s2)),
                        "D": "|".join(map(str, d)),
                        "g2_mask": g2_mask,
                        "reason": "post_simulation_mismatch",
                        "mismatch_count_sampled": len(mismatches),
                    })
                    continue

                found_for_template = True
                sat_template_count += 1

                candidate = {
                    "candidate_id": f"phase5a_exact_{exact_candidate_id:05d}",
                    "family": "exact_decomposition_6_2_4",
                    "S1": tuple(s1),
                    "S2": tuple(s2),
                    "D": tuple(d),
                    "g2_mask": g2_mask,
                    "num_signatures": dec["num_signatures"],
                    "g1_init_int": dec["g1_init_int"],
                    "g2_init_int": dec["g2_init_int"],
                    "root_init_int": dec["root_init_int"],
                    "g1_init": format_init(dec["g1_init_int"], 64),
                    "g2_init": format_init(dec["g2_init_int"], 4),
                    "root_init": format_init(dec["root_init_int"], 64),
                    "truth_table_equivalence": True,
                    "num_checked_vectors": 1 << boundary_count,
                    "window_depth": 2,
                }

                cost = compute_candidate_cost(candidate, phase3, slots)
                candidate.update(cost)

                # Detect baseline-equivalent partition.
                candidate["is_baseline_partition"] = (
                    tuple(s1) == baseline_partition["S1"]
                    and tuple(s2) == baseline_partition["S2"]
                    and tuple(d) == baseline_partition["D"]
                )

                exact_candidates.append(candidate)
                exact_candidate_id += 1

                # Voor deze template is één G2-oplossing genoeg.
                break

            if not found_for_template:
                rejected_rows.append({
                    "template_id": template_count,
                    "S1": "|".join(map(str, s1)),
                    "S2": "|".join(map(str, s2)),
                    "D": "|".join(map(str, d)),
                    "g2_mask": "",
                    "reason": "no_exact_decomposition",
                    "mismatch_count_sampled": "",
                })

    if exact_candidates:
        add_check(checks, "exact_candidates_found", "PASS", f"{len(exact_candidates)} exact candidates")
    else:
        add_check(checks, "exact_candidates_found", "FAIL", "0 exact candidates")

    # Sort candidates:
    #   1. non-baseline first if possible
    #   2. lower score
    #   3. fewer changed pins
    exact_candidates.sort(
        key=lambda c: (
            1 if c["is_baseline_partition"] else 0,
            c["score"],
            c["changed_pin_count"],
            c["candidate_id"],
        )
    )

    kept_candidates = exact_candidates[:max_keep]

    # Baseline candidate cost.
    baseline_candidates = [c for c in exact_candidates if c["is_baseline_partition"]]
    baseline_score = baseline_candidates[0]["score"] if baseline_candidates else None

    best_candidate = kept_candidates[0] if kept_candidates else None

    estimated_improvement = False
    if best_candidate is not None and baseline_score is not None:
        estimated_improvement = best_candidate["score"] < baseline_score

    if best_candidate is not None:
        add_check(
            checks,
            "best_candidate_selected",
            "PASS",
            f"{best_candidate['candidate_id']} score={best_candidate['score']} baseline_score={baseline_score}",
        )
    else:
        add_check(checks, "best_candidate_selected", "FAIL", "no candidate selected")

    if estimated_improvement:
        phase5a_status = "PASS_IMPROVED"
    elif exact_candidates:
        phase5a_status = "PASS_NO_ESTIMATED_IMPROVEMENT"
    else:
        phase5a_status = "FAIL"

    # CSV output.
    cand_rows = []
    for c in kept_candidates:
        cand_rows.append({
            "candidate_id": c["candidate_id"],
            "family": c["family"],
            "is_baseline_partition": int(c["is_baseline_partition"]),
            "S1": "|".join(map(str, c["S1"])),
            "S2": "|".join(map(str, c["S2"])),
            "D": "|".join(map(str, c["D"])),
            "g2_mask": c["g2_mask"],
            "num_signatures": c["num_signatures"],
            "g1_init": c["g1_init"],
            "g2_init": c["g2_init"],
            "root_init": c["root_init"],
            "truth_table_equivalence": int(c["truth_table_equivalence"]),
            "num_checked_vectors": c["num_checked_vectors"],
            "window_depth": c["window_depth"],
            "changed_pin_count": c["changed_pin_count"],
            "internal_manhattan_big_to_root": c["internal_manhattan_big_to_root"],
            "internal_manhattan_small_to_root": c["internal_manhattan_small_to_root"],
            "internal_manhattan_total": c["internal_manhattan_total"],
            "internal_manhattan_max": c["internal_manhattan_max"],
            "boundary_manhattan_total": c["boundary_manhattan_total"],
            "boundary_manhattan_missing": c["boundary_manhattan_missing"],
            "score": c["score"],
        })

    write_csv(
        os.path.join(out_dir, "phase5a_candidates.csv"),
        [
            "candidate_id",
            "family",
            "is_baseline_partition",
            "S1",
            "S2",
            "D",
            "g2_mask",
            "num_signatures",
            "g1_init",
            "g2_init",
            "root_init",
            "truth_table_equivalence",
            "num_checked_vectors",
            "window_depth",
            "changed_pin_count",
            "internal_manhattan_big_to_root",
            "internal_manhattan_small_to_root",
            "internal_manhattan_total",
            "internal_manhattan_max",
            "boundary_manhattan_total",
            "boundary_manhattan_missing",
            "score",
        ],
        cand_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5a_rejected_templates.csv"),
        ["template_id", "S1", "S2", "D", "g2_mask", "reason", "mismatch_count_sampled"],
        rejected_rows[:5000],
    )

    write_csv(
        os.path.join(out_dir, "phase5a_validation_checks.csv"),
        ["check", "status", "detail"],
        checks,
    )

    # Candidate JSON for phase 6.
    selected_json_path = os.path.join(out_dir, "phase5a_selected_candidate.json")

    selected_payload = None

    if best_candidate is not None:
        selected_payload = {
            "phase": "FASE 5A",
            "phase5a_status": phase5a_status,
            "candidate_id": best_candidate["candidate_id"],
            "family": best_candidate["family"],
            "same_lut_positions": True,
            "same_window_boundary": True,
            "new_topology_acyclic": True,
            "window_depth": best_candidate["window_depth"],
            "truth_table_equivalence": True,
            "num_checked_vectors": best_candidate["num_checked_vectors"],
            "estimated_improvement": estimated_improvement,
            "score": best_candidate["score"],
            "baseline_score": baseline_score,
            "slots": {
                "big_helper": {
                    "role": "G1",
                    "cell": slots["big_helper"]["cell"],
                    "ref": slots["big_helper"]["ref"],
                    "site": slots["big_helper"]["site"],
                    "bel": slots["big_helper"]["bel"],
                    "new_INIT": best_candidate["g1_init"],
                    "inputs": [
                        {
                            "sink_pin": f"I{i}",
                            "boundary_index": int(bidx),
                        }
                        for i, bidx in enumerate(best_candidate["S1"])
                    ],
                },
                "small_helper": {
                    "role": "G2",
                    "cell": slots["small_helper"]["cell"],
                    "ref": slots["small_helper"]["ref"],
                    "site": slots["small_helper"]["site"],
                    "bel": slots["small_helper"]["bel"],
                    "new_INIT": best_candidate["g2_init"],
                    "inputs": [
                        {
                            "sink_pin": f"I{i}",
                            "boundary_index": int(bidx),
                        }
                        for i, bidx in enumerate(best_candidate["S2"])
                    ],
                },
                "root": {
                    "role": "R",
                    "cell": slots["root"]["cell"],
                    "ref": slots["root"]["ref"],
                    "site": slots["root"]["site"],
                    "bel": slots["root"]["bel"],
                    "new_INIT": best_candidate["root_init"],
                    "inputs": (
                        [
                            {
                                "sink_pin": "I0",
                                "source": "big_helper/O",
                                "source_cell": slots["big_helper"]["cell"],
                            },
                            {
                                "sink_pin": "I1",
                                "source": "small_helper/O",
                                "source_cell": slots["small_helper"]["cell"],
                            },
                        ]
                        + [
                            {
                                "sink_pin": f"I{i + 2}",
                                "boundary_index": int(bidx),
                            }
                            for i, bidx in enumerate(best_candidate["D"])
                        ]
                    ),
                },
            },
            "changed_pins": best_candidate["changed_pins"],
            "cost": {
                "changed_pin_count": best_candidate["changed_pin_count"],
                "internal_manhattan_big_to_root": best_candidate["internal_manhattan_big_to_root"],
                "internal_manhattan_small_to_root": best_candidate["internal_manhattan_small_to_root"],
                "internal_manhattan_total": best_candidate["internal_manhattan_total"],
                "internal_manhattan_max": best_candidate["internal_manhattan_max"],
                "boundary_manhattan_total": best_candidate["boundary_manhattan_total"],
                "boundary_manhattan_missing": best_candidate["boundary_manhattan_missing"],
            },
        }

    with open(selected_json_path, "w") as f:
        json.dump(selected_payload, f, indent=2)

    # Full summary JSON.
    summary_json = {
        "phase": "FASE 5A",
        "phase5a_status": phase5a_status,
        "phase3_json": phase3_path,
        "truth_table_compact_json": phase4_path,
        "template_count": template_count,
        "sat_template_count": sat_template_count,
        "exact_candidate_count": len(exact_candidates),
        "kept_candidate_count": len(kept_candidates),
        "baseline_partition": {
            "S1": list(baseline_partition["S1"]),
            "S2": list(baseline_partition["S2"]),
            "D": list(baseline_partition["D"]),
            "reconstructed": baseline_ok,
        },
        "slots": {
            "root": slots["root"],
            "big_helper": slots["big_helper"],
            "small_helper": slots["small_helper"],
        },
        "baseline_score": baseline_score,
        "best_candidate_id": best_candidate["candidate_id"] if best_candidate else None,
        "best_score": best_candidate["score"] if best_candidate else None,
        "estimated_improvement": estimated_improvement,
        "validation_checks": checks,
    }

    with open(os.path.join(out_dir, "phase5a_summary.json"), "w") as f:
        json.dump(summary_json, f, indent=2)

    with open(os.path.join(out_dir, "phase5a_summary.txt"), "w") as f:
        f.write(f"phase5a_status={phase5a_status}\n")
        f.write(f"template_count={template_count}\n")
        f.write(f"sat_template_count={sat_template_count}\n")
        f.write(f"exact_candidate_count={len(exact_candidates)}\n")
        f.write(f"kept_candidate_count={len(kept_candidates)}\n")
        f.write(f"baseline_reconstructed={int(baseline_ok)}\n")
        f.write(f"baseline_partition_S1={'|'.join(map(str, baseline_partition['S1']))}\n")
        f.write(f"baseline_partition_S2={'|'.join(map(str, baseline_partition['S2']))}\n")
        f.write(f"baseline_partition_D={'|'.join(map(str, baseline_partition['D']))}\n")
        f.write(f"baseline_score={baseline_score}\n")
        f.write(f"best_candidate_id={best_candidate['candidate_id'] if best_candidate else ''}\n")
        f.write(f"best_score={best_candidate['score'] if best_candidate else ''}\n")
        f.write(f"estimated_improvement={int(estimated_improvement)}\n")
        f.write(f"selected_candidate_json={selected_json_path}\n")

    print(f"PHASE5A_{phase5a_status}")
    print(f"Templates checked: {template_count}")
    print(f"Exact candidates : {len(exact_candidates)}")
    print(f"Selected JSON    : {selected_json_path}")


if __name__ == "__main__":
    main()
