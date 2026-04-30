#!/usr/bin/env python3
"""
FASE 5B.3 FAST — Exacte 4-LUT decompositie via signature-tensor.

Doel:
  Zoek exact-equivalente decomposities van een <=12-input / 1-output windowfunctie
  met vier bestaande fysieke LUT-sites.

Belangrijk:
  - Geen approximation.
  - Geen Z3.
  - Geen nieuwe LUTs.
  - Exacte truth-table equivalentie over 2^boundary_count vectors.
  - Placement blijft vast.
  - Eerste 4-LUT uitbreiding van de bestaande 3-LUT Phase 5B.2 methode.
  - Output is een candidate.json in dezelfde stijl als Phase 5B.2, maar met helper3.

Decompositievorm:
    F(B1..Bn) = R(H1(S1), H2(S2), H3(S3), D)

waar:
    R  = root LUT6
    H1 = helper LUT6
    H2 = helper LUT6
    H3 = helper LUT6
    |D| = 3
    S1, S2 en S3 partitioneren de overige boundary inputs
    1 <= |S1| <= 6
    1 <= |S2| <= 6
    1 <= |S3| <= 6

Root pin order:
    I0 = H1 output
    I1 = H2 output
    I2 = H3 output
    I3 = D0
    I4 = D1
    I5 = D2

Gebruik:
  python3 phase5b3_fast_decompose_4lut.py \
      <phase3_window_info.json> \
      <truth_table_compact.json> \
      <out_dir> \
      [top_templates_to_check] \
      [max_candidates_to_keep] \
      [stop_on_first_improved] \
      [allow_output_driver_changed] \
      [max_unique_signatures]

Voorbeeld:
  python3 phase5b3_fast_decompose_4lut.py \
      phase3_window_info.json \
      truth_table_compact.json \
      phase5b3_fast \
      20000 \
      200 \
      1 \
      0 \
      5

Opmerking:
  Deze versie maakt nog geen Vivado-clean unused-pin cleanup af.
  Ze schrijft wel helper3 en used/unused pins mee zodat Phase 6 later gericht kan worden aangepast.
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
    m = re.fullmatch(r"LUT([1-6])", str(ref).strip())
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
    boundary_index is 1-based.
    """
    out = 0
    for local_i, bidx in enumerate(boundary_indices):
        bit = (row_index >> (int(bidx) - 1)) & 1
        out |= bit << local_i
    return out


def build_row_index_from_parts_3helpers(
    s1_assignment, s1,
    s2_assignment, s2,
    s3_assignment, s3,
    d_assignment, d,
):
    row = 0

    for local_i, bidx in enumerate(s1):
        bit = (s1_assignment >> local_i) & 1
        row |= bit << (int(bidx) - 1)

    for local_i, bidx in enumerate(s2):
        bit = (s2_assignment >> local_i) & 1
        row |= bit << (int(bidx) - 1)

    for local_i, bidx in enumerate(s3):
        bit = (s3_assignment >> local_i) & 1
        row |= bit << (int(bidx) - 1)

    for local_i, bidx in enumerate(d):
        bit = (d_assignment >> local_i) & 1
        row |= bit << (int(bidx) - 1)

    return row


def root_index_3helpers(h1_out, h2_out, h3_out, d_assignment, d_size=3):
    """
    Root pin order:
      I0 = H1 output
      I1 = H2 output
      I2 = H3 output
      I3 = D0
      I4 = D1
      I5 = D2
    """
    if d_size > 3:
        raise ValueError("root_index_3helpers supports d_size <= 3")

    idx = (int(h1_out) << 0) | (int(h2_out) << 1) | (int(h3_out) << 2)

    for i in range(d_size):
        bit = (d_assignment >> i) & 1
        idx |= bit << (i + 3)

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
# 4-LUT exact decomposition check
# -----------------------------

def compute_signature_tensor(output_sequence, s1, s2, s3, d):
    """
    Bouw tensor M[a][b][c].

    Elke entry is een 2^|D|-bit signature:
      bit d_assignment = F(S1=a, S2=b, S3=c, D=d_assignment)

    De decompositie bestaat alleen als deze tensor kan gefactoriseerd worden als:
      M[a][b][c] = T[H1(a)][H2(b)][H3(c)]
    met H1/H2/H3 binair.

    Eerste 4-LUT versie:
      |D| moet exact 3 zijn.
    """
    s1_size = len(s1)
    s2_size = len(s2)
    s3_size = len(s3)
    d_size = len(d)

    if d_size != 3:
        raise ValueError("FASE 5B.3-fast verwacht voorlopig |D| = 3")

    tensor = []
    unique = set()

    for a in range(1 << s1_size):
        plane = []

        for b in range(1 << s2_size):
            row = []

            for c in range(1 << s3_size):
                sig = 0

                for dd in range(1 << d_size):
                    row_index = build_row_index_from_parts_3helpers(
                        a, s1,
                        b, s2,
                        c, s3,
                        dd, d,
                    )
                    if output_sequence[row_index] == "1":
                        sig |= 1 << dd

                row.append(sig)
                unique.add(sig)

                # Nodige voorwaarde: root heeft 2^3 = 8 combinaties van H1/H2/H3.
                if len(unique) > 8:
                    return None, unique

            plane.append(row)

        tensor.append(plane)

    return tensor, unique


def allowed_triple_mask(T, val):
    """
    Triple bit order:
      bit = h1*4 + h2*2 + h3
    dus:
      bit 0 = 000
      bit 1 = 001
      bit 2 = 010
      bit 3 = 011
      bit 4 = 100
      bit 5 = 101
      bit 6 = 110
      bit 7 = 111
    """
    mask = 0
    for h1 in (0, 1):
        for h2 in (0, 1):
            for h3 in (0, 1):
                idx = h1 * 4 + h2 * 2 + h3
                if T[idx] == val:
                    mask |= 1 << idx
    return mask


def values_from_domain(mask):
    vals = []
    if mask & 1:
        vals.append(0)
    if mask & 2:
        vals.append(1)
    return vals


def triple_allowed(mask, a_val, b_val, c_val):
    bit = int(a_val) * 4 + int(b_val) * 2 + int(c_val)
    return (mask & (1 << bit)) != 0


def propagate_domains_3axis(a_domains, b_domains, c_domains, constraint_masks):
    """
    Arc-consistency-achtige propagatie voor 3-variabele constraints.

    Dit is bewust eenvoudig gehouden:
      voor elke constraint M[a][b][c] beperken we de domeinen van A[a], B[b], C[c]
      op basis van bestaande mogelijke waarden in de andere twee domeinen.
    """
    n_a = len(a_domains)
    n_b = len(b_domains)
    n_c = len(c_domains)

    changed = True

    while changed:
        changed = False

        for i in range(n_a):
            for j in range(n_b):
                for k in range(n_c):
                    mask = constraint_masks[i][j][k]

                    old_a = a_domains[i]
                    old_b = b_domains[j]
                    old_c = c_domains[k]

                    new_a = 0
                    for av in values_from_domain(old_a):
                        ok = False
                        for bv in values_from_domain(old_b):
                            for cv in values_from_domain(old_c):
                                if triple_allowed(mask, av, bv, cv):
                                    ok = True
                                    break
                            if ok:
                                break
                        if ok:
                            new_a |= 1 << av

                    new_b = 0
                    for bv in values_from_domain(old_b):
                        ok = False
                        for av in values_from_domain(new_a):
                            for cv in values_from_domain(old_c):
                                if triple_allowed(mask, av, bv, cv):
                                    ok = True
                                    break
                            if ok:
                                break
                        if ok:
                            new_b |= 1 << bv

                    new_c = 0
                    for cv in values_from_domain(old_c):
                        ok = False
                        for av in values_from_domain(new_a):
                            for bv in values_from_domain(new_b):
                                if triple_allowed(mask, av, bv, cv):
                                    ok = True
                                    break
                            if ok:
                                break
                        if ok:
                            new_c |= 1 << cv

                    if new_a == 0 or new_b == 0 or new_c == 0:
                        return None, None, None, False

                    if new_a != old_a:
                        a_domains[i] = new_a
                        changed = True

                    if new_b != old_b:
                        b_domains[j] = new_b
                        changed = True

                    if new_c != old_c:
                        c_domains[k] = new_c
                        changed = True

    return a_domains, b_domains, c_domains, True


def solve_label_csp_for_T_3axis(tensor, T, node_limit=50000):
    """
    Zoek labels:
      A-labels = H1(a)
      B-labels = H2(b)
      C-labels = H3(c)

    voor een vaste root table T.
    """
    n_a = len(tensor)
    n_b = len(tensor[0])
    n_c = len(tensor[0][0])

    constraint_masks = []

    for i in range(n_a):
        plane_masks = []
        for j in range(n_b):
            row_masks = []
            for k in range(n_c):
                val = tensor[i][j][k]
                mask = allowed_triple_mask(T, val)
                if mask == 0:
                    return None, None, None, False
                row_masks.append(mask)
            plane_masks.append(row_masks)
        constraint_masks.append(plane_masks)

    # Domain mask:
    #   1 = only 0
    #   2 = only 1
    #   3 = {0,1}
    a_domains = [3] * n_a
    b_domains = [3] * n_b
    c_domains = [3] * n_c

    # Symmetry breaking:
    # H1(0) = 0. Dit verwijdert minstens één globale inverter/permutatie-symmetrie.
    a_domains[0] = 1

    nodes = 0

    def dfs(adom, bdom, cdom):
        nonlocal nodes
        nodes += 1

        if nodes > node_limit:
            return None

        adom = list(adom)
        bdom = list(bdom)
        cdom = list(cdom)

        adom, bdom, cdom, ok = propagate_domains_3axis(adom, bdom, cdom, constraint_masks)
        if not ok:
            return None

        all_singleton = (
            all(x in (1, 2) for x in adom)
            and all(x in (1, 2) for x in bdom)
            and all(x in (1, 2) for x in cdom)
        )

        if all_singleton:
            alabels = [0 if x == 1 else 1 for x in adom]
            blabels = [0 if x == 1 else 1 for x in bdom]
            clabels = [0 if x == 1 else 1 for x in cdom]
            return alabels, blabels, clabels

        # Branch op kleinste niet-singleton domein. Alle niet-singletons zijn hier {0,1}.
        for idx, dom in enumerate(adom):
            if dom == 3:
                for val in (0, 1):
                    na = list(adom)
                    na[idx] = 1 << val
                    res = dfs(na, bdom, cdom)
                    if res is not None:
                        return res
                return None

        for idx, dom in enumerate(bdom):
            if dom == 3:
                for val in (0, 1):
                    nb = list(bdom)
                    nb[idx] = 1 << val
                    res = dfs(adom, nb, cdom)
                    if res is not None:
                        return res
                return None

        for idx, dom in enumerate(cdom):
            if dom == 3:
                for val in (0, 1):
                    nc = list(cdom)
                    nc[idx] = 1 << val
                    res = dfs(adom, bdom, nc)
                    if res is not None:
                        return res
                return None

        return None

    res = dfs(a_domains, b_domains, c_domains)

    if res is None:
        return None, None, None, False

    alabels, blabels, clabels = res
    return alabels, blabels, clabels, True


def factor_signature_tensor(tensor, unique_values, max_unique_signatures=5):
    """
    Exacte factorisatie:
      M[a][b][c] = T[H1(a)][H2(b)][H3(c)]

    Return:
      h1 labels, h2 labels, h3 labels, root table T

    Kritische beperking:
      Naieve T-enumeratie is product(unique_values, repeat=8).
      Daarom beperken we unique_signature_count voorlopig.
    """
    unique_values = sorted(unique_values)

    if len(unique_values) > max_unique_signatures:
        return None, "too_many_unique_for_T_enum"

    # T heeft 8 entries. Entries mogen herhaald worden.
    # Alle waarden die in de tensor voorkomen moeten in T aanwezig zijn.
    for T in product(unique_values, repeat=8):
        if not set(unique_values).issubset(set(T)):
            continue

        h1_labels, h2_labels, h3_labels, ok = solve_label_csp_for_T_3axis(tensor, T)
        if ok:
            return (h1_labels, h2_labels, h3_labels, T), "sat"

    return None, "not_factorable"


def solve_template_fast_4lut(output_sequence, s1, s2, s3, d, max_unique_signatures=5):
    """
    Constructieve exacte 4-LUT decompositiecheck.
    """
    tensor, unique_values = compute_signature_tensor(output_sequence, s1, s2, s3, d)

    if tensor is None:
        return None, "too_many_signatures"

    result, status = factor_signature_tensor(
        tensor,
        unique_values,
        max_unique_signatures=max_unique_signatures,
    )

    if result is None:
        return None, status

    h1_labels, h2_labels, h3_labels, T = result

    # H1 INIT small.
    h1_init_small = 0
    for assignment, label in enumerate(h1_labels):
        h1_init_small |= int(label) << assignment

    # H2 INIT small.
    h2_init_small = 0
    for assignment, label in enumerate(h2_labels):
        h2_init_small |= int(label) << assignment

    # H3 INIT small.
    h3_init_small = 0
    for assignment, label in enumerate(h3_labels):
        h3_init_small |= int(label) << assignment

    # Root INIT.
    # T index:
    #   idx = h1*4 + h2*2 + h3
    root_init = 0

    for h1 in (0, 1):
        for h2 in (0, 1):
            for h3 in (0, 1):
                sig = T[h1 * 4 + h2 * 2 + h3]

                for d_assignment in range(8):
                    bit = (sig >> d_assignment) & 1
                    ridx = root_index_3helpers(h1, h2, h3, d_assignment, d_size=3)
                    root_init |= bit << ridx

    return {
        "h1_init_small": h1_init_small,
        "h2_init_small": h2_init_small,
        "h3_init_small": h3_init_small,
        "h1_init_64": expand_support_init_to_lut6(h1_init_small, len(s1)),
        "h2_init_64": expand_support_init_to_lut6(h2_init_small, len(s2)),
        "h3_init_64": expand_support_init_to_lut6(h3_init_small, len(s3)),
        "root_init_64": root_init,
        "unique_signature_count": len(unique_values),
        "T": T,
    }, "sat"


def simulate_candidate_4lut(
    output_sequence,
    s1, s2, s3, d,
    h1_init_64, h2_init_64, h3_init_64, root_init_64,
):
    """
    Simuleer kandidaat over alle rijen van de truth table.
    """
    mismatches = []
    num_rows = len(output_sequence)

    for row in range(num_rows):
        h1_idx = project_assignment(row, s1)
        h2_idx = project_assignment(row, s2)
        h3_idx = project_assignment(row, s3)
        d_idx = project_assignment(row, d)

        h1_out = (h1_init_64 >> h1_idx) & 1
        h2_out = (h2_init_64 >> h2_idx) & 1
        h3_out = (h3_init_64 >> h3_idx) & 1

        root_inputs = [
            h1_out,
            h2_out,
            h3_out,
            (d_idx >> 0) & 1,
            (d_idx >> 1) & 1,
            (d_idx >> 2) & 1,
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


def compute_changed_pins_4lut(candidate, phase3):
    boundary_by_index = boundary_by_index_map(phase3)
    old_pin_map = build_old_pin_map(phase3)

    root = candidate["root"]
    h1 = candidate["h1"]
    h2 = candidate["h2"]
    h3 = candidate["h3"]

    new_pin_map = {}

    for i, bidx in enumerate(candidate["S1"]):
        new_pin_map[(h1["cell"], f"I{i}")] = new_source_id_from_boundary(bidx, boundary_by_index)

    for i, bidx in enumerate(candidate["S2"]):
        new_pin_map[(h2["cell"], f"I{i}")] = new_source_id_from_boundary(bidx, boundary_by_index)

    for i, bidx in enumerate(candidate["S3"]):
        new_pin_map[(h3["cell"], f"I{i}")] = new_source_id_from_boundary(bidx, boundary_by_index)

    new_pin_map[(root["cell"], "I0")] = f"INT:{h1['cell']}/O"
    new_pin_map[(root["cell"], "I1")] = f"INT:{h2['cell']}/O"
    new_pin_map[(root["cell"], "I2")] = f"INT:{h3['cell']}/O"

    for i, bidx in enumerate(candidate["D"]):
        new_pin_map[(root["cell"], f"I{i + 3}")] = new_source_id_from_boundary(bidx, boundary_by_index)

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


def used_unused_pins_for_support(support_size):
    used = [f"I{i}" for i in range(support_size)]
    unused = [f"I{i}" for i in range(support_size, 6)]
    return used, unused


def template_cost_4lut(template, phase3):
    boundary_by_index = boundary_by_index_map(phase3)

    root = template["root"]
    h1 = template["h1"]
    h2 = template["h2"]
    h3 = template["h3"]
    s1 = template["S1"]
    s2 = template["S2"]
    s3 = template["S3"]
    d = template["D"]

    internal_m1 = manhattan(h1["site"], root["site"])
    internal_m2 = manhattan(h2["site"], root["site"])
    internal_m3 = manhattan(h3["site"], root["site"])

    internal_total = (internal_m1 or 0) + (internal_m2 or 0) + (internal_m3 or 0)
    internal_max = max(internal_m1 or 0, internal_m2 or 0, internal_m3 or 0)

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

    for b in s3:
        add_boundary_cost(b, h3["site"])

    for b in d:
        add_boundary_cost(b, root["site"])

    current_root = phase3["boundary_outputs"][0]["source_cell"]
    output_driver_changed = root["cell"] != current_root

    upgraded_cells = []

    for slot, support_size in [
        (root, 6),
        (h1, len(s1)),
        (h2, len(s2)),
        (h3, len(s3)),
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
        "internal_manhattan_h3_to_root": internal_m3,
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


def allowed_support_size_triples(remaining_count):
    """
    Beperk eerste 4-LUT versie tot redelijke supportverdelingen.

    We genereren ordered triples (s1_size, s2_size, s3_size) met:
      sum = remaining_count
      1 <= size <= 6

    Extra heuristiek:
      verschil tussen grootste en kleinste support maximaal 2.
    Dit vermijdt extreme templates zoals 6/1/1 in de eerste versie.
    """
    triples = []

    for a in range(1, 7):
        for b in range(1, 7):
            for c in range(1, 7):
                if a + b + c != remaining_count:
                    continue
                if max(a, b, c) - min(a, b, c) > 2:
                    continue
                triples.append((a, b, c))

    return triples


def generate_ordered_partitions_by_sizes(items, sizes):
    """
    Genereer ordered partitions:
      S1 size sizes[0]
      S2 size sizes[1]
      S3 size sizes[2]

    items is een tuple.
    """
    s1_size, s2_size, s3_size = sizes

    for s1 in itertools.combinations(items, s1_size):
        rem1 = tuple(x for x in items if x not in s1)

        for s2 in itertools.combinations(rem1, s2_size):
            s3 = tuple(x for x in rem1 if x not in s2)

            if len(s3) != s3_size:
                continue

            yield tuple(s1), tuple(s2), tuple(s3)


def generate_templates_4lut(
    phase3,
    boundary_count,
    d_size=3,
    allow_output_driver_changed=False,
):
    """
    Genereer 4-LUT templates.

    Eerste versie:
      - root, h1, h2, h3 worden gekozen uit bestaande window LUTs.
      - root krijgt 3 helper outputs + 3 directe boundary inputs.
      - S1/S2/S3 partitioneren de overige inputs.
      - supportverdelingen worden beperkt door allowed_support_size_triples().
    """
    luts = phase3.get("luts", [])
    all_inputs = tuple(range(1, boundary_count + 1))

    if boundary_count < 6:
        return

    if d_size != 3:
        raise ValueError("generate_templates_4lut supports voorlopig alleen d_size=3")

    current_root = phase3["boundary_outputs"][0]["source_cell"]

    role_id = 0

    for root in luts:
        if not allow_output_driver_changed and root["cell"] != current_root:
            continue

        helpers = [x for x in luts if x["cell"] != root["cell"]]

        for h1, h2, h3 in itertools.permutations(helpers, 3):
            role_id += 1

            for d in itertools.combinations(all_inputs, d_size):
                remaining = tuple(x for x in all_inputs if x not in d)
                support_triples = allowed_support_size_triples(len(remaining))

                for sizes in support_triples:
                    for s1, s2, s3 in generate_ordered_partitions_by_sizes(remaining, sizes):
                        template = {
                            "role_id": role_id,
                            "root": root,
                            "h1": h1,
                            "h2": h2,
                            "h3": h3,
                            "D": tuple(d),
                            "S1": tuple(s1),
                            "S2": tuple(s2),
                            "S3": tuple(s3),
                            "support_sizes": sizes,
                        }

                        yield template_cost_4lut(template, phase3)


def collect_top_templates_4lut(
    phase3,
    boundary_count,
    top_n,
    allow_output_driver_changed=False,
):
    """
    Verzamel alleen de beste top_n templates volgens score_with_penalties.
    """
    total = 0

    if top_n < 0:
        templates = []
        for t in generate_templates_4lut(
            phase3,
            boundary_count,
            d_size=3,
            allow_output_driver_changed=allow_output_driver_changed,
        ):
            total += 1
            templates.append(t)
        templates.sort(key=lambda x: (x["score_with_penalties"], x["score_without_penalties"]))
        return templates, total

    heap = []
    counter = 0

    for t in generate_templates_4lut(
        phase3,
        boundary_count,
        d_size=3,
        allow_output_driver_changed=allow_output_driver_changed,
    ):
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
            print(f"[collect-4lut] generated={total}, kept={len(heap)}", flush=True)

    templates = [item[2] for item in heap]
    templates.sort(key=lambda x: (x["score_with_penalties"], x["score_without_penalties"]))

    return templates, total


# -----------------------------
# Candidate formatting
# -----------------------------

def helper_role_payload(role_name, role_short, slot, support, init_value):
    used, unused = used_unused_pins_for_support(len(support))

    return {
        "role": role_short,
        "cell": slot["cell"],
        "original_ref": slot["ref"],
        "logical_ref": "LUT6",
        "site": slot["site"],
        "bel": slot["bel"],
        "new_INIT": format_init(init_value, 64),
        "support_size": len(support),
        "used_pins": used,
        "unused_pins": unused,
        "inputs": [
            {
                "sink_pin": f"I{i}",
                "boundary_index": int(b),
            }
            for i, b in enumerate(support)
        ],
    }


def root_role_payload(root, h1, h2, h3, d, root_init):
    used, unused = used_unused_pins_for_support(6)

    return {
        "role": "R",
        "cell": root["cell"],
        "original_ref": root["ref"],
        "logical_ref": "LUT6",
        "site": root["site"],
        "bel": root["bel"],
        "new_INIT": format_init(root_init, 64),
        "support_size": 6,
        "used_pins": used,
        "unused_pins": unused,
        "inputs": (
            [
                {
                    "sink_pin": "I0",
                    "source": "helper1/O",
                    "source_cell": h1["cell"],
                },
                {
                    "sink_pin": "I1",
                    "source": "helper2/O",
                    "source_cell": h2["cell"],
                },
                {
                    "sink_pin": "I2",
                    "source": "helper3/O",
                    "source_cell": h3["cell"],
                },
            ]
            + [
                {
                    "sink_pin": f"I{i + 3}",
                    "boundary_index": int(b),
                }
                for i, b in enumerate(d)
            ]
        ),
    }


# -----------------------------
# Main
# -----------------------------

def main():
    if len(sys.argv) < 4:
        fail(
            "usage: python3 phase5b3_fast_decompose_4lut.py "
            "<phase3_window_info.json> <truth_table_compact.json> <out_dir> "
            "[top_templates_to_check] [max_candidates_to_keep] [stop_on_first_improved] "
            "[allow_output_driver_changed] [max_unique_signatures]"
        )

    phase3_path = os.path.abspath(sys.argv[1])
    phase4_path = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])

    top_templates_to_check = int(sys.argv[4]) if len(sys.argv) >= 5 else 20000
    max_candidates_to_keep = int(sys.argv[5]) if len(sys.argv) >= 6 else 200
    stop_on_first_improved = int(sys.argv[6]) if len(sys.argv) >= 7 else 1
    allow_output_driver_changed = bool(int(sys.argv[7])) if len(sys.argv) >= 8 else False
    max_unique_signatures = int(sys.argv[8]) if len(sys.argv) >= 9 else 5

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

    # Voor deze 4-LUT vorm:
    # root heeft H1/H2/H3 + D(3), dus remaining inputs moeten over 3 helpers kunnen.
    # Minimum boundary_count = D(3) + 1 + 1 + 1 = 6.
    # Maximum blijft 12 door truth-table/praktische limiet.
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

    if lut_count < 4:
        add_check(checks, "at_least_four_luts", "FAIL", f"{lut_count}")
    else:
        add_check(checks, "at_least_four_luts", "PASS", f"{lut_count}")

    if max_unique_signatures < 1 or max_unique_signatures > 8:
        add_check(checks, "max_unique_signatures_range", "FAIL", str(max_unique_signatures))
    else:
        add_check(checks, "max_unique_signatures_range", "PASS", str(max_unique_signatures))

    if any(c["status"] == "FAIL" for c in checks):
        write_csv(
            os.path.join(out_dir, "phase5b3_fast_validation_checks.csv"),
            ["check", "status", "detail"],
            checks,
        )
        fail("pre-checks failed")

    start = time.time()

    baseline_score = infer_baseline_score(phase3)

    print("[phase5b3-fast] collecting top 4-LUT templates...", flush=True)
    print(f"[phase5b3-fast] allow_output_driver_changed={int(allow_output_driver_changed)}", flush=True)
    print(f"[phase5b3-fast] max_unique_signatures={max_unique_signatures}", flush=True)

    templates, total_template_count = collect_top_templates_4lut(
        phase3,
        boundary_count,
        top_templates_to_check,
        allow_output_driver_changed=allow_output_driver_changed,
    )

    print(f"[phase5b3-fast] total templates generated: {total_template_count}", flush=True)
    print(f"[phase5b3-fast] templates to check: {len(templates)}", flush=True)
    print(f"[phase5b3-fast] baseline_score={baseline_score}", flush=True)

    add_check(checks, "templates_generated", "PASS", f"total={total_template_count}, selected={len(templates)}")

    solved_rows = []
    candidates = []
    status_counts = {}

    best_improved_found = False

    progress_path = os.path.join(out_dir, "phase5b3_fast_progress.csv")

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
            result, status = solve_template_fast_4lut(
                output_sequence,
                template["S1"],
                template["S2"],
                template["S3"],
                template["D"],
                max_unique_signatures=max_unique_signatures,
            )

            status_counts[status] = status_counts.get(status, 0) + 1

            solved_rows.append({
                "template_index": idx,
                "status": status,
                "role_id": template["role_id"],
                "root_cell": template["root"]["cell"],
                "h1_cell": template["h1"]["cell"],
                "h2_cell": template["h2"]["cell"],
                "h3_cell": template["h3"]["cell"],
                "S1": "|".join(map(str, template["S1"])),
                "S2": "|".join(map(str, template["S2"])),
                "S3": "|".join(map(str, template["S3"])),
                "D": "|".join(map(str, template["D"])),
                "support_sizes": "|".join(map(str, template["support_sizes"])),
                "score_without_penalties": template["score_without_penalties"],
                "score_with_penalties": template["score_with_penalties"],
                "internal_manhattan_max": template["internal_manhattan_max"],
                "boundary_manhattan_total": template["boundary_manhattan_total"],
                "upgrade_count": template["upgrade_count"],
                "upgraded_cells": "|".join(template["upgraded_cells"]),
                "output_driver_changed": int(template["output_driver_changed"]),
            })

            if result is not None:
                mismatches = simulate_candidate_4lut(
                    output_sequence,
                    template["S1"],
                    template["S2"],
                    template["S3"],
                    template["D"],
                    result["h1_init_64"],
                    result["h2_init_64"],
                    result["h3_init_64"],
                    result["root_init_64"],
                )

                if mismatches:
                    status = "post_sim_mismatch"
                    status_counts[status] = status_counts.get(status, 0) + 1
                else:
                    candidate_id = f"phase5b3_fast_exact_{len(candidates):05d}"

                    candidate = {
                        "candidate_id": candidate_id,
                        "family": "root_free_4lut_fast_exact_signature_tensor",
                        "root": template["root"],
                        "h1": template["h1"],
                        "h2": template["h2"],
                        "h3": template["h3"],
                        "S1": template["S1"],
                        "S2": template["S2"],
                        "S3": template["S3"],
                        "D": template["D"],
                        "support_sizes": template["support_sizes"],
                        "h1_init_64_int": result["h1_init_64"],
                        "h2_init_64_int": result["h2_init_64"],
                        "h3_init_64_int": result["h3_init_64"],
                        "root_init_64_int": result["root_init_64"],
                        "h1_init": format_init(result["h1_init_64"], 64),
                        "h2_init": format_init(result["h2_init_64"], 64),
                        "h3_init": format_init(result["h3_init_64"], 64),
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
                            "internal_manhattan_h3_to_root",
                            "internal_manhattan_total",
                            "internal_manhattan_max",
                            "boundary_manhattan_total",
                            "boundary_manhattan_missing",
                            "output_driver_changed",
                            "upgrade_count",
                            "upgraded_cells",
                        ]},
                    }

                    changed = compute_changed_pins_4lut(candidate, phase3)
                    candidate["changed_pins"] = changed
                    candidate["changed_pin_count"] = len(changed)

                    candidates.append(candidate)

                    print(
                        f"[candidate] {candidate_id} "
                        f"score={candidate['score_without_penalties']} "
                        f"root={candidate['root']['cell']} "
                        f"h1={candidate['h1']['cell']} "
                        f"h2={candidate['h2']['cell']} "
                        f"h3={candidate['h3']['cell']} "
                        f"support={candidate['support_sizes']} "
                        f"unique_sig={candidate['unique_signature_count']} "
                        f"upgrade={candidate['upgraded_cells']}",
                        flush=True,
                    )

                    if candidate["score_with_penalties"] < baseline_score:
                        best_improved_found = True

                        if stop_on_first_improved:
                            print("[phase5b3-fast] improved candidate found; stopping early.", flush=True)
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
            "h3_cell": c["h3"]["cell"],
            "h3_original_ref": c["h3"]["ref"],
            "S1": "|".join(map(str, c["S1"])),
            "S2": "|".join(map(str, c["S2"])),
            "S3": "|".join(map(str, c["S3"])),
            "D": "|".join(map(str, c["D"])),
            "support_sizes": "|".join(map(str, c["support_sizes"])),
            "root_init": c["root_init"],
            "h1_init": c["h1_init"],
            "h2_init": c["h2_init"],
            "h3_init": c["h3_init"],
            "truth_table_equivalence": int(c["truth_table_equivalence"]),
            "num_checked_vectors": c["num_checked_vectors"],
            "unique_signature_count": c["unique_signature_count"],
            "changed_pin_count": c["changed_pin_count"],
            "upgrade_count": c["upgrade_count"],
            "upgraded_cells": "|".join(c["upgraded_cells"]),
            "output_driver_changed": int(c["output_driver_changed"]),
            "internal_manhattan_h1_to_root": c["internal_manhattan_h1_to_root"],
            "internal_manhattan_h2_to_root": c["internal_manhattan_h2_to_root"],
            "internal_manhattan_h3_to_root": c["internal_manhattan_h3_to_root"],
            "internal_manhattan_max": c["internal_manhattan_max"],
            "boundary_manhattan_total": c["boundary_manhattan_total"],
            "score_without_penalties": c["score_without_penalties"],
            "score_with_penalties": c["score_with_penalties"],
        })

    write_csv(
        os.path.join(out_dir, "phase5b3_fast_candidates.csv"),
        [
            "candidate_id",
            "root_cell",
            "root_original_ref",
            "h1_cell",
            "h1_original_ref",
            "h2_cell",
            "h2_original_ref",
            "h3_cell",
            "h3_original_ref",
            "S1",
            "S2",
            "S3",
            "D",
            "support_sizes",
            "root_init",
            "h1_init",
            "h2_init",
            "h3_init",
            "truth_table_equivalence",
            "num_checked_vectors",
            "unique_signature_count",
            "changed_pin_count",
            "upgrade_count",
            "upgraded_cells",
            "output_driver_changed",
            "internal_manhattan_h1_to_root",
            "internal_manhattan_h2_to_root",
            "internal_manhattan_h3_to_root",
            "internal_manhattan_max",
            "boundary_manhattan_total",
            "score_without_penalties",
            "score_with_penalties",
        ],
        candidate_rows,
    )

    write_csv(
        os.path.join(out_dir, "phase5b3_fast_solved_templates.csv"),
        [
            "template_index",
            "status",
            "role_id",
            "root_cell",
            "h1_cell",
            "h2_cell",
            "h3_cell",
            "S1",
            "S2",
            "S3",
            "D",
            "support_sizes",
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
        os.path.join(out_dir, "phase5b3_fast_validation_checks.csv"),
        ["check", "status", "detail"],
        checks,
    )

    selected_path = os.path.join(out_dir, "phase5b3_fast_selected_candidate.json")
    selected_payload = None

    if best:
        selected_payload = {
            "phase": "FASE 5B.3 FAST",
            "phase5b3_fast_status": phase_status,
            "candidate_id": best["candidate_id"],
            "family": best["family"],
            "same_lut_positions": True,
            "same_window_boundary": True,
            "root_free": True,
            "four_lut_signature_tensor": True,
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
            "support_sizes": list(best["support_sizes"]),
            "max_unique_signatures": max_unique_signatures,
            "roles": {
                "root": root_role_payload(
                    best["root"],
                    best["h1"],
                    best["h2"],
                    best["h3"],
                    best["D"],
                    best["root_init_64_int"],
                ),
                "helper1": helper_role_payload(
                    "helper1",
                    "H1",
                    best["h1"],
                    best["S1"],
                    best["h1_init_64_int"],
                ),
                "helper2": helper_role_payload(
                    "helper2",
                    "H2",
                    best["h2"],
                    best["S2"],
                    best["h2_init_64_int"],
                ),
                "helper3": helper_role_payload(
                    "helper3",
                    "H3",
                    best["h3"],
                    best["S3"],
                    best["h3_init_64_int"],
                ),
            },
            "changed_pins": best["changed_pins"],
            "cost": {
                "internal_manhattan_h1_to_root": best["internal_manhattan_h1_to_root"],
                "internal_manhattan_h2_to_root": best["internal_manhattan_h2_to_root"],
                "internal_manhattan_h3_to_root": best["internal_manhattan_h3_to_root"],
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
        "phase": "FASE 5B.3 FAST",
        "phase5b3_fast_status": phase_status,
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
        "allow_output_driver_changed": allow_output_driver_changed,
        "max_unique_signatures": max_unique_signatures,
        "d_size": 3,
    }

    with open(os.path.join(out_dir, "phase5b3_fast_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(out_dir, "phase5b3_fast_summary.txt"), "w") as f:
        f.write(f"phase5b3_fast_status={phase_status}\n")
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
        f.write(f"allow_output_driver_changed={int(allow_output_driver_changed)}\n")
        f.write(f"max_unique_signatures={max_unique_signatures}\n")
        f.write("d_size=3\n")

    print(f"PHASE5B3_FAST_{phase_status}")
    print(f"Total templates : {total_template_count}")
    print(f"Checked templates: {len(solved_rows)}")
    print(f"Exact candidates: {len(candidates)}")
    print(f"Selected JSON   : {selected_path}")


if __name__ == "__main__":
    main()
