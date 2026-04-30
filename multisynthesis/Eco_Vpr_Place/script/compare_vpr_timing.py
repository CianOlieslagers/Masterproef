#!/usr/bin/env python3
import argparse
import re
from pathlib import Path


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def extract_global_from_log(path):
    txt = read_text(path)

    cpd = None
    fmax = None
    swns = None
    stns = None

    m = re.search(r"Final critical path delay \(least slack\):\s+([0-9.]+)\s+ns,\s+Fmax:\s+([0-9.]+)\s+MHz", txt)
    if m:
        cpd = float(m.group(1))
        fmax = float(m.group(2))

    m = re.search(r"Final setup Worst Negative Slack \(sWNS\):\s+(-?[0-9.]+)\s+ns", txt)
    if m:
        swns = float(m.group(1))

    m = re.search(r"Final setup Total Negative Slack \(sTNS\):\s+(-?[0-9.]+)\s+ns", txt)
    if m:
        stns = float(m.group(1))

    return {
        "cpd_ns": cpd,
        "fmax_mhz": fmax,
        "swns_ns": swns,
        "stns_ns": stns,
    }


def extract_timing_rows(path):
    rows = []
    txt = read_text(path)

    # Lines look like:
    # LUT_97.out[0] (.names)                                           0.225     1.206
    pattern = re.compile(r"^\s*(\S.*?\))\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s*$")

    for line in txt.splitlines():
        m = pattern.match(line)
        if not m:
            continue

        node = m.group(1).strip()
        incr = float(m.group(2))
        arrival = float(m.group(3))
        rows.append({
            "node": node,
            "incr_ns": incr,
            "arrival_ns": arrival,
        })

    return rows


def print_path(title, rows):
    print(f"\n==== {title} ====")
    if not rows:
        print("Geen timing path rows gevonden.")
        return

    for r in rows:
        print(f"{r['node']:<70} incr={r['incr_ns']:>8.3f} ns   arrival={r['arrival_ns']:>8.3f} ns")


def find_rows_containing(rows, terms):
    return [r for r in rows if any(t in r["node"] for t in terms)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-log", required=True)
    ap.add_argument("--patched-log", required=True)
    ap.add_argument("--baseline-rpt", required=True)
    ap.add_argument("--patched-rpt", required=True)
    ap.add_argument("--source", default="LUT_97")
    ap.add_argument("--sink", default="LUT_101")
    ap.add_argument("--eco", default="ECO_BUF_LUT_97_TO_LUT_101")
    args = ap.parse_args()

    base = extract_global_from_log(args.baseline_log)
    patch = extract_global_from_log(args.patched_log)

    print("==== GLOBAL TIMING COMPARISON ====")
    print(f"Baseline CPD : {base['cpd_ns']} ns")
    print(f"Patched CPD  : {patch['cpd_ns']} ns")

    if base["cpd_ns"] is not None and patch["cpd_ns"] is not None:
        delta = patch["cpd_ns"] - base["cpd_ns"]
        pct = 100.0 * delta / base["cpd_ns"]
        print(f"Delta CPD    : {delta:+.5f} ns ({pct:+.2f}%)")

    print()
    print(f"Baseline Fmax: {base['fmax_mhz']} MHz")
    print(f"Patched Fmax : {patch['fmax_mhz']} MHz")

    if base["fmax_mhz"] is not None and patch["fmax_mhz"] is not None:
        delta_f = patch["fmax_mhz"] - base["fmax_mhz"]
        pct_f = 100.0 * delta_f / base["fmax_mhz"]
        print(f"Delta Fmax   : {delta_f:+.3f} MHz ({pct_f:+.2f}%)")

    print()
    print(f"Baseline sWNS: {base['swns_ns']} ns")
    print(f"Patched sWNS : {patch['swns_ns']} ns")

    base_rows = extract_timing_rows(args.baseline_rpt)
    patch_rows = extract_timing_rows(args.patched_rpt)

    print_path("BASELINE REPORTED SETUP PATH", base_rows)
    print_path("PATCHED REPORTED SETUP PATH", patch_rows)

    terms = [args.source, args.sink, args.eco]

    base_hits = find_rows_containing(base_rows, terms)
    patch_hits = find_rows_containing(patch_rows, terms)

    print_path("BASELINE ROWS CONTAINING ECO TERMS", base_hits)
    print_path("PATCHED ROWS CONTAINING ECO TERMS", patch_hits)

    # Try local ECO segment computation from patched path.
    names = [r["node"] for r in patch_rows]

    def find_exact_node(rows, block, pin_kind):
    """
    Zoekt exact naar bv:
      LUT_97.out[0]
      ECO_BUF_LUT_97_TO_LUT_101.in[0]
      LUT_101.in[3]

    Niet met substring matching, want ECO_BUF_LUT_97_TO_LUT_101 bevat ook LUT_101.
    """
    prefix = block + "." + pin_kind

    for r in rows:
        node = r["node"].split()[0]  # bv. LUT_101.in[3]
        if node.startswith(prefix + "["):
            return r

    return None
    src_out = find_exact_node(patch_rows, args.source, "out")
    eco_in = find_exact_node(patch_rows, args.eco, "in")
    eco_out = find_exact_node(patch_rows, args.eco, "out")
    sink_in = find_exact_node(patch_rows, args.sink, "in")
    print("\n==== PATCHED LOCAL ECO DELAY ====")

    if src_out and eco_in and eco_out and sink_in:
        src_to_eco_wire = eco_in["arrival_ns"] - src_out["arrival_ns"]
        eco_lut = eco_out["arrival_ns"] - eco_in["arrival_ns"]
        eco_to_sink_wire = sink_in["arrival_ns"] - eco_out["arrival_ns"]
        total = sink_in["arrival_ns"] - src_out["arrival_ns"]

        print(f"{args.source}.out -> {args.eco}.in       : {src_to_eco_wire:.3f} ns")
        print(f"{args.eco}.in -> {args.eco}.out          : {eco_lut:.3f} ns")
        print(f"{args.eco}.out -> {args.sink}.in         : {eco_to_sink_wire:.3f} ns")
        print(f"TOTAL {args.source}.out -> {args.sink}.in via ECO: {total:.3f} ns")
    else:
        print("Kon lokale ECO-delay niet automatisch berekenen uit patched report.")


if __name__ == "__main__":
    main()
