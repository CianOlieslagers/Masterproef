#!/usr/bin/env python3
import argparse
import json
import itertools
from pathlib import Path


#Bestand voor de output json voor de care sett
#Command call is 
#Build_care_space_json.py Inner.json - Outer.json - Output.json

def load_json(path: str):
    with open(path, "r") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inner", required=True, help="inner window json")
    ap.add_argument("--outer", required=True, help="outer window json")
    ap.add_argument("--out", required=True, help="output care space json")
    args = ap.parse_args()

    inner = load_json(args.inner)
    outer = load_json(args.outer)

    # -------------------------
    # basischecks
    # -------------------------
    if inner.get("pivot") != outer.get("pivot"):
        raise ValueError(
            f"Pivot mismatch: inner={inner.get('pivot')} outer={outer.get('pivot')}"
        )

    s = inner.get("window_pis")
    if not isinstance(s, list):
        raise ValueError("inner json mist geldige 'window_pis' lijst")

    # vaste volgorde
    s = list(s)
    num_s_vars = len(s)

    # alle assignments in lexicografische bitstring-volgorde
    all_s_assignments = [
        "".join(bits)
        for bits in itertools.product("01", repeat=num_s_vars)
    ]

    out_data = {
        "pivot": inner["pivot"],
        "inner_window_json": str(Path(args.inner).resolve()),
        "outer_window_json": str(Path(args.outer).resolve()),
        "inner_levels": {
            "tfi_L": inner["tfi_L"],
            "tfo_L": inner["tfo_L"],
        },
        "outer_levels": {
            "tfi_L": outer["tfi_L"],
            "tfo_L": outer["tfo_L"],
        },
        "s": s,
        "num_s_vars": num_s_vars,
        "num_all_s_assignments": len(all_s_assignments),
        "all_s_assignments": all_s_assignments,
        "care_minterms_sim": [],
        "care_minterms_sat": [],
        "care_minterms_total": []
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2)

    print(f"[OK] care space json geschreven naar: {out_path}")
    print(f"  pivot               : {out_data['pivot']}")
    print(f"  |s|                 : {num_s_vars}")
    print(f"  #all_s_assignments  : {len(all_s_assignments)}")


if __name__ == "__main__":
    main()
