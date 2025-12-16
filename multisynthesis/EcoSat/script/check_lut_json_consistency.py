#!/usr/bin/env python3
import json
import argparse
import os
from typing import Any, Dict, List, Set


def normalize_hex(h: Any) -> str:
    """Zet func_hex in een genormaliseerde vorm (lowercase, zonder '0x')."""
    if h is None:
        return None
    s = str(h).strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return s


def load_json(path: str) -> Any:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"[FATAL] JSON-bestand niet gevonden: {path}")
    with open(path, "r") as f:
        return json.load(f)


def as_set(xs: List[Any]) -> Set[int]:
    return {int(x) for x in xs}


def build_lut_cones_map(lut_cones_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Maak een map:
      lut_map["LUT_11"] = {
        "lut_root": int,
        "leaves": set(int),
        "internal_nodes": set(int),
        "func_hex": str (genormaliseerd)
      }
    """
    lut_cones = lut_cones_data.get("lut_cones", [])
    lut_map: Dict[str, Dict[str, Any]] = {}

    for cone in lut_cones:
        name = cone.get("lut_name")
        if not name:
            continue

        lut_root = cone.get("lut_root")
        leaves = as_set(cone.get("leaves", []))
        internals = as_set(cone.get("internal_nodes", []))
        func_hex = normalize_hex(cone.get("func_hex"))

        lut_map[name] = {
            "lut_root": int(lut_root) if lut_root is not None else None,
            "leaves": leaves,
            "internal_nodes": internals,
            "func_hex": func_hex,
        }

    print(f"[INFO] LUT-cones geladen: {len(lut_map)} LUTs in lut_cones.json")
    return lut_map


def extract_aig_view(aig_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pak uit een 'aig'-object de velden die we willen vergelijken.
    We gaan er van uit dat in lut_connections_full.json de structuur is:
      "aig": {
        "found": true,
        "lut_name": "LUT_xx",
        "lut_root": 11,
        "leaves": [...],
        "internal_nodes": [...],
        "func_hex": "...",
        "node_functions": [ ... ]
      }
    """
    if not isinstance(aig_obj, dict):
        return {
            "lut_root": None,
            "leaves": set(),
            "internal_nodes": set(),
            "func_hex": None,
        }

    lut_root = aig_obj.get("lut_root")
    leaves = as_set(aig_obj.get("leaves", []))
    internals = as_set(aig_obj.get("internal_nodes", []))
    func_hex = normalize_hex(aig_obj.get("func_hex"))

    return {
        "lut_root": int(lut_root) if lut_root is not None else None,
        "leaves": leaves,
        "internal_nodes": internals,
        "func_hex": func_hex,
    }


def check_lut_against_cones(
    kind: str,
    lut_name: str,
    aig_view: Dict[str, Any],
    lut_cones_map: Dict[str, Dict[str, Any]],
    conn_idx: int,
    pit_idx: int = None,
) -> bool:
    """
    Vergelijk één LUT (src/dst/pit) uit lut_connections_full.json met lut_cones.json.

    kind    : "src" / "dst" / "pit"
    lut_name: bv. "LUT_11"
    aig_view: uit extract_aig_view()
    conn_idx: index van de connection (voor logging)
    pit_idx : index van de pitstop (alleen voor pitstops; anders None)

    Return: True als alles consistent is, False bij mismatch.
    """
    loc = f"conn={conn_idx}"
    if pit_idx is not None:
        loc += f", pit={pit_idx}"
    loc += f", {kind}={lut_name}"

    if not lut_name:
        print(f"[WARN] {loc}: geen lut_name, sla vergelijking over.")
        return False

    cone_entry = lut_cones_map.get(lut_name)
    if cone_entry is None:
        print(f"[ERROR] {loc}: lut_name niet aanwezig in lut_cones.json")
        return False

    ok = True

    # Vergelijk lut_root
    cone_root = cone_entry["lut_root"]
    conn_root = aig_view["lut_root"]
    if cone_root != conn_root:
        print(
            f"[MISMATCH] {loc}: lut_root verschilt "
            f"(lut_cones={cone_root}, connections={conn_root})"
        )
        ok = False

    # Vergelijk leaves
    cone_leaves = cone_entry["leaves"]
    conn_leaves = aig_view["leaves"]
    if cone_leaves != conn_leaves:
        print(
            f"[MISMATCH] {loc}: leaves verschillen\n"
            f"    lut_cones : {sorted(cone_leaves)}\n"
            f"    connections: {sorted(conn_leaves)}"
        )
        ok = False

    # Vergelijk internal_nodes
    cone_int = cone_entry["internal_nodes"]
    conn_int = aig_view["internal_nodes"]
    if cone_int != conn_int:
        print(
            f"[MISMATCH] {loc}: internal_nodes verschillen\n"
            f"    lut_cones : {sorted(cone_int)}\n"
            f"    connections: {sorted(conn_int)}"
        )
        ok = False

    # Vergelijk func_hex
    cone_hex = cone_entry["func_hex"]
    conn_hex = aig_view["func_hex"]
    if cone_hex != conn_hex:
        print(
            f"[MISMATCH] {loc}: func_hex verschilt "
            f"(lut_cones={cone_hex}, connections={conn_hex})"
        )
        ok = False

    if ok:
        print(f"[OK] {loc}: lut_root + leaves + internals + func_hex zijn consistent.")
    return ok


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Check consistency tussen <design>.lut_cones.json en "
            "<design>.lut_connections_full.json voor alle src/dst/pitstop LUTs."
        )
    )
    ap.add_argument(
        "--lut-cones",
        required=True,
        help="Pad naar <design>.lut_cones.json",
    )
    ap.add_argument(
        "--connections",
        required=True,
        help="Pad naar <design>.lut_connections_full.json",
    )

    args = ap.parse_args()

    lut_cones_data = load_json(args.lut_cones)
    connections_data = load_json(args.connections)

    design_name = connections_data.get("design", "unknown_design")
    connections = connections_data.get("connections", [])

    print("========================================")
    print("[INFO] LUT JSON consistency check gestart")
    print(f"[INFO] Design          : {design_name}")
    print(f"[INFO] lut_cones.json  : {args.lut_cones}")
    print(f"[INFO] connections.json: {args.connections}")
    print("========================================")

    lut_cones_map = build_lut_cones_map(lut_cones_data)

    total_luts_checked = 0
    total_ok = 0
    total_mismatch = 0

    for conn_idx, conn in enumerate(connections):
        print("----------------------------------------")
        src = conn.get("src", {})
        dst = conn.get("dst", {})
        pitstops = conn.get("pitstops", [])

        src_name = src.get("lut_name") or src.get("block")
        dst_name = dst.get("lut_name") or dst.get("block")

        print(
            f"[CONN {conn_idx}] src={src_name}, "
            f"dst={dst_name}, d_ab={conn.get('d_ab')}, "
            f"#pitstops={len(pitstops)}"
        )

        # SRC
        if src.get("aig"):
            aig_view_src = extract_aig_view(src["aig"])
            total_luts_checked += 1
            if check_lut_against_cones(
                kind="src",
                lut_name=src_name,
                aig_view=aig_view_src,
                lut_cones_map=lut_cones_map,
                conn_idx=conn_idx,
            ):
                total_ok += 1
            else:
                total_mismatch += 1
        else:
            print(f"  [WARN] conn={conn_idx}: src.aig ontbreekt, sla over.")

        # DST
        if dst.get("aig"):
            aig_view_dst = extract_aig_view(dst["aig"])
            total_luts_checked += 1
            if check_lut_against_cones(
                kind="dst",
                lut_name=dst_name,
                aig_view=aig_view_dst,
                lut_cones_map=lut_cones_map,
                conn_idx=conn_idx,
            ):
                total_ok += 1
            else:
                total_mismatch += 1
        else:
            print(f"  [WARN] conn={conn_idx}: dst.aig ontbreekt, sla over.")

        # PITSTOPS
        for pit_idx, pit in enumerate(pitstops):
            pit_name = pit.get("lut_name") or pit.get("block") or f"pit_{pit_idx}"
            if not pit.get("aig"):
                print(
                    f"  [WARN] conn={conn_idx}, pit={pit_idx}: pit.aig ontbreekt, sla over."
                )
                continue

            aig_view_pit = extract_aig_view(pit["aig"])
            total_luts_checked += 1
            if check_lut_against_cones(
                kind="pit",
                lut_name=pit_name,
                aig_view=aig_view_pit,
                lut_cones_map=lut_cones_map,
                conn_idx=conn_idx,
                pit_idx=pit_idx,
            ):
                total_ok += 1
            else:
                total_mismatch += 1

    print("========================================")
    print("[INFO] LUT JSON consistency check klaar.")
    print(f"[INFO] Totaal LUTs gecontroleerd : {total_luts_checked}")
    print(f"[INFO]   -> OK                   : {total_ok}")
    print(f"[INFO]   -> Mismatches           : {total_mismatch}")
    if total_mismatch == 0:
        print("[INFO] RESULTAAT: ALLE LUTs zijn consistent tussen lut_cones en connections.")
        print(
            "[INFO] Dit betekent dat al je JSON vanuit één consistente AIG komt "
            "en je veilig diezelfde AIG naar ABC kunt voeren."
        )
    else:
        print(
            "[WARN] RESULTAAT: Er zijn mismatches gevonden. "
            "Dit betekent dat er ergens een verschil zit tussen de AIG die "
            "mt_lut_cones gebruikte en de AIG-info in lut_connections_full.json."
        )
    print("========================================")


if __name__ == "__main__":
    main()
