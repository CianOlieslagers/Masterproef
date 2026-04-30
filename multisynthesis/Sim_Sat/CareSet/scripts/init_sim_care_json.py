#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

#Script voor start basis Care sett te berekenen
#Command call
#Python 3 init_sim_care_json.py --care-space "Insert volledige care space" --out "Insert output json"

def load_json(path: str):
    with open(path, "r") as f:
        return json.load(f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--care-space", required=True, help="input care space json")
    ap.add_argument("--out", required=True, help="output simulation care json")
    args = ap.parse_args()

    data = load_json(args.care_space)

    assignments = data.get("all_s_assignments")
    if not isinstance(assignments, list):
        raise ValueError("care-space json mist geldige 'all_s_assignments' lijst")

    out_data = dict(data)
    out_data["care_eval"] = {
        "method": "simulation_stub",
        "evaluated_assignments": len(assignments)
    }
    out_data["care_flags"] = [
        {
            "s_bits": bits,
            "is_care": False
        }
        for bits in assignments
    ]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2)

    print(f"[OK] simulation care json geschreven naar: {out_path}")
    print(f"  assignments: {len(assignments)}")

if __name__ == "__main__":
    main()
