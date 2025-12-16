#!/usr/bin/env python3
import json
import argparse
import os
from typing import Any, Dict, List, Set, Tuple


def load_json(path: str) -> Any:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"[FATAL] JSON-bestand niet gevonden: {path}")
    with open(path, "r") as f:
        data = json.load(f)
    return data


def leaves_from_aig(aig_obj: Dict[str, Any]) -> List[int]:
    """
    Haal de lijst van AIG-leaves uit een { 'aig': {...} } object.
    Als er iets ontbreekt, geef een lege lijst terug (en log later).
    """
    if not isinstance(aig_obj, dict):
        return []
    return aig_obj.get("leaves", []) or []


def as_set_int(xs: List[Any]) -> Set[int]:
    return {int(x) for x in xs}


def summarize_connection(idx: int, conn: Dict[str, Any]) -> str:
    """Korte één-regel samenvatting voor logging."""
    src = conn.get("src", {})
    dst = conn.get("dst", {})
    src_name = src.get("lut_name") or src.get("block")
    dst_name = dst.get("lut_name") or dst.get("block")
    d_ab = conn.get("d_ab", "?")
    num_pits = len(conn.get("pitstops", []))
    return f"[CONN {idx}] src={src_name}, dst={dst_name}, d_ab={d_ab}, pitstops={num_pits}"


def build_candidate_instance(
    design: str,
    conn_idx: int,
    pit_idx: int,
    conn: Dict[str, Any],
    pit: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Bouw een compacte instance-structuur met alle info die we later nodig hebben
    voor Scenario 2a/2b (ECO patch rond één pitstop).
    """

    src = conn.get("src", {})
    dst = conn.get("dst", {})

    src_aig = src.get("aig", {}) or {}
    dst_aig = dst.get("aig", {}) or {}
    pit_aig = pit.get("aig", {}) or {}

    src_leaves = as_set_int(leaves_from_aig(src_aig))
    dst_leaves = as_set_int(leaves_from_aig(dst_aig))
    pit_leaves = as_set_int(leaves_from_aig(pit_aig))

    # Overlaps
    overlap_src_pit = sorted(src_leaves & pit_leaves)
    overlap_dst_pit = sorted(dst_leaves & pit_leaves)
    overlap_src_dst = sorted(src_leaves & dst_leaves)

    # Manhattan / costs
    distances = pit.get("distances", {}) or {}
    costs = pit.get("costs", {}) or {}

    instance = {
        "format": "eco_candidate:v1",
        "design": design,
        "connection_index": conn_idx,
        "pitstop_index": pit_idx,
        "src": {
            "block": src.get("block"),
            "lut_name": src.get("lut_name"),
            "lut_root": src_aig.get("lut_root"),
            "coords": src.get("coords", {}),
            "aig": {
                "leaves": sorted(src_leaves),
                "func_hex": src_aig.get("func_hex"),
            },
            "expr_root": src.get("expr_root"),
        },
        "dst": {
            "block": dst.get("block"),
            "lut_name": dst.get("lut_name"),
            "lut_root": dst_aig.get("lut_root"),
            "coords": dst.get("coords", {}),
            "aig": {
                "leaves": sorted(dst_leaves),
                "func_hex": dst_aig.get("func_hex"),
            },
            "expr_root": dst.get("expr_root"),
        },
        "pitstop": {
            "block": pit.get("block"),
            "lut_name": pit.get("lut_name"),
            "lut_root": pit_aig.get("lut_root"),
            "coords": pit.get("coords", {}),
            "distances": distances,
            "costs": costs,
            "aig": {
                "leaves": sorted(pit_leaves),
                "func_hex": pit_aig.get("func_hex"),
            },
            "expr_root": pit.get("expr_root"),
        },
        "overlaps": {
            "src_pit": overlap_src_pit,
            "dst_pit": overlap_dst_pit,
            "src_dst": overlap_src_dst,
        },
        "connection": {
            "d_ab": conn.get("d_ab"),
        },
    }

    return instance


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Genereer ECO-kandidaten per (src, dst, pitstop) op basis van "
            "<design>.lut_connections_full.json + <design>.lut_cones.json. "
            "Schrijft per kandidaat een klein JSON-instance en logt uitgebreide info."
        )
    )
    ap.add_argument(
        "--connections",
        required=True,
        help="Pad naar <design>.lut_connections_full.json",
    )
    ap.add_argument(
        "--lut-cones",
        required=True,
        help="Pad naar <design>.lut_cones.json (voor meta, sanity-checks).",
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="Output-directory voor ECO-candidate instances (*.eco_instance.json).",
    )
    ap.add_argument(
        "--max-candidates",
        type=int,
        default=0,
        help="Optioneel maximum aantal candidates (0 = geen limiet).",
    )

    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # -----------------------
    # JSON inladen
    # -----------------------
    connections_data = load_json(args.connections)
    lut_cones_data = load_json(args.lut_cones)

    design_name = connections_data.get("design", "unknown_design")
    connections: List[Dict[str, Any]] = connections_data.get("connections", [])
    num_conns = len(connections)
    lut_cones = lut_cones_data.get("lut_cones", [])
    lut_cones_map = {lc.get("lut_name"): lc for lc in lut_cones if lc.get("lut_name")}

    print("========================================")
    print(f"[INFO] ECO candidates generator gestart")
    print(f"[INFO] Design                 : {design_name}")
    print(f"[INFO] # connections          : {num_conns}")
    print(f"[INFO] # LUT-cones in DB      : {len(lut_cones_map)}")
    print(f"[INFO] Output dir             : {args.out_dir}")
    print(f"[INFO] Max candidates (0=all) : {args.max_candidates}")
    print("========================================")

    candidate_count = 0

    for conn_idx, conn in enumerate(connections):
        print(summarize_connection(conn_idx, conn))

        src = conn.get("src", {})
        dst = conn.get("dst", {})
        pitstops = conn.get("pitstops", [])

        src_name = src.get("lut_name") or src.get("block")
        dst_name = dst.get("lut_name") or dst.get("block")

        # sanity check: zitten src/dst in lut_cones_map?
        if src_name not in lut_cones_map:
            print(
                f"  [WARN] src {src_name} niet gevonden in lut_cones_map "
                f"(mogelijk geen echte LUT of mismatch)."
            )
        if dst_name not in lut_cones_map:
            print(
                f"  [WARN] dst {dst_name} niet gevonden in lut_cones_map "
                f"(mogelijk geen echte LUT of mismatch)."
            )

        if not pitstops:
            print("  [INFO] Geen pitstops voor deze verbinding.")
            continue

        for pit_idx, pit in enumerate(pitstops):
            pit_name = pit.get("lut_name") or pit.get("block")
            print(
                f"  [CAND] conn={conn_idx}, pit={pit_idx}, "
                f"src={src_name}, dst={dst_name}, pit={pit_name}"
            )

            pit_aig = pit.get("aig", {}) or {}
            if not pit_aig.get("found", False):
                print("    [WARN] pit.aig.found == False, sla candidate over.")
                continue

            # Leaves & overlap
            src_leaves = as_set_int(leaves_from_aig(src.get("aig", {}) or {}))
            dst_leaves = as_set_int(leaves_from_aig(dst.get("aig", {}) or {}))
            pit_leaves = as_set_int(leaves_from_aig(pit_aig))

            overlap_src_pit = src_leaves & pit_leaves
            overlap_dst_pit = dst_leaves & pit_leaves

            print(f"    [INFO] src_leaves (#={len(src_leaves)}): {sorted(src_leaves)}")
            print(f"    [INFO] dst_leaves (#={len(dst_leaves)}): {sorted(dst_leaves)}")
            print(f"    [INFO] pit_leaves (#={len(pit_leaves)}): {sorted(pit_leaves)}")
            print(
                f"    [INFO] overlap src∩pit (#={len(overlap_src_pit)}): "
                f"{sorted(overlap_src_pit)}"
            )
            print(
                f"    [INFO] overlap dst∩pit (#={len(overlap_dst_pit)}): "
                f"{sorted(overlap_dst_pit)}"
            )

            distances = pit.get("distances", {}) or {}
            costs = pit.get("costs", {}) or {}
            print(f"    [INFO] distances: {distances}")
            print(f"    [INFO] costs    : {costs}")

            # Instance bouwen
            instance = build_candidate_instance(
                design=design_name,
                conn_idx=conn_idx,
                pit_idx=pit_idx,
                conn=conn,
                pit=pit,
            )

            out_name = (
                f"{design_name}.conn{conn_idx:03d}.pit{pit_idx:03d}.eco_instance.json"
            )
            out_path = os.path.join(args.out_dir, out_name)
            with open(out_path, "w") as f_out:
                json.dump(instance, f_out, indent=2)

            print(f"    [OK] instance geschreven → {out_path}")
            candidate_count += 1

            if args.max_candidates > 0 and candidate_count >= args.max_candidates:
                print("========================================")
                print(
                    f"[INFO] Max candidates bereikt ({args.max_candidates}), "
                    "stoppen met verdere enumeratie."
                )
                print("========================================")
                print(f"[INFO] Totaal geschreven instances: {candidate_count}")
                return

    print("========================================")
    print(f"[INFO] ECO candidates generator klaar.")
    print(f"[INFO] Totaal geschreven instances: {candidate_count}")
    print("========================================")


if __name__ == "__main__":
    main()
