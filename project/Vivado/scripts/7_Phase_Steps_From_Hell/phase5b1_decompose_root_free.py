#!/usr/bin/env python3
"""
FASE 5B.1 — Exacte fixed-placement decompositie met vrije output-root.

Verschil met FASE 5A:
  - De root/output-LUT mag wisselen.
  - LUT-capaciteiten blijven vast zoals ze nu zijn.
  - Geen LUT2 -> LUT6 upgrade.
  - Geen approximation.

Voor dit window betekent dat:
  - Twee LUT6-slots
  - Eén LUT2-slot
  - Eén van de drie mag root worden
  - Boundary output wordt conceptueel door die root aangedreven

Geteste vormen:

1) Root = LUT6:
      F = R(H1(S1), H2(S2), D)
   met:
      |S1| = capaciteit helper 1
      |S2| = capaciteit helper 2
      |D|  = root_capacity - 2 = 4
   Voor dit window is dat typisch 6 + 2 + 4 = 12.

2) Root = LUT2:
      F = R(H1(S1), H2(S2))
   met:
      |S1| = 6
      |S2| = 6
      |D|  = 0

Gebruik:
  python3 phase5b1_decompose_root_free.py \
      <phase3_window_info.json> \
      <truth_table_compact.json> \
      <out_dir> \
      [max_exact_candidates_to_keep]

Voorbeeld:
  python3 ~/Masterproef/project/Vivado/scripts/phase5b1_decompose_root_free.py \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase3_window_info/phase3_window_info.json \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase4_truth_table/truth_table_compact.json \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase5b1_root_free \
      500
"""

import csv
import itertools
import json
import os
import re
import sys


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


def format_init(value: int, width: int) -> str:
    hex_digits = max(1, width // 4)
    return f"{width}'h{value:0{hex_digits}X}"


def project_assignment(row_index: int, boundary_indices):
    """
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


def root_index(h1_out, h2_out, d_assignment, d_size):
    """
    Root pin order:
      I0 = H1 output
      I1 = H2 output
      I2.. = D bits
    """
    idx = (h1_out << 0) | (h2_out << 1)

    for i in range(d_size):
        bit = (d_assignment >> i) & 1
        idx |= bit << (i + 2)

    return idx


def check_decomposition_enum_small_helper(output_sequence, boundary_count, s1, s2, d):
    """
    Exacte check voor:
        F = R(H1(S1), H2(S2), D)

    Deze functie enumereert H2 volledig.
    Dit is bedoeld voor het geval |S2| klein is, zoals LUT2.

    Voor dit project:
        |S1| = 6
        |S2| = 2
        |D|  = 4
    """
    s1_size = len(s1)
    s2_size = len(s2)
    d_size = len(d)

    if s2_size > 4:
        raise ValueError("enum_small_helper is alleen bedoeld voor kleine H2-support")

    h2_func_count = 1 << (1 << s2_size)

    for h2_init in range(h2_func_count):
        h2_values = {
            s2_assignment: (h2_init >> s2_assignment) & 1
            for s2_assignment in range(1 << s2_size)
        }

        signatures = []
        sig_for_s1 = {}

        possible = True

        for s1_assignment in range(1 << s1_size):
            signature = []

            for d_assignment in range(1 << d_size):
                for h2_out in (0, 1):
                    vals = set()

                    for s2_assignment in range(1 << s2_size):
                        if h2_values[s2_assignment] != h2_out:
                            continue

                        row = build_row_index_from_parts(
                            s1_assignment,
                            s1,
                            s2_assignment,
                            s2,
                            d_assignment,
                            d,
                        )

                        vals.add(int(output_sequence[row]))

                    if len(vals) == 0:
                        signature.append(None)
                    elif len(vals) == 1:
                        signature.append(next(iter(vals)))
                    else:
                        possible = False
                        break

                if not possible:
                    break

            if not possible:
                break

            sig = tuple(signature)
            sig_for_s1[s1_assignment] = sig

            if sig not in signatures:
                signatures.append(sig)

                if len(signatures) > 2:
                    possible = False
                    break

        if not possible:
            continue

        sig_to_h1 = {sig: idx for idx, sig in enumerate(signatures)}

        h1_init = 0
        for s1_assignment in range(1 << s1_size):
            h1_out = sig_to_h1[sig_for_s1[s1_assignment]]
            h1_init |= h1_out << s1_assignment

        root_init = 0
        for d_assignment in range(1 << d_size):
            for h2_out in (0, 1):
                for h1_out in (0, 1):
                    ridx = root_index(h1_out, h2_out, d_assignment, d_size)

                    if h1_out >= len(signatures):
                        val = 0
                    else:
                        sig = signatures[h1_out]
                        sig_pos = d_assignment * 2 + h2_out
                        sig_val = sig[sig_pos]
                        val = 0 if sig_val is None else sig_val

                    root_init |= int(val) << ridx

        return {
            "h1_init_int": h1_init,
            "h2_init_int": h2_init,
            "root_init_int": root_init,
            "num_signatures": len(signatures),
            "method": "enum_small_helper",
        }

    return None


def check_decomposition_root2_two_helpers(output_sequence, boundary_count, s1, s2):
    """
    Exacte check voor:
        F = R(H1(S1), H2(S2))

    Dit is speciaal voor root = LUT2, dus geen directe D-inputs.

    Eigenschap:
      Matrix F[S1_assignment][S2_assignment] moet kunnen worden
      gegroepeerd in maximaal 2 row classes en maximaal 2 column classes.
    """
    s1_size = len(s1)
    s2_size = len(s2)

    rows = []
    for s1_assignment in range(1 << s1_size):
        row_bits = []

        for s2_assignment in range(1 << s2_size):
            row = build_row_index_from_parts(
                s1_assignment,
                s1,
                s2_assignment,
                s2,
                0,
                (),
            )
            row_bits.append(int(output_sequence[row]))

        rows.append(tuple(row_bits))

    unique_row_patterns = []
    row_pattern_to_h1 = {}

    for pat in rows:
        if pat not in unique_row_patterns:
            unique_row_patterns.append(pat)

            if len(unique_row_patterns) > 2:
                return None

        row_pattern_to_h1[pat] = unique_row_patterns.index(pat)

    # H1 INIT.
    h1_init = 0
    for s1_assignment, pat in enumerate(rows):
        h1_out = row_pattern_to_h1[pat]
        h1_init |= h1_out << s1_assignment

    # Column signatures over row-pattern classes.
    column_signatures = []

    for s2_assignment in range(1 << s2_size):
        sig = tuple(pat[s2_assignment] for pat in unique_row_patterns)

        if sig not in column_signatures:
            column_signatures.append(sig)

            if len(column_signatures) > 2:
                return None

    sig_to_h2 = {sig: idx for idx, sig in enumerate(column_signatures)}

    # H2 INIT.
    h2_init = 0
    for s2_assignment in range(1 << s2_size):
        sig = tuple(pat[s2_assignment] for pat in unique_row_patterns)
        h2_out = sig_to_h2[sig]
        h2_init |= h2_out << s2_assignment

    # Root LUT2 INIT.
    # I0 = H1, I1 = H2.
    root_init = 0

    for h1_out in (0, 1):
        for h2_out in (0, 1):
            ridx = (h1_out << 0) | (h2_out << 1)

            if h1_out >= len(unique_row_patterns):
                val = 0
            elif h2_out >= len(column_signatures):
                val = 0
            else:
                sig = column_signatures[h2_out]
                val = sig[h1_out] if h1_out < len(sig) else 0

            root_init |= int(val) << ridx

    return {
        "h1_init_int": h1_init,
        "h2_init_int": h2_init,
        "root_init_int": root_init,
        "num_signatures": len(unique_row_patterns),
        "method": "root2_matrix_factor",
    }


def simulate_candidate(output_sequence, boundary_count, s1, s2, d, h1_init, h2_init, root_init):
    mismatches = []

    for row in range(1 << boundary_count):
        h1_idx = project_assignment(row, s1)
        h2_idx = project_assignment(row, s2)
        d_idx = project_assignment(row, d)

        h1_out = (h1_init >> h1_idx) & 1
        h2_out = (h2_init >> h2_idx) & 1

        root_inputs = [h1_out, h2_out]
        for i in range(len(d)):
            root_inputs.append((d_idx >> i) & 1)

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


def boundary_by_index_map(phase3):
    return {
        int(b["boundary_index"]): b
        for b in phase3.get("boundary_inputs", [])
    }


def new_source_id_from_boundary(boundary_index, boundary_by_index):
    net = boundary_by_index[int(boundary_index)].get("net", "")
    return f"BI_NET:{net}"


def compute_candidate_cost(candidate, phase3):
    """
    Schatting, geen Vivado timing.

    De score is bedoeld om kandidaten te rangschikken, niet als bewijs.
    Finale timing blijft FASE 7 met Vivado.
    """
    boundary_by_index = boundary_by_index_map(phase3)
    old_pin_map = build_old_pin_map(phase3)

    h1 = candidate["helper1_slot"]
    h2 = candidate["helper2_slot"]
    root = candidate["root_slot"]

    h1_site = h1["site"]
    h2_site = h2["site"]
    root_site = root["site"]

    new_pin_map = {}

    for local_i, bidx in enumerate(candidate["S1"]):
        new_pin_map[(h1["cell"], f"I{local_i}")] = new_source_id_from_boundary(
            bidx,
            boundary_by_index,
        )

    for local_i, bidx in enumerate(candidate["S2"]):
        new_pin_map[(h2["cell"], f"I{local_i}")] = new_source_id_from_boundary(
            bidx,
            boundary_by_index,
        )

    new_pin_map[(root["cell"], "I0")] = f"INT:{h1['cell']}/O"
    new_pin_map[(root["cell"], "I1")] = f"INT:{h2['cell']}/O"

    for local_i, bidx in enumerate(candidate["D"]):
        new_pin_map[(root["cell"], f"I{local_i + 2}")] = new_source_id_from_boundary(
            bidx,
            boundary_by_index,
        )

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

    internal_m1 = manhattan(h1_site, root_site)
    internal_m2 = manhattan(h2_site, root_site)

    internal_manhattan_total = (internal_m1 or 0) + (internal_m2 or 0)
    internal_manhattan_max = max(internal_m1 or 0, internal_m2 or 0)

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
        add_boundary_cost(bidx, h1_site)

    for bidx in candidate["S2"]:
        add_boundary_cost(bidx, h2_site)

    for bidx in candidate["D"]:
        add_boundary_cost(bidx, root_site)

    old_root = phase3["boundary_outputs"][0]["source_cell"]
    output_driver_changed = root["cell"] != old_root

    # Twee scores:
    # - score_without_output_penalty: puur topologie/interconnect-proxy
    # - score_with_output_penalty: conservatiever omdat FASE 6 output-driver rewiring moeilijker is
    score_without_output_penalty = (
        internal_manhattan_max * 1000
        + internal_manhattan_total * 100
        + boundary_manhattan_total
        + len(changed_pins) * 250
        + boundary_manhattan_missing * 10000
    )

    output_driver_change_penalty = 5000 if output_driver_changed else 0

    score_with_output_penalty = score_without_output_penalty + output_driver_change_penalty

    return {
        "changed_pin_count": len(changed_pins),
        "changed_pins": changed_pins,
        "internal_manhattan_h1_to_root": internal_m1,
        "internal_manhattan_h2_to_root": internal_m2,
        "internal_manhattan_total": internal_manhattan_total,
        "internal_manhattan_max": internal_manhattan_max,
        "boundary_manhattan_total": boundary_manhattan_total,
        "boundary_manhattan_missing": boundary_manhattan_missing,
        "output_driver_changed": output_driver_changed,
        "output_driver_change_penalty": output_driver_change_penalty,
        "score_without_output_penalty": score_without_output_penalty,
        "score_with_output_penalty": score_with_output_penalty,
    }


def infer_current_baseline_partition(phase3, root_cell, helper1_cell, helper2_cell):
    """
    Probeert de bestaande verdeling te reconstrueren voor één roltoekenning.
    Dit is vooral nuttig om de baseline te herkennen.
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

    for pin in phase3.get("lut_input_pins", []):
        if pin.get("classification") != "boundary_input":
            continue

        net = pin.get("net", "")

        if net not in net_to_bidx:
            continue

        bidx = net_to_bidx[net]
        sink = pin["sink_cell"]

        if sink == helper1_cell:
            out["S1"].append(bidx)
        elif sink == helper2_cell:
            out["S2"].append(bidx)
        elif sink == root_cell:
            out["D"].append(bidx)

    out["S1"] = tuple(sorted(out["S1"]))
    out["S2"] = tuple(sorted(out["S2"]))
    out["D"] = tuple(sorted(out["D"]))

    return out


def generate_role_assignments(luts):
    """
    Genereert roltoekenningen:
      root, helper1, helper2

    Voor root LUT6:
      helper1 = grootste helper
      helper2 = kleinste helper
      zodat helper2 eventueel klein geënumeerd kan worden.

    Voor root LUT2:
      beide helpers zijn LUT6.
    """
    assignments = []

    for root in luts:
        helpers = [x for x in luts if x["cell"] != root["cell"]]

        root_cap = ref_capacity(root["ref"])

        if root_cap == 6:
            # Vereist één LUT6-helper en één LUT2-helper in dit window.
            sorted_helpers = sorted(
                helpers,
                key=lambda h: ref_capacity(h["ref"]),
                reverse=True,
            )

            h1 = sorted_helpers[0]
            h2 = sorted_helpers[1]

            if ref_capacity(h1["ref"]) + ref_capacity(h2["ref"]) + (root_cap - 2) != 12:
                continue

            # Voor root LUT6 willen we dat h2 klein is voor enumeratie.
            if ref_capacity(h2["ref"]) > 4:
                continue

            assignments.append({
                "root": root,
                "helper1": h1,
                "helper2": h2,
                "root_capacity": root_cap,
                "helper1_capacity": ref_capacity(h1["ref"]),
                "helper2_capacity": ref_capacity(h2["ref"]),
                "direct_capacity": root_cap - 2,
            })

        elif root_cap == 2:
            h1, h2 = helpers

            if ref_capacity(h1["ref"]) + ref_capacity(h2["ref"]) != 12:
                continue

            assignments.append({
                "root": root,
                "helper1": h1,
                "helper2": h2,
                "root_capacity": root_cap,
                "helper1_capacity": ref_capacity(h1["ref"]),
                "helper2_capacity": ref_capacity(h2["ref"]),
                "direct_capacity": 0,
            })

            # Omdat de twee LUT6 helpers fysiek verschillend zijn, test ook de omgekeerde rol.
            assignments.append({
                "root": root,
                "helper1": h2,
                "helper2": h1,
                "root_capacity": root_cap,
                "helper1_capacity": ref_capacity(h2["ref"]),
                "helper2_capacity": ref_capacity(h1["ref"]),
                "direct_capacity": 0,
            })

    return assignments


def main():
    if len(sys.argv) < 4:
        fail(
            "usage: python3 phase5b1_decompose_root_free.py "
            "<phase3_window_info.json> <truth_table_compact.json> <out_dir> "
            "[max_exact_candidates_to_keep]"
        )

    phase3_path = os.path.abspath(sys.argv[1])
    phase4_path = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])

    if len(sys.argv) >= 5:
        max_keep = int(sys.argv[4])
    else:
        max_keep = 500

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

    luts = phase3.get("luts", [])

    if len(luts) != 3:
        add_check(checks, "three_luts", "FAIL", f"num_luts={len(luts)}")
    else:
        add_check(checks, "three_luts", "PASS", "3 LUTs")

    if any(c["status"] == "FAIL" for c in checks):
        write_csv(
            os.path.join(out_dir, "phase5b1_validation_checks.csv"),
            ["check", "status", "detail"],
            checks,
        )
        fail("pre-checks failed")

    role_assignments = generate_role_assignments(luts)

    add_check(
        checks,
        "role_assignments_generated",
        "PASS" if role_assignments else "FAIL",
        f"count={len(role_assignments)}",
    )

    all_inputs = tuple(range(1, boundary_count + 1))

    current_root_cell = phase3["boundary_outputs"][0]["source_cell"]

    template_rows = []
    exact_candidates = []
    rejected_rows = []

    template_count = 0
    exact_candidate_id = 0

    for role_id, role in enumerate(role_assignments):
        root = role["root"]
        h1 = role["helper1"]
        h2 = role["helper2"]

        root_cap = role["root_capacity"]
        h1_cap = role["helper1_capacity"]
        h2_cap = role["helper2_capacity"]
        d_cap = role["direct_capacity"]

        role_name = (
            f"root={root['cell']}({root['ref']}),"
            f"h1={h1['cell']}({h1['ref']}),"
            f"h2={h2['cell']}({h2['ref']})"
        )

        baseline_partition_for_role = infer_current_baseline_partition(
            phase3,
            root["cell"],
            h1["cell"],
            h2["cell"],
        )

        for s1 in itertools.combinations(all_inputs, h1_cap):
            remaining_after_s1 = tuple(x for x in all_inputs if x not in s1)

            for s2 in itertools.combinations(remaining_after_s1, h2_cap):
                d = tuple(x for x in remaining_after_s1 if x not in s2)

                if len(d) != d_cap:
                    continue

                template_count += 1

                found = None

                if root_cap == 6:
                    # F = R(H1, H2, D), H2 is small.
                    found = check_decomposition_enum_small_helper(
                        output_sequence,
                        boundary_count,
                        s1,
                        s2,
                        d,
                    )
                elif root_cap == 2:
                    # F = R(H1, H2), no D.
                    found = check_decomposition_root2_two_helpers(
                        output_sequence,
                        boundary_count,
                        s1,
                        s2,
                    )
                else:
                    rejected_rows.append({
                        "template_id": template_count,
                        "role_id": role_id,
                        "role": role_name,
                        "S1": "|".join(map(str, s1)),
                        "S2": "|".join(map(str, s2)),
                        "D": "|".join(map(str, d)),
                        "reason": f"unsupported_root_capacity_{root_cap}",
                    })
                    continue

                if found is None:
                    rejected_rows.append({
                        "template_id": template_count,
                        "role_id": role_id,
                        "role": role_name,
                        "S1": "|".join(map(str, s1)),
                        "S2": "|".join(map(str, s2)),
                        "D": "|".join(map(str, d)),
                        "reason": "no_exact_decomposition",
                    })
                    continue

                mismatches = simulate_candidate(
                    output_sequence,
                    boundary_count,
                    s1,
                    s2,
                    d,
                    found["h1_init_int"],
                    found["h2_init_int"],
                    found["root_init_int"],
                )

                if mismatches:
                    rejected_rows.append({
                        "template_id": template_count,
                        "role_id": role_id,
                        "role": role_name,
                        "S1": "|".join(map(str, s1)),
                        "S2": "|".join(map(str, s2)),
                        "D": "|".join(map(str, d)),
                        "reason": "post_simulation_mismatch",
                    })
                    continue

                candidate = {
                    "candidate_id": f"phase5b1_exact_{exact_candidate_id:05d}",
                    "family": "root_free_exact_decomposition_fixed_capacities",
                    "role_id": role_id,
                    "root_slot": root,
                    "helper1_slot": h1,
                    "helper2_slot": h2,
                    "root_capacity": root_cap,
                    "helper1_capacity": h1_cap,
                    "helper2_capacity": h2_cap,
                    "direct_capacity": d_cap,
                    "S1": tuple(s1),
                    "S2": tuple(s2),
                    "D": tuple(d),
                    "method": found["method"],
                    "num_signatures": found["num_signatures"],
                    "h1_init_int": found["h1_init_int"],
                    "h2_init_int": found["h2_init_int"],
                    "root_init_int": found["root_init_int"],
                    "h1_init": format_init(found["h1_init_int"], 1 << h1_cap),
                    "h2_init": format_init(found["h2_init_int"], 1 << h2_cap),
                    "root_init": format_init(found["root_init_int"], 1 << root_cap),
                    "truth_table_equivalence": True,
                    "num_checked_vectors": 1 << boundary_count,
                    "window_depth": 2,
                    "root_changed": root["cell"] != current_root_cell,
                    "is_current_root": root["cell"] == current_root_cell,
                    "is_baseline_like_partition": (
                        tuple(s1) == baseline_partition_for_role["S1"]
                        and tuple(s2) == baseline_partition_for_role["S2"]
                        and tuple(d) == baseline_partition_for_role["D"]
                        and root["cell"] == current_root_cell
                    ),
                }

                candidate.update(compute_candidate_cost(candidate, phase3))

                exact_candidates.append(candidate)
                exact_candidate_id += 1

                template_rows.append({
                    "template_id": template_count,
                    "role_id": role_id,
                    "role": role_name,
                    "candidate_id": candidate["candidate_id"],
                    "root_cell": root["cell"],
                    "helper1_cell": h1["cell"],
                    "helper2_cell": h2["cell"],
                    "S1": "|".join(map(str, s1)),
                    "S2": "|".join(map(str, s2)),
                    "D": "|".join(map(str, d)),
                    "method": found["method"],
                    "score_without_output_penalty": candidate["score_without_output_penalty"],
                    "score_with_output_penalty": candidate["score_with_output_penalty"],
                    "root_changed": int(candidate["root_changed"]),
                    "changed_pin_count": candidate["changed_pin_count"],
                })

    if exact_candidates:
        add_check(
            checks,
            "exact_candidates_found",
            "PASS",
            f"{len(exact_candidates)} exact candidates",
        )
    else:
        add_check(
            checks,
            "exact_candidates_found",
            "FAIL",
            "0 exact candidates",
        )

    # Baseline candidate.
    baseline_candidates = [c for c in exact_candidates if c["is_baseline_like_partition"]]
    baseline_score_no_penalty = (
        baseline_candidates[0]["score_without_output_penalty"]
        if baseline_candidates
        else None
    )
    baseline_score_with_penalty = (
        baseline_candidates[0]["score_with_output_penalty"]
        if baseline_candidates
        else None
    )

    # Sort:
    #   1. avoid pure baseline
    #   2. prefer lower score without output penalty
    #   3. prefer lower score with output penalty
    #   4. fewer changed pins
    exact_candidates.sort(
        key=lambda c: (
            1 if c["is_baseline_like_partition"] else 0,
            c["score_without_output_penalty"],
            c["score_with_output_penalty"],
            c["changed_pin_count"],
            c["candidate_id"],
        )
    )

    kept_candidates = exact_candidates[:max_keep]
    best_candidate = kept_candidates[0] if kept_candidates else None

    estimated_improvement_no_penalty = False
    estimated_improvement_with_penalty = False

    if best_candidate and baseline_score_no_penalty is not None:
        estimated_improvement_no_penalty = (
            best_candidate["score_without_output_penalty"] < baseline_score_no_penalty
        )

    if best_candidate and baseline_score_with_penalty is not None:
        estimated_improvement_with_penalty = (
            best_candidate["score_with_output_penalty"] < baseline_score_with_penalty
        )

    if best_candidate:
        add_check(
            checks,
            "best_candidate_selected",
            "PASS",
            (
                f"{best_candidate['candidate_id']} "
                f"score_no_penalty={best_candidate['score_without_output_penalty']} "
                f"baseline_no_penalty={baseline_score_no_penalty}"
            ),
        )
    else:
        add_check(checks, "best_candidate_selected", "FAIL", "no candidate selected")

    if best_candidate and estimated_improvement_no_penalty:
        phase5b1_status = "PASS_IMPROVED_ESTIMATE"
    elif best_candidate:
        phase5b1_status = "PASS_NO_ESTIMATED_IMPROVEMENT"
    else:
        phase5b1_status = "FAIL"

    # Write candidate CSV.
    cand_rows = []
    for c in kept_candidates:
        cand_rows.append({
            "candidate_id": c["candidate_id"],
            "family": c["family"],
            "role_id": c["role_id"],
            "root_cell": c["root_slot"]["cell"],
            "root_ref": c["root_slot"]["ref"],
            "helper1_cell": c["helper1_slot"]["cell"],
            "helper1_ref": c["helper1_slot"]["ref"],
            "helper2_cell": c["helper2_slot"]["cell"],
            "helper2_ref": c["helper2_slot"]["ref"],
            "root_changed": int(c["root_changed"]),
            "is_baseline_like_partition": int(c["is_baseline_like_partition"]),
            "S1": "|".join(map(str, c["S1"])),
            "S2": "|".join(map(str, c["S2"])),
            "D": "|".join(map(str, c["D"])),
            "method": c["method"],
            "num_signatures": c["num_signatures"],
            "h1_init": c["h1_init"],
            "h2_init": c["h2_init"],
            "root_init": c["root_init"],
            "truth_table_equivalence": int(c["truth_table_equivalence"]),
            "num_checked_vectors": c["num_checked_vectors"],
            "window_depth": c["window_depth"],
            "changed_pin_count": c["changed_pin_count"],
            "output_driver_changed": int(c["output_driver_changed"]),
            "internal_manhattan_h1_to_root": c["internal_manhattan_h1_to_root"],
            "internal_manhattan_h2_to_root": c["internal_manhattan_h2_to_root"],
            "internal_manhattan_total": c["internal_manhattan_total"],
            "internal_manhattan_max": c["internal_manhattan_max"],
            "boundary_manhattan_total": c["boundary_manhattan_total"],
            "boundary_manhattan_missing": c["boundary_manhattan_missing"],
            "score_without_output_penalty": c["score_without_output_penalty"],
            "score_with_output_penalty": c["score_with_output_penalty"],
        })

    write_csv(
        os.path.join(out_dir, "phase5b1_candidates.csv"),
        [
            "candidate_id",
            "family",
            "role_id",
            "root_cell",
            "root_ref",
            "helper1_cell",
            "helper1_ref",
            "helper2_cell",
            "helper2_ref",
            "root_changed",
            "is_baseline_like_partition",
            "S1",
            "S2",
            "D",
            "method",
            "num_signatures",
            "h1_init",
            "h2_init",
            "root_init",
            "truth_table_equivalence",
            "num_checked_vectors",
            "window_depth",
            "changed_pin_count",
            "output_driver_changed",
            "internal_manhattan_h1_to_root",
            "internal_manhattan_h2_to_root",
            "internal_manhattan_total",
            "internal_manhattan_max",
            "boundary_manhattan_total",
            "boundary_manhattan_missing",
            "score_without_output_penalty",
            "score_with_output_penalty",
        ],
        cand_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5b1_exact_templates.csv"),
        [
            "template_id",
            "role_id",
            "role",
            "candidate_id",
            "root_cell",
            "helper1_cell",
            "helper2_cell",
            "S1",
            "S2",
            "D",
            "method",
            "score_without_output_penalty",
            "score_with_output_penalty",
            "root_changed",
            "changed_pin_count",
        ],
        template_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5b1_rejected_templates.csv"),
        ["template_id", "role_id", "role", "S1", "S2", "D", "reason"],
        rejected_rows[:10000],
    )

    write_csv(
        os.path.join(out_dir, "phase5b1_validation_checks.csv"),
        ["check", "status", "detail"],
        checks,
    )

    # Selected candidate JSON.
    selected_json_path = os.path.join(out_dir, "phase5b1_selected_candidate.json")

    selected_payload = None

    if best_candidate:
        selected_payload = {
            "phase": "FASE 5B.1",
            "phase5b1_status": phase5b1_status,
            "candidate_id": best_candidate["candidate_id"],
            "family": best_candidate["family"],
            "same_lut_positions": True,
            "same_window_boundary": True,
            "root_free": True,
            "root_changed": best_candidate["root_changed"],
            "output_driver_changed": best_candidate["output_driver_changed"],
            "fixed_capacities": True,
            "lut2_upgraded_to_lut6": False,
            "new_topology_acyclic": True,
            "window_depth": best_candidate["window_depth"],
            "truth_table_equivalence": True,
            "num_checked_vectors": best_candidate["num_checked_vectors"],
            "estimated_improvement_no_output_penalty": estimated_improvement_no_penalty,
            "estimated_improvement_with_output_penalty": estimated_improvement_with_penalty,
            "baseline_score_without_output_penalty": baseline_score_no_penalty,
            "baseline_score_with_output_penalty": baseline_score_with_penalty,
            "score_without_output_penalty": best_candidate["score_without_output_penalty"],
            "score_with_output_penalty": best_candidate["score_with_output_penalty"],
            "roles": {
                "root": {
                    "role": "R",
                    "cell": best_candidate["root_slot"]["cell"],
                    "ref": best_candidate["root_slot"]["ref"],
                    "site": best_candidate["root_slot"]["site"],
                    "bel": best_candidate["root_slot"]["bel"],
                    "new_INIT": best_candidate["root_init"],
                    "inputs": (
                        [
                            {
                                "sink_pin": "I0",
                                "source": "helper1/O",
                                "source_cell": best_candidate["helper1_slot"]["cell"],
                            },
                            {
                                "sink_pin": "I1",
                                "source": "helper2/O",
                                "source_cell": best_candidate["helper2_slot"]["cell"],
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
                "helper1": {
                    "role": "H1",
                    "cell": best_candidate["helper1_slot"]["cell"],
                    "ref": best_candidate["helper1_slot"]["ref"],
                    "site": best_candidate["helper1_slot"]["site"],
                    "bel": best_candidate["helper1_slot"]["bel"],
                    "new_INIT": best_candidate["h1_init"],
                    "inputs": [
                        {
                            "sink_pin": f"I{i}",
                            "boundary_index": int(bidx),
                        }
                        for i, bidx in enumerate(best_candidate["S1"])
                    ],
                },
                "helper2": {
                    "role": "H2",
                    "cell": best_candidate["helper2_slot"]["cell"],
                    "ref": best_candidate["helper2_slot"]["ref"],
                    "site": best_candidate["helper2_slot"]["site"],
                    "bel": best_candidate["helper2_slot"]["bel"],
                    "new_INIT": best_candidate["h2_init"],
                    "inputs": [
                        {
                            "sink_pin": f"I{i}",
                            "boundary_index": int(bidx),
                        }
                        for i, bidx in enumerate(best_candidate["S2"])
                    ],
                },
            },
            "changed_pins": best_candidate["changed_pins"],
            "cost": {
                "changed_pin_count": best_candidate["changed_pin_count"],
                "output_driver_changed": best_candidate["output_driver_changed"],
                "output_driver_change_penalty": best_candidate["output_driver_change_penalty"],
                "internal_manhattan_h1_to_root": best_candidate["internal_manhattan_h1_to_root"],
                "internal_manhattan_h2_to_root": best_candidate["internal_manhattan_h2_to_root"],
                "internal_manhattan_total": best_candidate["internal_manhattan_total"],
                "internal_manhattan_max": best_candidate["internal_manhattan_max"],
                "boundary_manhattan_total": best_candidate["boundary_manhattan_total"],
                "boundary_manhattan_missing": best_candidate["boundary_manhattan_missing"],
            },
        }

    with open(selected_json_path, "w") as f:
        json.dump(selected_payload, f, indent=2)

    summary_json = {
        "phase": "FASE 5B.1",
        "phase5b1_status": phase5b1_status,
        "phase3_json": phase3_path,
        "truth_table_compact_json": phase4_path,
        "template_count": template_count,
        "exact_candidate_count": len(exact_candidates),
        "kept_candidate_count": len(kept_candidates),
        "role_assignment_count": len(role_assignments),
        "baseline_score_without_output_penalty": baseline_score_no_penalty,
        "baseline_score_with_output_penalty": baseline_score_with_penalty,
        "best_candidate_id": best_candidate["candidate_id"] if best_candidate else None,
        "best_score_without_output_penalty": (
            best_candidate["score_without_output_penalty"] if best_candidate else None
        ),
        "best_score_with_output_penalty": (
            best_candidate["score_with_output_penalty"] if best_candidate else None
        ),
        "estimated_improvement_no_output_penalty": estimated_improvement_no_penalty,
        "estimated_improvement_with_output_penalty": estimated_improvement_with_penalty,
        "validation_checks": checks,
    }

    with open(os.path.join(out_dir, "phase5b1_summary.json"), "w") as f:
        json.dump(summary_json, f, indent=2)

    with open(os.path.join(out_dir, "phase5b1_summary.txt"), "w") as f:
        f.write(f"phase5b1_status={phase5b1_status}\n")
        f.write(f"template_count={template_count}\n")
        f.write(f"exact_candidate_count={len(exact_candidates)}\n")
        f.write(f"kept_candidate_count={len(kept_candidates)}\n")
        f.write(f"role_assignment_count={len(role_assignments)}\n")
        f.write(f"baseline_score_without_output_penalty={baseline_score_no_penalty}\n")
        f.write(f"baseline_score_with_output_penalty={baseline_score_with_penalty}\n")
        f.write(f"best_candidate_id={best_candidate['candidate_id'] if best_candidate else ''}\n")
        f.write(
            f"best_score_without_output_penalty="
            f"{best_candidate['score_without_output_penalty'] if best_candidate else ''}\n"
        )
        f.write(
            f"best_score_with_output_penalty="
            f"{best_candidate['score_with_output_penalty'] if best_candidate else ''}\n"
        )
        f.write(f"estimated_improvement_no_output_penalty={int(estimated_improvement_no_penalty)}\n")
        f.write(f"estimated_improvement_with_output_penalty={int(estimated_improvement_with_penalty)}\n")
        f.write(f"selected_candidate_json={selected_json_path}\n")

    print(f"PHASE5B1_{phase5b1_status}")
    print(f"Templates checked: {template_count}")
    print(f"Exact candidates : {len(exact_candidates)}")
    print(f"Selected JSON    : {selected_json_path}")


if __name__ == "__main__":
    main()
