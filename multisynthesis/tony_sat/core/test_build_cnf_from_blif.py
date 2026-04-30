# tony_sat/core/test_build_cnf_from_blif.py
from __future__ import annotations
import argparse

from tony_sat.core.blif_parser import parse_blif, summarize
from tony_sat.core.blif_to_cnf import build_cnf_from_blif


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    args = ap.parse_args()

    design = parse_blif(args.blif)
    print("[INFO] BLIF summary:", summarize(design))

    circ = build_cnf_from_blif(design)

    # CNFBuilder API verschilt soms; probeer common fields.
    cnf = circ.cnf
    n_vars = getattr(cnf, "num_vars", None) or getattr(cnf, "n_vars", None)
    n_clauses = getattr(cnf, "num_clauses", None) or getattr(cnf, "n_clauses", None)

    print("[INFO] CNF built.")
    print("       nets:", len(circ.net2var))
    print("       outputs:", circ.outputs)
    if n_vars is not None:
        print("       vars:", n_vars)
    if n_clauses is not None:
        print("       clauses:", n_clauses)


if __name__ == "__main__":
    main()
