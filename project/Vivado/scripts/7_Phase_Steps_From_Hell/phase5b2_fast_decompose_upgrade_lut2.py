#!/usr/bin/env python3
"""
FASE 5B.2 FAST — Exacte decompositie met LUT2 -> LUT6 upgrade toegestaan.

Doel:
  Zoek exact-equivalente decomposities van de 12-input / 1-output windowfunctie
  met drie bestaande fysieke LUT-sites, waarbij alle drie logisch als LUT6 mogen
  worden gebruikt.

Belangrijk:
  - Geen approximation.
  - Geen Z3 per template.
  - Exacte truth-table equivalentie over 4096 vectors.
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
    S1 en S2 partitioneren de overige 8 boundary inputs
    2 <= |S1| <= 6
    2 <= |S2| <= 6

Gebruik:
  python3 phase5b2_fast_decompose_upgrade_lut2.py \
      <phase3_window_info.json> \
      <truth_table_compact.json> \
      <out_dir> \
      [top_templates_to_check] \
      [max_candidates_to_keep] \
      [stop_on_first_improved]

Voorbeeld:
  python3 ~/Masterproef/project/Vivado/scripts/phase5b2_fast_decompose_upgrade_lut2.py \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase3_window_info/phase3_window_info.json \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase4_truth_table/truth_table_compact.json \
      ~/Masterproef/project/results/run_lut_insertion/TestDirectory/phase5b2_fast \
      20000 \
      200 \
      1
"""

import csv
import heapq
import itertools
import json
import os
import re
import sys
import time
from itertools import product


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
    checks.append({
        "check": check,
        "status": status,
        "detail": detail,
    })


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


def root_index(h1_out, h2_out, d_assignment, d_size=4):
    """
    Root pin order:
      I0 = H1 output
      I1 = H2 output
      I2 = D0
      I3 = D1
      I4 = D2
      I5 = D3
    """
    idx = (h1_out << 0) | (h2_out << 1)

    for i in range(d_size):
        bit = (d_assignment >> i) & 1
        idx |= bit << (i + 2)

    return idx


def expand_support_init_to_lut6(init_value: int, support_size: int) -> int:
    """
    Embed een k-input functie in een LUT6 INIT.
    De support gebruikt I0..I(k-1).
    I(k)..I5 zijn don't-cares en worden gerepliceerd.
    """
    if support_size > 6:
        raise ValueError("support_size > 6")

    expanded = 0
    mask = (1 << support_size) - 1

    for idx6 in range(64):
        small_idx = idx6 & mask
        bit = (init_value >> small_idx) & 1
        expanded |= bit << idx6

    return expanded


# -----------------------------
# Exact decomposition check
# -----------------------------

def compute_signature_matrix(output_sequence, s1, s2, d):
    """
    Bouw matrix M[a][b].

    Elke entry is een 16-bit signature:
      bit d_assignment = F(s1_assignment=a, s2_assignment=b, D=d_assignment)

    De decompositie bestaat alleen als deze matrix kan gefactoriseerd worden als:
      M[a][b] = T[H1(a)][H2(b)]
    met H1/H2 binair.
    """
    s1_size = len(s1)
    s2_size = len(s2)
    d_size = len(d)

    if d_size != 4:
        raise ValueError("FASE 5B.2-fast verwacht |D| = 4")

    matrix = []
    unique = set()

    for a in range(1 << s1_size):
        row = []

        for b in range(1 << s2_size):
            sig = 0

            for dd in range(1 << d_size):
                row_index = build_row_index_from_parts(a, s1, b, s2, dd, d)
                if output_sequence[row_index] == "1":
                    sig |= 1 << dd

            row.append(sig)
            unique.add(sig)

            # Nodige voorwaarde: root heeft maar 4 combinaties van H1/H2.
            if len(unique) > 4:
                return None, unique

        matrix.append(row)

    return matrix, unique


def allowed_pair_mask(t00, t01, t10, t11, val):
    """
    Pair bit order:
      bit 0 = r0 c0
      bit 1 = r0 c1
      bit 2 = r1 c0
      bit 3 = r1 c1
    """
    mask = 0
    if t00 == val:
        mask |= 1 << 0
    if t01 == val:
        mask |= 1 << 1
    if t10 == val:
        mask |= 1 << 2
    if t11 == val:
        mask |= 1 << 3
    return mask


def values_from_domain(mask):
    vals = []
    if mask & 1:
        vals.append(0)
    if mask & 2:
        vals.append(1)
    return vals


def pair_allowed(mask, r, c):
    bit = r * 2 + c
    return (mask & (1 << bit)) != 0


def propagate_domains(row_domains, col_domains, constraint_masks):
    """
    Arc consistency propagation voor binary row/column labels.
    """
    n_rows = len(row_domains)
    n_cols = len(col_domains)

    changed = True

    while changed:
        changed = False

        for i in range(n_rows):
            for j in range(n_cols):
                mask = constraint_masks[i][j]

                old_r = row_domains[i]
                old_c = col_domains[j]

                new_r = 0
                for r in values_from_domain(old_r):
                    ok = False
                    for c in values_from_domain(old_c):
                        if pair_allowed(mask, r, c):
                            ok = True
                            break
                    if ok:
                        new_r |= 1 << r

                new_c = 0
                for c in values_from_domain(old_c):
                    ok = False
                    for r in values_from_domain(new_r):
                        if pair_allowed(mask, r, c):
                            ok = True
                            break
                    if ok:
                        new_c |= 1 << c

                if new_r == 0 or new_c == 0:
                    return None, None, False

                if new_r != old_r:
                    row_domains[i] = new_r
                    changed = True

                if new_c != old_c:
                    col_domains[j] = new_c
                    changed = True

    return row_domains, col_domains, True


def solve_label_csp_for_T(matrix, T, node_limit=10000):
    """
    Zoek row labels H1(a) en column labels H2(b) voor vaste T.
    """
    n_rows = len(matrix)
    n_cols = len(matrix[0])

    t00, t01, t10, t11 = T

    constraint_masks = []
    for i in range(n_rows):
        row_masks = []
        for j in range(n_cols):
            val = matrix[i][j]
            mask = allowed_pair_mask(t00, t01, t10, t11, val)
            if mask == 0:
                return None, None, False
            row_masks.append(mask)
        constraint_masks.append(row_masks)

    # Domain mask:
    #   1 = only 0
    #   2 = only 1
    #   3 = {0,1}
    row_domains = [3] * n_rows
    col_domains = [3] * n_cols

    # Symmetry breaking: first row label = 0.
    row_domains[0] = 1

    nodes = 0

    def dfs(rdom, cdom):
        nonlocal nodes
        nodes += 1

        if nodes > node_limit:
            return None

        rdom = list(rdom)
        cdom = list(cdom)

        rdom, cdom, ok = propagate_domains(rdom, cdom, constraint_masks)
        if not ok:
            return None

        # Done?
        all_singleton = all(x in (1, 2) for x in rdom) and all(x in (1, 2) for x in cdom)
        if all_singleton:
            rlabels = [0 if x == 1 else 1 for x in rdom]
            clabels = [0 if x == 1 else 1 for x in cdom]
            return rlabels, clabels

        # Branch op eerste niet-singleton domein.
        for idx, dom in enumerate(rdom):
            if dom == 3:
                for val in (0, 1):
                    nr = list(rdom)
                    nr[idx] = 1 << val
                    res = dfs(nr, cdom)
                    if res is not None:
                        return res
                return None

        for idx, dom in enumerate(cdom):
            if dom == 3:
                for val in (0, 1):
                    nc = list(cdom)
                    nc[idx] = 1 << val
                    res = dfs(rdom, nc)
                    if res is not None:
                        return res
                return None

        return None

    res = dfs(row_domains, col_domains)

    if res is None:
        return None, None, False

    rlabels, clabels = res
    return rlabels, clabels, True


def factor_signature_matrix(matrix, unique_values):
    """
    Exacte factorisatie:
      M[a][b] = T[H1(a)][H2(b)]

    Return:
      h1 labels, h2 labels, root table T
    """
    unique_values = sorted(unique_values)

    # T heeft 4 entries. Entries mogen herhaald worden.
    # Maar alle waarden die in de matrix voorkomen moeten in T aanwezig zijn.
    for T in product(unique_values, repeat=4):
        if not set(unique_values).issubset(set(T)):
            continue

        rlabels, clabels, ok = solve_label_csp_for_T(matrix, T)
        if ok:
            return rlabels, clabels, T

    return None


def solve_template_fast(output_sequence, s1, s2, d):
    """
    Constructieve exacte decompositiecheck.
    """
    matrix, unique_values = compute_signature_matrix(output_sequence, s1, s2, d)

    if matrix is None:
        return None, "too_many_signatures"

    result = factor_signature_matrix(matrix, unique_values)

    if result is None:
        return None, "not_factorable"

    h1_labels, h2_labels, T = result

    # H1 INIT small.
    h1_init_small = 0
    for assignment, label in enumerate(h1_labels):
        h1_init_small |= int(label) << assignment

    # H2 INIT small.
    h2_init_small = 0
    for assignment, label in enumerate(h2_labels):
        h2_init_small |= int(label) << assignment

    # Root INIT.
    # T order:
    #   T[0] = R(0,0) signature over D
    #   T[1] = R(0,1)
    #   T[2] = R(1,0)
    #   T[3] = R(1,1)
    root_init = 0

    for h1 in (0, 1):
        for h2 in (0, 1):
            sig = T[h1 * 2 + h2]

            for d_assignment in range(16):
                bit = (sig >> d_assignment) & 1
                ridx = root_index(h1, h2, d_assignment)
                root_init |= bit << ridx

    return {
        "h1_init_small": h1_init_small,
        "h2_init_small": h2_init_small,
        "h1_init_64": expand_support_init_to_lut6(h1_init_small, len(s1)),
        "h2_init_64": expand_support_init_to_lut6(h2_init_small, len(s2)),
        "root_init_64": root_init,
        "unique_signature_count": len(unique_values),
        "T": T,
    }, "sat"


def simulate_candidate(output_sequence, s1, s2, d, h1_init_64, h2_init_64, root_init_64):
    """
    Simuleer kandidaat over alle rijen van de truth table.

    Nieuwe versie:
    - niet meer hardcoded 4096;
    - werkt voor boundary_count <= 12;
    - len(output_sequence) bepaalt het aantal testvectors.
    """
    mismatches = []

    num_rows = len(output_sequence)

    for row in range(num_rows):
        h1_idx = project_assignment(row, s1)
        h2_idx = project_assignment(row, s2)
        d_idx = project_assignment(row, d)

        h1_out = (h1_init_64 >> h1_idx) & 1
        h2_out = (h2_init_64 >> h2_idx) & 1

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
            mismatches.append({
                "row": row,
                "expected": expected,
                "actual": y,
            })
            if len(mismatches) >= 20:
                break

    return mismatches

# -----------------------------
# Cost / template generation
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


def template_cost(template, phase3):
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

    def add_boundary_cost(bidx, sink_site):
        nonlocal boundary_total, boundary_missing

        src_site = boundary_by_index[int(bidx)].get("driver_site", "")
        m = manhattan(src_site, sink_site)

        if m is None:
            boundary_missing += 1
        else:
            boundary_total += m

    for b in s1:
        add_boundary_cost(b, h1["site"])

    for b in s2:
        add_boundary_cost(b, h2["site"])

    for b in d:
        add_boundary_cost(b, root["site"])

    current_root = phase3["boundary_outputs"][0]["source_cell"]
    output_driver_changed = root["cell"] != current_root

    upgraded_cells = []

    for slot, support_size in [
        (root, 6),
        (h1, len(s1)),
        (h2, len(s2)),
    ]:
        original_cap = ref_capacity(slot["ref"])
        if slot["ref"] != "LUT6" or original_cap < support_size:
            upgraded_cells.append(slot["cell"])

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
        "internal_manhattan_h1_to_root": internal_m1,
        "internal_manhattan_h2_to_root": internal_m2,
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


def generate_templates(phase3, boundary_count):
    """
    Genereer alle root-free / LUT2-upgrade templates.

    Nieuwe versie:
    - window mag meer dan 3 LUTs bevatten;
    - we kiezen root, h1, h2 uit alle LUTs in het window;
    - boundary_count mag kleiner zijn dan 12;
    - root blijft LUT6:
        I0 = H1
        I1 = H2
        I2..I5 = vier directe boundary inputs D
    - dus |D| blijft voorlopig exact 4.
    """
    luts = phase3.get("luts", [])
    all_inputs = tuple(range(1, boundary_count + 1))

    if boundary_count < 6:
        return

    role_id = 0

    for root in luts:
        helpers = [x for x in luts if x["cell"] != root["cell"]]

        for h1, h2 in itertools.permutations(helpers, 2):
            role_id += 1

            # Root krijgt altijd 4 directe boundary inputs.
            for d in itertools.combinations(all_inputs, 4):
                remaining = tuple(x for x in all_inputs if x not in d)

                # Remaining inputs worden verdeeld over H1 en H2.
                # Nieuwe versie: helper mag ook 1-input functie zijn.
                for k in range(1, 7):
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

                        yield template_cost(template, phase3)

def collect_top_templates(phase3, boundary_count, top_n):
    """
    Verzamel alleen de beste top_n templates volgens score_with_penalties.

    Nieuwe versie:
    - boundary_count wordt doorgegeven aan generate_templates;
    - sortering gebeurt primair op score_with_penalties;
    - werkt met windows groter dan 3 LUTs.
    """
    total = 0

    if top_n < 0:
        templates = []
        for t in generate_templates(phase3, boundary_count):
            total += 1
            templates.append(t)
        templates.sort(key=lambda x: (x["score_with_penalties"], x["score_without_penalties"]))
        return templates, total

    heap = []
    counter = 0

    for t in generate_templates(phase3, boundary_count):
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

# -----------------------------
# Main
# -----------------------------

def main():
    if len(sys.argv) < 4:
        fail(
            "usage: python3 phase5b2_fast_decompose_upgrade_lut2.py "
            "<phase3_window_info.json> <truth_table_compact.json> <out_dir> "
            "[top_templates_to_check] [max_candidates_to_keep] [stop_on_first_improved]"
        )

    phase3_path = os.path.abspath(sys.argv[1])
    phase4_path = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])

    top_templates_to_check = int(sys.argv[4]) if len(sys.argv) >= 5 else 20000
    max_candidates_to_keep = int(sys.argv[5]) if len(sys.argv) >= 6 else 200
    stop_on_first_improved = int(sys.argv[6]) if len(sys.argv) >= 7 else 1

    ensure_dir(out_dir)

    with open(phase3_path, "r") as f:
        phase3 = json.load(f)

    with open(phase4_path, "r") as f:
        phase4 = json.load(f)

    checks = []

    add_check(checks, "phase3_status", "PASS" if phase3.get("phase3_status") == "PASS" else "FAIL", phase3.get("phase3_status", ""))
    add_check(checks, "phase4_status", "PASS" if phase4.get("phase4_status") == "PASS" else "FAIL", phase4.get("phase4_status", ""))

    boundary_count = int(phase4["num_boundary_inputs"])
    output_count = int(phase4["num_boundary_outputs"])
    output_sequence = phase4["output_sequence"]

    if boundary_count < 6 or boundary_count > 12:
        add_check(
            checks,
            "boundary_count_supported",
            "FAIL",
            f"boundary_count={boundary_count}; supported range is 6..12",
        )
    else:
        add_check(
            checks,
            "boundary_count_supported",
            "PASS",
            f"boundary_count={boundary_count}",
        )
    if output_count != 1:
        add_check(checks, "single_output", "FAIL", f"output_count={output_count}")
    else:
        add_check(checks, "single_output", "PASS", "1")

    expected_truth_table_length = 1 << boundary_count

    if len(output_sequence) != expected_truth_table_length:
        add_check(
            checks,
            "truth_table_length",
            "FAIL",
            f"len={len(output_sequence)}, expected={expected_truth_table_length}",
        )
    else:
        add_check(
            checks,
            "truth_table_length",
            "PASS",
            str(expected_truth_table_length),
        )



    lut_count = len(phase3.get("luts", []))

    if lut_count < 3:
        add_check(checks, "at_least_three_luts", "FAIL", f"{lut_count}")
    else:
        add_check(checks, "at_least_three_luts", "PASS", f"{lut_count}")
    if any(c["status"] == "FAIL" for c in checks):
        write_csv(
            os.path.join(out_dir, "phase5b2_fast_validation_checks.csv"),
            ["check", "status", "detail"],
            checks,
        )
        fail("pre-checks failed")

    start = time.time()

    baseline_score = infer_baseline_score(phase3)

    print("[phase5b2-fast] collecting top templates...", flush=True)

    templates, total_template_count = collect_top_templates(
        phase3,
        boundary_count,
        top_templates_to_check,
    )
    print(f"[phase5b2-fast] total templates generated: {total_template_count}", flush=True)
    print(f"[phase5b2-fast] templates to check: {len(templates)}", flush=True)
    print(f"[phase5b2-fast] baseline_score={baseline_score}", flush=True)

    add_check(checks, "templates_generated", "PASS", f"total={total_template_count}, selected={len(templates)}")

    solved_rows = []
    candidates = []
    status_counts = {}

    best_improved_found = False

    progress_path = os.path.join(out_dir, "phase5b2_fast_progress.csv")

    with open(progress_path, "w", newline="") as pf:
        pw = csv.DictWriter(
            pf,
            fieldnames=[
                "template_index",
                "status",
                "candidate_count",
                "best_score",
                "elapsed_seconds",
            ],
        )
        pw.writeheader()

        for idx, template in enumerate(templates):
            result, status = solve_template_fast(
                output_sequence,
                template["S1"],
                template["S2"],
                template["D"],
            )

            status_counts[status] = status_counts.get(status, 0) + 1

            solved_rows.append({
                "template_index": idx,
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

            if result is not None:
                mismatches = simulate_candidate(
                    output_sequence,
                    template["S1"],
                    template["S2"],
                    template["D"],
                    result["h1_init_64"],
                    result["h2_init_64"],
                    result["root_init_64"],
                )

                if mismatches:
                    status = "post_sim_mismatch"
                    status_counts[status] = status_counts.get(status, 0) + 1
                else:
                    candidate_id = f"phase5b2_fast_exact_{len(candidates):05d}"

                    candidate = {
                        "candidate_id": candidate_id,
                        "family": "root_free_lut2_to_lut6_fast_exact_decomposition",
                        "root": template["root"],
                        "h1": template["h1"],
                        "h2": template["h2"],
                        "S1": template["S1"],
                        "S2": template["S2"],
                        "D": template["D"],
                        "h1_init_64_int": result["h1_init_64"],
                        "h2_init_64_int": result["h2_init_64"],
                        "root_init_64_int": result["root_init_64"],
                        "h1_init": format_init(result["h1_init_64"], 64),
                        "h2_init": format_init(result["h2_init_64"], 64),
                        "root_init": format_init(result["root_init_64"], 64),
                        "truth_table_equivalence": True,
                        "num_checked_vectors": len(output_sequence),
                        "window_depth": 2,
                        "unique_signature_count": result["unique_signature_count"],
                        "changed_pins": [],
                        "changed_pin_count": 0,
                        **{k: template[k] for k in [
                            "role_id",
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

                    changed = compute_changed_pins(candidate, phase3)
                    candidate["changed_pins"] = changed
                    candidate["changed_pin_count"] = len(changed)

                    candidates.append(candidate)

                    print(
                        f"[candidate] {candidate_id} "
                        f"score={candidate['score_without_penalties']} "
                        f"root={candidate['root']['cell']} "
                        f"h1={candidate['h1']['cell']} "
                        f"h2={candidate['h2']['cell']} "
                        f"upgrade={candidate['upgraded_cells']}",
                        flush=True,
                    )

                    if candidate["score_with_penalties"] < baseline_score:
                        best_improved_found = True

                        if stop_on_first_improved:
                            print("[phase5b2-fast] improved candidate found; stopping early.", flush=True)
                            break

            if idx % 500 == 0:
                best_score = min([c["score_without_penalties"] for c in candidates], default="")
                pw.writerow({
                    "template_index": idx,
                    "status": status,
                    "candidate_count": len(candidates),
                    "best_score": best_score,
                    "elapsed_seconds": round(time.time() - start, 3),
                })
                pf.flush()

                print(
                    f"[progress] checked={idx}/{len(templates)} "
                    f"status={status} candidates={len(candidates)}",
                    flush=True,
                )

    if candidates:
        add_check(checks, "exact_candidates_found", "PASS", str(len(candidates)))
    else:
        add_check(checks, "exact_candidates_found", "FAIL", "0")

    candidates.sort(key=lambda c: (
        c["score_with_penalties"],
        c["score_without_penalties"],
        c["changed_pin_count"],
        c["candidate_id"],
    ))

    kept_candidates = candidates[:max_candidates_to_keep]
    best = kept_candidates[0] if kept_candidates else None

    if best:
        estimated_improvement = best["score_with_penalties"] < baseline_score
        add_check(
            checks,
            "best_candidate_selected",
            "PASS",
            f"{best['candidate_id']} score={best['score_with_penalties']} baseline={baseline_score}",
        )
    else:
        estimated_improvement = False
        add_check(checks, "best_candidate_selected", "FAIL", "none")

    if best and estimated_improvement:
        phase_status = "PASS_IMPROVED_ESTIMATE"
    elif best:
        phase_status = "PASS_NO_ESTIMATED_IMPROVEMENT"
    else:
        phase_status = "FAIL"

    # Candidate CSV.
    candidate_rows = []
    for c in kept_candidates:
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
            "unique_signature_count": c["unique_signature_count"],
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
        os.path.join(out_dir, "phase5b2_fast_candidates.csv"),
        [
            "candidate_id",
            "root_cell",
            "root_original_ref",
            "h1_cell",
            "h1_original_ref",
            "h2_cell",
            "h2_original_ref",
            "S1",
            "S2",
            "D",
            "root_init",
            "h1_init",
            "h2_init",
            "truth_table_equivalence",
            "num_checked_vectors",
            "unique_signature_count",
            "changed_pin_count",
            "upgrade_count",
            "upgraded_cells",
            "output_driver_changed",
            "internal_manhattan_h1_to_root",
            "internal_manhattan_h2_to_root",
            "internal_manhattan_max",
            "boundary_manhattan_total",
            "score_without_penalties",
            "score_with_penalties",
        ],
        candidate_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5b2_fast_solved_templates.csv"),
        [
            "template_index",
            "status",
            "role_id",
            "root_cell",
            "h1_cell",
            "h2_cell",
            "S1",
            "S2",
            "D",
            "score_without_penalties",
            "score_with_penalties",
            "internal_manhattan_max",
            "boundary_manhattan_total",
            "upgrade_count",
            "upgraded_cells",
            "output_driver_changed",
        ],
        solved_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5b2_fast_validation_checks.csv"),
        ["check", "status", "detail"],
        checks,
    )

    # Selected candidate JSON.
    selected_path = os.path.join(out_dir, "phase5b2_fast_selected_candidate.json")
    selected_payload = None

    if best:
        selected_payload = {
            "phase": "FASE 5B.2 FAST",
            "phase5b2_fast_status": phase_status,
            "candidate_id": best["candidate_id"],
            "family": best["family"],
            "same_lut_positions": True,
            "same_window_boundary": True,
            "root_free": True,
            "lut2_upgrade_allowed": True,
            "all_roles_logical_lut6": True,
            "truth_table_equivalence": True,
            "num_checked_vectors": len(output_sequence),
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
                            {
                                "sink_pin": "I0",
                                "source": "helper1/O",
                                "source_cell": best["h1"]["cell"],
                            },
                            {
                                "sink_pin": "I1",
                                "source": "helper2/O",
                                "source_cell": best["h2"]["cell"],
                            },
                        ]
                        + [
                            {
                                "sink_pin": f"I{i + 2}",
                                "boundary_index": int(b),
                            }
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
                        {
                            "sink_pin": f"I{i}",
                            "boundary_index": int(b),
                        }
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
                        {
                            "sink_pin": f"I{i}",
                            "boundary_index": int(b),
                        }
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

    summary = {
        "phase": "FASE 5B.2 FAST",
        "phase5b2_fast_status": phase_status,
        "phase3_json": phase3_path,
        "truth_table_compact_json": phase4_path,
        "total_template_count": total_template_count,
        "templates_checked": len(solved_rows),
        "top_templates_to_check": top_templates_to_check,
        "status_counts": status_counts,
        "exact_candidate_count": len(candidates),
        "kept_candidate_count": len(kept_candidates),
        "baseline_score": baseline_score,
        "best_candidate_id": best["candidate_id"] if best else None,
        "best_score_without_penalties": best["score_without_penalties"] if best else None,
        "best_score_with_penalties": best["score_with_penalties"] if best else None,
        "estimated_improvement": estimated_improvement,
        "elapsed_seconds": round(time.time() - start, 3),
        "selected_candidate_json": selected_path,
        "validation_checks": checks,
        "boundary_count": boundary_count,
        "truth_table_length": len(output_sequence),
        "lut_count": len(phase3.get("luts", [])),

    }

    with open(os.path.join(out_dir, "phase5b2_fast_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(out_dir, "phase5b2_fast_summary.txt"), "w") as f:
        f.write(f"phase5b2_fast_status={phase_status}\n")
        f.write(f"total_template_count={total_template_count}\n")
        f.write(f"templates_checked={len(solved_rows)}\n")
        f.write(f"top_templates_to_check={top_templates_to_check}\n")
        f.write(f"status_counts={status_counts}\n")
        f.write(f"exact_candidate_count={len(candidates)}\n")
        f.write(f"kept_candidate_count={len(kept_candidates)}\n")
        f.write(f"baseline_score={baseline_score}\n")
        f.write(f"best_candidate_id={best['candidate_id'] if best else ''}\n")
        f.write(f"best_score_without_penalties={best['score_without_penalties'] if best else ''}\n")
        f.write(f"best_score_with_penalties={best['score_with_penalties'] if best else ''}\n")
        f.write(f"estimated_improvement={int(estimated_improvement)}\n")
        f.write(f"selected_candidate_json={selected_path}\n")
        f.write(f"elapsed_seconds={round(time.time() - start, 3)}\n")
        f.write(f"boundary_count={boundary_count}\n")
        f.write(f"truth_table_length={len(output_sequence)}\n")
        f.write(f"lut_count={len(phase3.get('luts', []))}\n")

    print(f"PHASE5B2_FAST_{phase_status}")
    print(f"Total templates : {total_template_count}")
    print(f"Checked templates: {len(solved_rows)}")
    print(f"Exact candidates: {len(candidates)}")
    print(f"Selected JSON   : {selected_path}")


if __name__ == "__main__":
    main()
