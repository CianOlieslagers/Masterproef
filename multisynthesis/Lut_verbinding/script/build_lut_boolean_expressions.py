#!/usr/bin/env python3
import json
import argparse
from typing import List, Dict, Any

# -----------------------------
# Helpers
# -----------------------------

def hex_to_bits(func_hex: str, num_vars: int) -> List[int]:
    """
    Zet func_hex (bv. '8777') om naar een bitlijst van lengte 2^num_vars.

    We nemen de conventie:
      - bit i hoort bij input assignment i
      - i in binair -> bits per variabele:
          var j heeft waarde (i >> j) & 1
    """
    total_bits = 1 << num_vars
    val = int(func_hex, 16)

    bits = []
    for i in range(total_bits):
        bits.append((val >> i) & 1)
    return bits


def make_var_names(leaves: List[int]) -> Dict[int, str]:
    """
    Maak leesbare variabelenamen voor de leaves.

    bv. leaves = [1, 2, 3, 4] ->
        {1: 'a', 2: 'b', 3: 'c', 4: 'd'}
    """
    letters = "abcdefghijklmnopqrstuvwxyz"
    name_map: Dict[int, str] = {}

    for idx, leaf_id in enumerate(leaves):
        if idx < len(letters):
            name_map[leaf_id] = letters[idx]
        else:
            # fallback: leaf_123
            name_map[leaf_id] = f"leaf_{leaf_id}"
    return name_map


def build_dnf_expression(func_hex: str, leaves: List[int]) -> Dict[str, Any]:
    """
    Bouw een DNF-expressie voor één LUT op basis van func_hex en leaves.

    Returnt:
      {
        "var_names": { leaf_id: "a", ... },
        "expression": "<string>"
      }
    """
    num_vars = len(leaves)
    if num_vars == 0:
        # Degeneratief geval (zou niet moeten gebeuren)
        return {
            "var_names": {},
            "expression": "0"
        }

    bits = hex_to_bits(func_hex, num_vars)
    var_names = make_var_names(leaves)

    # Mintermen verzamelen (rijen waar output = 1)
    terms: List[str] = []
    total_bits = 1 << num_vars

    for i in range(total_bits):
        if bits[i] == 0:
            continue

        # bouw één minterm:
        # voor elke variabele j (0..num_vars-1):
        #   waarde = (i >> j) & 1
        #   literal = v_j ? var_j : ~var_j
        literals = []
        for j in range(num_vars):
            val = (i >> j) & 1
            leaf_id = leaves[j]
            vname = var_names[leaf_id]
            if val == 1:
                literals.append(vname)
            else:
                literals.append(f"~{vname}")

        # combineer met AND
        if len(literals) == 1:
            term_str = literals[0]
        else:
            term_str = "(" + " & ".join(literals) + ")"

        terms.append(term_str)

    # Geen enkele 1 → constante 0
    if not terms:
        expr = "0"
    # Alles is 1 → constante 1
    elif len(terms) == (1 << num_vars) and len(set(bits)) == 1:
        expr = "1"
    # Anders OR van alle mintermen
    else:
        if len(terms) == 1:
            expr = terms[0]
        else:
            expr = " | ".join(terms)

    return {
        "var_names": var_names,
        "expression": expr
    }


# -----------------------------
# Hoofdlogica
# -----------------------------

def build_lut_expressions(lut_cones_path: str) -> Dict[str, Any]:
    """
    Leest example_big_300.lut_cones.json en bouwt een nieuwe JSON:

    {
      "format": "lut_boolean_expressions:v1",
      "circuit": "...",
      "K": ...,
      "luts": [
        {
          "lut_name": "LUT_11",
          "lut_root": 11,
          "leaves": [1,2,3,4],
          "func_hex": "8777",
          "var_names": { "1":"a", "2":"b", ... },
          "expression": "(~a & ~b & ~c & ~d) | ..."
        },
        ...
      ]
    }
    """
    with open(lut_cones_path, "r") as f:
        data = json.load(f)

    lut_cones = data.get("lut_cones", [])
    circuit = data.get("circuit")
    K = data.get("K")

    out_luts = []

    for cone in lut_cones:
        lut_name = cone.get("lut_name")
        lut_root = cone.get("lut_root")
        func_hex = cone.get("func_hex")
        leaves = cone.get("leaves", [])

        if not lut_name or func_hex is None or not leaves:
            # sla rare / incomplete entries over
            continue

        expr_info = build_dnf_expression(func_hex, leaves)

        out_luts.append({
            "lut_name": lut_name,
            "lut_root": lut_root,
            "leaves": leaves,
            "func_hex": func_hex,
            "var_names": {str(k): v for k, v in expr_info["var_names"].items()},
            "expression": expr_info["expression"]
        })

    result = {
        "format": "lut_boolean_expressions:v1",
        "circuit": circuit,
        "K": K,
        "num_luts": len(out_luts),
        "luts": out_luts
    }
    return result


def main():
    ap = argparse.ArgumentParser(
        description="Genereer Booleaanse expressies (DNF) voor elke LUT uit mt_lut_cones JSON."
    )
    ap.add_argument(
        "--lut-cones",
        required=True,
        help="Pad naar example_big_300.lut_cones.json (mt_lut_cones output)"
    )
    ap.add_argument(
        "--out",
        required=True,
        help="Output JSON bestand met Booleaanse expressies"
    )

    args = ap.parse_args()

    res = build_lut_expressions(args.lut_cones)

    with open(args.out, "w") as f:
        json.dump(res, f, indent=2)

    print(f"[OK] LUT-expressies geschreven naar: {args.out}")
    print(f"     Aantal LUTs: {res['num_luts']}")


if __name__ == "__main__":
    main()
