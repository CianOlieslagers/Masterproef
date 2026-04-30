# tony_sat/core/test_build_miter.py
from __future__ import annotations
import argparse

from tony_sat.core.blif_parser import parse_blif
from tony_sat.core.miter_blif import build_miter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    ap.add_argument("--pit", required=True, help="pit LUT name, e.g. LUT_22")
    ap.add_argument("--row", required=True, type=int, help="row 0..15")
    args = ap.parse_args()

    design = parse_blif(args.blif)
    cnf, diff = build_miter(design, pit_lut=args.pit, row=args.row)

    print("[INFO] Miter CNF built.")
    print("       var_count:", cnf.var_count)
    print("       clauses:", len(cnf.clauses))
    print("       diff_var:", diff)


if __name__ == "__main__":
    main()
