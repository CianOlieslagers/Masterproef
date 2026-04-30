#!/usr/bin/env python3
import argparse
import json
import sys




#Is een checker script die de TFO en TFI van twee Json bestanden controleert
#Vb command call: python3 ~/Masterproef/multisynthesis/Sim_Sat/Windowing/scripts/check_inner_outer.py 
#--inner ~/Masterproef/multisynthesis/Sim_Sat/Windowing/results/window_120_3_3.json 
#--outer ~/Masterproef/multisynthesis/Sim_Sat/Windowing/results/window_120_5_5.json



def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def as_set(d, key):
    v = d.get(key)
    if not isinstance(v, list):
        raise ValueError(f"{key} ontbreekt of is geen lijst")
    return set(v)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inner", required=True, help="inner window json")
    ap.add_argument("--outer", required=True, help="outer window json")
    args = ap.parse_args()

    inner = load_json(args.inner)
    outer = load_json(args.outer)

    # -------------------------
    # basischecks
    # -------------------------
    if inner["pivot"] != outer["pivot"]:
        print(f"ERROR: pivot mismatch: inner={inner['pivot']} outer={outer['pivot']}")
        sys.exit(1)

    inner_tfi = as_set(inner, "tfi_nodes")
    inner_tfo = as_set(inner, "tfo_nodes")
    inner_pis = as_set(inner, "window_pis")
    inner_pos = as_set(inner, "window_pos")
    inner_marked = as_set(inner, "marked_nodes")
    inner_collected = as_set(inner, "collected_nodes")

    outer_tfi = as_set(outer, "tfi_nodes")
    outer_tfo = as_set(outer, "tfo_nodes")
    outer_pis = as_set(outer, "window_pis")
    outer_pos = as_set(outer, "window_pos")
    outer_marked = as_set(outer, "marked_nodes")
    outer_collected = as_set(outer, "collected_nodes")

    print("[CHECK] inner/outer windows")
    print(f"  pivot              : {inner['pivot']}")
    print(f"  inner levels       : ({inner['tfi_L']}, {inner['tfo_L']})")
    print(f"  outer levels       : ({outer['tfi_L']}, {outer['tfo_L']})")
    print()

    print(f"  |inner tfi|        : {len(inner_tfi)}")
    print(f"  |outer tfi|        : {len(outer_tfi)}")
    print(f"  |inner tfo|        : {len(inner_tfo)}")
    print(f"  |outer tfo|        : {len(outer_tfo)}")
    print(f"  |inner pis| = |s|  : {len(inner_pis)}")
    print(f"  |outer pis|        : {len(outer_pis)}")
    print(f"  |inner pos|        : {len(inner_pos)}")
    print(f"  |outer pos|        : {len(outer_pos)}")
    print(f"  |inner marked|     : {len(inner_marked)}")
    print(f"  |outer marked|     : {len(outer_marked)}")
    print(f"  |inner collected|  : {len(inner_collected)}")
    print(f"  |outer collected|  : {len(outer_collected)}")
    print()

    # -------------------------
    # relation checks
    # -------------------------
    print("[RELATIONS]")

    print(f"  inner_tfi subset outer_tfi        : {inner_tfi.issubset(outer_tfi)}")
    print(f"  inner_tfo subset outer_tfo        : {inner_tfo.issubset(outer_tfo)}")
    print(f"  inner_marked subset outer_marked  : {inner_marked.issubset(outer_marked)}")
    print(f"  inner_collected subset outer_collected : {inner_collected.issubset(outer_collected)}")

    # s-space info
    s = sorted(inner_pis)
    print()
    print("[CARE-SPACE]")
    print(f"  s (= inner.window_pis) size : {len(s)}")
    print(f"  s values                    : {s}")

    if len(s) > 10:
        print("  WARNING: |s| > 10, SAT/all-SAT may become heavier.")
    else:
        print("  OK: |s| is small enough to be practical.")

    # extra monotonic sanity
    print()
    print("[SANITY]")
    print(f"  outer tfi >= inner tfi      : {len(outer_tfi) >= len(inner_tfi)}")
    print(f"  outer tfo >= inner tfo      : {len(outer_tfo) >= len(inner_tfo)}")

if __name__ == "__main__":
    main()
