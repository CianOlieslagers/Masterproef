#!/usr/bin/env python3
import json
import argparse
from typing import Any, Dict, List, Set


# -----------------------------
# Helper: hex normaliseren
# -----------------------------

def normalize_hex(h: str) -> str:
    """
    Normaliseer hex-string:
      - lowercase
      - geen '0x'
    """
    if h is None:
        return None
    h = str(h).strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    return h


# -----------------------------
# Truth table evaluatie
# -----------------------------

def eval_tt(func_hex: str, num_vars: int, assignment: List[int]) -> int:
    """
    Evalueer een truth table (func_hex) op een gegeven assignment.

    - func_hex: hex-string van 2^num_vars bits (kitty-conventie)
    - assignment[j]: 0/1 voor variabele j (0..num_vars-1)
    - We gebruiken index = sum_j assignment[j] << j
    """
    func_hex = normalize_hex(func_hex)
    if not func_hex:
        return 0

    v = int(func_hex, 16)

    idx = 0
    for j, bit in enumerate(assignment):
        if bit:
            idx |= (1 << j)

    return (v >> idx) & 1


def funcs_match_on_overlap(
    dst_func_hex: str,
    dst_num_vars: int,
    dst_leaf_index: Dict[int, int],
    pit_func_hex: str,
    pit_num_vars: int,
    pit_leaf_index: Dict[int, int],
    common_leaf_ids: Set[int],
) -> bool:
    """
    Check of dst-functie (node in cone van dst) en pitstop-functie
    hetzelfde zijn (of complement) op de overlappende leaves.

    We zetten alle niet-overlappende leaves gewoon op 0.
    """

    if not common_leaf_ids:
        return False

    ids = sorted(common_leaf_ids)
    m = len(ids)

    eq_ok = True      # kunnen nog exact gelijk zijn
    comp_ok = True    # kunnen nog complement zijn

    total = 1 << m
    for mask in range(total):
        # Bouw assignments voor dst en pit
        dst_assign = [0] * dst_num_vars
        pit_assign = [0] * pit_num_vars

        for k, leaf_id in enumerate(ids):
            bit = (mask >> k) & 1

            # zet bit voor juiste variabele in dst
            idx_dst = dst_leaf_index[leaf_id]
            dst_assign[idx_dst] = bit

            # en voor pit
            idx_pit = pit_leaf_index[leaf_id]
            pit_assign[idx_pit] = bit

        v_dst = eval_tt(dst_func_hex, dst_num_vars, dst_assign)
        v_pit = eval_tt(pit_func_hex, pit_num_vars, pit_assign)

        if v_dst != v_pit:
            eq_ok = False
        if v_dst == v_pit:
            comp_ok = False

        if not eq_ok and not comp_ok:
            return False

    return eq_ok or comp_ok


# -----------------------------
# LUT-cones DB inlezen
# -----------------------------

def load_lut_db(lut_cones_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Bouw een kleine DB uit example_big_300.lut_cones.json:

      lut_db["LUT_11"] = {
        "leaves": [1,2,3,4],
        "leaf_index": {1:0, 2:1, 3:2, 4:3},
        "node_funcs": { 11: "8777", 7: "...", 8: "...", ... }
      }
    """
    with open(lut_cones_path, "r") as f:
        data = json.load(f)

    lut_cones = data.get("lut_cones", [])
    lut_db: Dict[str, Dict[str, Any]] = {}

    for cone in lut_cones:
        lut_name = cone.get("lut_name")
        if not lut_name:
            continue

        leaves = cone.get("leaves", [])
        leaf_index = {leaf_id: idx for idx, leaf_id in enumerate(leaves)}

        node_funcs: Dict[int, str] = {}
        # node_functions bevat root + internals
        for nf in cone.get("node_functions", []):
            nid = nf.get("node")
            fh = normalize_hex(nf.get("func_hex"))
            if nid is None or fh is None:
                continue
            node_funcs[int(nid)] = fh

        # fallback: zorg dat root er zeker in zit
        root_id = cone.get("lut_root")
        root_hex = normalize_hex(cone.get("func_hex"))
        if root_id is not None and root_hex is not None:
            if int(root_id) not in node_funcs:
                node_funcs[int(root_id)] = root_hex

        lut_db[lut_name] = {
            "leaves": leaves,
            "leaf_index": leaf_index,
            "node_funcs": node_funcs,
        }

    print(f"[INFO] LUT DB geladen uit {lut_cones_path} ({len(lut_db)} LUTs)")
    return lut_db


# -----------------------------
# Scenario 1 filtering
# -----------------------------

def filter_connections(
    input_json: str,
    output_json: str,
    lut_cones_path: str,
    min_leaf_overlap: int = 2,
) -> None:
    """
    Lees example_big_300.lut_connections_full.json en filter pitstops
    volgens ECHT Scenario 1:

      - Er moet voldoende overlap zijn in leaves tussen dst en pitstop.
      - Er moet een node in de cone van dst bestaan waarvoor
        f_node(overlap) == f_pit(overlap) (of complement).
      - NIEUW: die overlap moet minstens één leaf bevatten die ook
        als leaf van src optreedt (=> afhankelijk van src-signaal).

    Hiervoor gebruiken we:
      - per verbinding: src.aig.leaves, dst.aig.leaves, pit.aig.leaves/func_hex
      - uit lut_cones.json: dst.node_functions (truth tables per node).
    """

    lut_db = load_lut_db(lut_cones_path)

    with open(input_json, "r") as f:
        data = json.load(f)

    connections: List[Dict[str, Any]] = data.get("connections", [])
    total_pits_before = 0
    total_pits_after = 0

    for idx, conn in enumerate(connections):
        dst = conn.get("dst", {})
        dst_lut_name = dst.get("lut_name")
        dst_aig = dst.get("aig", {})

        dst_leaves = dst_aig.get("leaves", [])
        dst_leaves_set = set(dst_leaves)
        dst_num_vars = len(dst_leaves)
        dst_leaf_index = {leaf_id: i for i, leaf_id in enumerate(dst_leaves)}

        # Info uit lut_cones: node_functions voor dst
        dst_entry = lut_db.get(dst_lut_name)
        if dst_entry is None:
            # We kunnen geen interne nodes checken → alle pitstops droppen
            orig_len = len(conn.get("pitstops", []))
            total_pits_before += orig_len
            conn["pitstops"] = []
            continue

        node_funcs = dst_entry["node_funcs"]  # node_id -> func_hex (norm)

        # NIEUW: info over src (voor "afhankelijk van src"-check)
        src = conn.get("src", {})
        src_aig = src.get("aig", {})
        src_leaves = src_aig.get("leaves", [])
        src_leaves_set = set(src_leaves)

        new_pitstops = []
        for pit in conn.get("pitstops", []):
            total_pits_before += 1

            pit_aig = pit.get("aig", {})
            pit_func_hex = normalize_hex(pit_aig.get("func_hex"))
            pit_leaves = pit_aig.get("leaves", [])

            if not pit_func_hex or not pit_leaves:
                # Geen goede functie-info
                continue

            pit_num_vars = len(pit_leaves)
            pit_leaf_index = {leaf_id: i for i, leaf_id in enumerate(pit_leaves)}

            pit_leaves_set = set(pit_leaves)

            # Overlappende leaves tussen dst en pit
            common = dst_leaves_set & pit_leaves_set
            if len(common) < min_leaf_overlap:
                # te weinig gedeelde inputs om als subexpressie interessant te zijn
                continue

            # EXTRA: overlap moet minstens één leaf bevatten die ook in src zit
            common_with_src = common & src_leaves_set
            if not common_with_src:
                # dst en pit delen wel iets, maar niets dat via src komt
                continue

            # Check of er minstens één node in dst-cone is
            # met dezelfde functie als pit (op de src-gerelateerde overlap).
            scen1_ok = False
            for node_id, node_hex in node_funcs.items():
                if funcs_match_on_overlap(
                    dst_func_hex=node_hex,
                    dst_num_vars=dst_num_vars,
                    dst_leaf_index=dst_leaf_index,
                    pit_func_hex=pit_func_hex,
                    pit_num_vars=pit_num_vars,
                    pit_leaf_index=pit_leaf_index,
                    common_leaf_ids=common_with_src,
                ):
                    scen1_ok = True
                    break

            if scen1_ok:
                new_pitstops.append(pit)
                total_pits_after += 1

        conn["pitstops"] = new_pitstops

    data["scenario1_filter"] = {
        "min_leaf_overlap": min_leaf_overlap,
        "total_pitstops_before": total_pits_before,
        "total_pitstops_after": total_pits_after,
    }

    with open(output_json, "w") as f:
        json.dump(data, f, indent=2)

    print("[OK] Scenario 1 filtering gedaan (subexpressies + src-overlap).")
    print(f"     Pitstops vóór : {total_pits_before}")
    print(f"     Pitstops na   : {total_pits_after}")
    print(f"     Output        : {output_json}")

# -----------------------------
# main
# -----------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Filter pitstop-LUTs volgens Scenario 1 (subexpressie in dst-cone)."
    )
    parser.add_argument("--in", dest="inp", required=True,
                        help="Input JSON (…lut_connections_full.json)")
    parser.add_argument("--out", dest="out", required=True,
                        help="Output JSON met gefilterde pitstops")
    parser.add_argument("--lut-cones", required=True,
                        help="Pad naar example_big_300.lut_cones.json (met node_functions)")
    parser.add_argument("--min-overlap", type=int, default=2,
                        help="Minimum # overlappende leaves tussen dst en pitstop (default: 2)")

    args = parser.parse_args()

    filter_connections(
        input_json=args.inp,
        output_json=args.out,
        lut_cones_path=args.lut_cones,
        min_leaf_overlap=args.min_overlap,
    )
