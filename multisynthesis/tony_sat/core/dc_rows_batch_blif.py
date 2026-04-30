# tony_sat/core/dc_rows_batch_blif.py
from __future__ import annotations
import argparse, json
from typing import Dict, Any, List

from tony_sat.core.dc_blif import classify_row
from tony_sat.core.blif_parser import parse_blif

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    ap.add_argument("--pit", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows: List[Dict[str, Any]] = []
    counts = {"CARE": 0, "DONT_CARE": 0, "UNREACHABLE": 0}



    design = parse_blif(args.blif)
    pit_fanins = None
    for nb in design.names:
        if nb.output == args.pit:
            pit_fanins = nb.fanins
            break
    if pit_fanins is None:
        raise KeyError(f"PIT LUT {args.pit} not found in BLIF")

    k = len(pit_fanins)
    nrows = 1 << k

    for r in range(nrows):
        res = classify_row(args.blif, args.pit, r)
        rows.append({
            "row": r,
            "status": res.status,
            "reachable": res.reachable,
            "observable": res.observable,
        })
        counts[res.status] += 1
        print(f"[ROW {r:2d}] {res.status}")

    out_obj = {
        "blif": args.blif,
        "pit": args.pit,
        "nrows": nrows,
	"k": k,
 	"rows": rows,
        "summary": counts,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_obj, f, indent=2)

    print("\n[INFO] Summary:", counts)
    print("[OK] Wrote", args.out)


if __name__ == "__main__":
    main()
