#!/usr/bin/env python3
import json
import argparse
import re
from typing import Dict, Any, Optional


# ----------------------------
# Helpers: namen → LUT-namen
# ----------------------------

def net_to_lut_name(net_name: str) -> Optional[str]:
    """
    Probeer een net/blocknaam om te zetten naar een LUT-naam 'LUT_<nr>'.

    Ondersteunt:
      - 'LUT_11'     -> 'LUT_11'
      - 'new_n11'    -> 'LUT_11'
    Alles wat niet lijkt op een LUT-output wordt genegeerd (None).
    """
    if not isinstance(net_name, str):
        return None

    # Reeds een LUT-naam
    m = re.fullmatch(r"LUT_(\d+)", net_name)
    if m:
        return net_name

    # BLIF-intermediair net: new_n<nr>
    m = re.fullmatch(r"new_n(\d+)", net_name)
    if m:
        return f"LUT_{m.group(1)}"

    # Eventueel later uitbreiden met extra patterns (bv. 'n42', 'block_42', ...)
    return None


# ----------------------------
# LUT-cones inlezen
# ----------------------------

def load_lut_cones(lut_cones_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Leest <design>.lut_cones.json en bouwt:
      lut_cones_map["LUT_11"] = {
        "lut_root": <int>,
        "leaves": [int,...],
        "internal_nodes": [int,...],
        "func_hex": "<hex>",
        "node_functions": [...]
      }
    """
    with open(lut_cones_path, "r") as f:
        data = json.load(f)

    lut_cones = data.get("lut_cones", [])
    lut_map: Dict[str, Dict[str, Any]] = {}

    for cone in lut_cones:
        lut_name = cone.get("lut_name")
        if not lut_name:
            continue

        lut_map[lut_name] = {
            "lut_root": cone.get("lut_root"),
            "leaves": cone.get("leaves", []),
            "internal_nodes": cone.get("internal_nodes", []),
            "func_hex": cone.get("func_hex"),
            "node_functions": cone.get("node_functions", []),
        }

    print(f"[INFO] LUT-cones geladen: {len(lut_map)} LUTs")
    return lut_map


def lookup_lut_aig(lut_name: Optional[str],
                   lut_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Geef AIG-info terug voor een LUT-naam, of een 'found: false'-struct als er
    geen match is.
    """
    if lut_name is None:
        return {
            "found": False,
            "lut_name": None,
            "lut_root": None,
            "leaves": [],
            "internal_nodes": [],
            "func_hex": None,
            "node_functions": []
        }

    info = lut_map.get(lut_name)
    if info is None:
        return {
            "found": False,
            "lut_name": lut_name,
            "lut_root": None,
            "leaves": [],
            "internal_nodes": [],
            "func_hex": None,
            "node_functions": []
        }

    return {
        "found": True,
        "lut_name": lut_name,
        "lut_root": info.get("lut_root"),
        "leaves": info.get("leaves", []),
        "internal_nodes": info.get("internal_nodes", []),
        "func_hex": info.get("func_hex"),
        "node_functions": info.get("node_functions", []),
    }


# ----------------------------
# LUT-boolean expressies inlezen
# ----------------------------

def load_lut_bool_exprs(lut_bool_path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """
    Leest <design>.lutBooleanExp.json en bouwt:
      lut_exprs["LUT_11"] = volledige entry voor die LUT.

    We gaan er van uit dat de structuur ongeveer is:

      {
        "format": "lut_boolean_expressions:v1",
        "design": "...",
        "luts": [
          {
            "lut_name": "LUT_11",
            "root_node": 11,
            "expr_root": "...",
            "node_exprs": { "11": "...", "7": "...", ... }
          },
          ...
        ]
      }

    Als de sleutel voor de root-expressie bv. 'root_expr' of 'expression'
    heet, is dat ook oké: dat handelen we later af.
    """
    if not lut_bool_path:
        return {}

    with open(lut_bool_path, "r") as f:
        data = json.load(f)

    lut_exprs: Dict[str, Dict[str, Any]] = {}
    for entry in data.get("luts", []):
        name = entry.get("lut_name")
        if not name:
            continue
        lut_exprs[name] = entry

    print(f"[INFO] LUT-boolean expressies geladen: {len(lut_exprs)} LUTs")
    return lut_exprs


def get_root_expr_for_lut(lut_name: Optional[str],
                          lut_exprs: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """
    Geef de booleaanse expressie van de LUT-root terug (als string), of None.
    We zijn wat tolerant in veldnamen: expr_root, root_expr, expression, expr.
    """
    if not lut_name:
        return None
    if lut_name not in lut_exprs:
        return None

    entry = lut_exprs[lut_name]
    return (
        entry.get("expr_root")
        or entry.get("root_expr")
        or entry.get("expression")
        or entry.get("expr")
    )


# ----------------------------
# mid_luts + manhattan samenvoegen
# ----------------------------

def build_connections(
    mid_luts_path: str,
    lut_cones_path: str,
    manhattan_path: Optional[str] = None,
    lut_bool_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Bouw één grote JSON-structuur:
      {
        "design": ...,
        "connections": [
          {
            "src": {
              "block": ...,
              "lut_name": ...,
              "coords": {...},
              "aig": {...},
              "expr_root": "<boolean expression>"   # NIEUW
            },
            "dst": {...},
            "d_ab": <manhattan>,
            "pitstops": [
              {
                "block": ...,
                "lut_name": ...,
                "coords": {...},
                "distances": {...},
                "costs": {...},
                "aig": {...},
                "expr_root": "<boolean expression>" # NIEUW
              },
              ...
            ]
          },
          ...
        ]
      }
    """

    # mid_luts.json
    with open(mid_luts_path, "r") as f:
        mid_data = json.load(f)

    if not isinstance(mid_data, list):
        raise ValueError(f"{mid_luts_path} verwacht een lijst, kreeg: {type(mid_data)}")

    # lut_cones.json
    lut_map = load_lut_cones(lut_cones_path)

    # LUT-boolean expressies (optioneel)
    lut_exprs = load_lut_bool_exprs(lut_bool_path)

    # optioneel manhattan.json (bv. voor designnaam of extra checks)
    design_name = None
    if manhattan_path:
        with open(manhattan_path, "r") as f:
            manh = json.load(f)
        design_name = manh.get("design")
        print(f"[INFO] Manhattan JSON geladen, design={design_name}")

    connections_out = []

    for idx, entry in enumerate(mid_data):
        raw_src = entry.get("src", "")
        raw_dst = entry.get("dst", "")

        src_lut_name = net_to_lut_name(raw_src)
        dst_lut_name = net_to_lut_name(raw_dst)

        if src_lut_name is None or dst_lut_name is None:
            print(f"[WARN] Entry {idx}: src/dst niet naar LUT_naam te mappen "
                  f"(src='{raw_src}', dst='{raw_dst}'), sla entry toch op maar zonder AIG-info.")

        src_aig = lookup_lut_aig(src_lut_name, lut_map)
        dst_aig = lookup_lut_aig(dst_lut_name, lut_map)

        src_coords = entry.get("src_coords", {})
        dst_coords = entry.get("dst_coords", {})
        d_ab = entry.get("d_ab", None)

        # Booleaanse expressies (root van de LUT)
        src_expr = get_root_expr_for_lut(src_lut_name, lut_exprs)
        dst_expr = get_root_expr_for_lut(dst_lut_name, lut_exprs)

        conn_obj = {
            "src": {
                "block": raw_src,             # naam zoals in mid_luts.json
                "lut_name": src_lut_name,     # bv. "LUT_11"
                "coords": src_coords,         # {"x":.., "y":..}
                "aig": src_aig,
                "expr_root": src_expr,        # NIEUW: booleaanse expressie als string (of None)
            },
            "dst": {
                "block": raw_dst,
                "lut_name": dst_lut_name,
                "coords": dst_coords,
                "aig": dst_aig,
                "expr_root": dst_expr,        # NIEUW
            },
            "d_ab": d_ab,
            "pitstops": []
        }

        midpoints = entry.get("midpoints", [])
        for mp in midpoints:
            raw_mid = mp.get("mid", "")
            mid_lut_name = net_to_lut_name(raw_mid)
            mid_aig = lookup_lut_aig(mid_lut_name, lut_map)
            mid_expr = get_root_expr_for_lut(mid_lut_name, lut_exprs)

            pit_obj = {
                "block": raw_mid,          # originele block/netnaam
                "lut_name": mid_lut_name,  # "LUT_xx" of None
                "coords": mp.get("coords", {}),
                "distances": mp.get("distances", {}),
                "costs": mp.get("costs", {}),
                "aig": mid_aig,
                "expr_root": mid_expr,     # NIEUW
            }
            conn_obj["pitstops"].append(pit_obj)

        connections_out.append(conn_obj)

    result = {
        "design": design_name,
        "num_connections": len(connections_out),
        "connections": connections_out,
    }
    return result


# ----------------------------
# main
# ----------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Combineer manhattan + mid_luts + lut_cones tot één JSON met AIG-info per src/dst/pitstop + optioneel booleaanse expressies."
    )
    ap.add_argument("--mid-luts", required=True,
                    help="Pad naar <design>.mid_luts.json")
    ap.add_argument("--lut-cones", required=True,
                    help="Pad naar <design>.lut_cones.json")
    ap.add_argument("--manhattan", required=False,
                    help="Optioneel: pad naar <design>.manhattan.json (voor meta-info)")
    ap.add_argument("--lut-bool-exp", required=False,
                    help="Optioneel: pad naar <design>.lutBooleanExp.json (booleaanse expressies per LUT)")
    ap.add_argument("--out", required=True,
                    help="Output JSON-bestand")

    args = ap.parse_args()

    combined = build_connections(
        mid_luts_path=args.mid_luts,
        lut_cones_path=args.lut_cones,
        manhattan_path=args.manhattan,
        lut_bool_path=args.lut_bool_exp,
    )

    with open(args.out, "w") as f:
        json.dump(combined, f, indent=2)

    print(f"[OK] Gecombineerde JSON geschreven naar: {args.out}")
    print(f"     Aantal src-dst-paren: {combined['num_connections']}")


if __name__ == "__main__":
    main()
