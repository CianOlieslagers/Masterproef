#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Set


def load_json(p: Path) -> Any:
    return json.loads(p.read_text())


def pit_inputs_set(super_data: Dict[str, Any], pit_key: str) -> Set[str]:
    pit = super_data["luts"][pit_key]
    netlist = pit.get("netlist", {}) or {}
    pins = netlist.get("lut_inputs_ordered", []) or []
    return set(str(x) for x in pins)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--super", required=True, help="super json path")
    ap.add_argument("--targets", required=True, help="targets_per_combo.json path")
    ap.add_argument("--out", required=True, help="output filtered targets json")
    ap.add_argument("--drop-if-empty", action="store_true", help="remove combos that end up with 0 targets")
    args = ap.parse_args()

    super_p = Path(args.super)
    targets_p = Path(args.targets)
    out_p = Path(args.out)

    super_data = load_json(super_p)
    tdata = load_json(targets_p)

    # We ondersteunen 2 vormen:
    #  1) {"combos":[ {...}, {...} ]}
    #  2) {"results":[ {...}, {...} ]}
    #  3) direct lijst
    combos: List[Dict[str, Any]]
    if isinstance(tdata, dict) and isinstance(tdata.get("combos"), list):
        combos = tdata["combos"]
        top_key = "combos"
    elif isinstance(tdata, dict) and isinstance(tdata.get("results"), list):
        combos = tdata["results"]
        top_key = "results"
    elif isinstance(tdata, list):
        combos = tdata
        top_key = None
    else:
        raise RuntimeError("Unknown targets json structure (expected dict with 'combos'/'results' or a list).")

    out_combos: List[Dict[str, Any]] = []

    stats_total_targets = 0
    stats_kept_targets = 0
    stats_total_combos = 0
    stats_kept_combos = 0
    stats_missing_pit = 0

    for c in combos:
        stats_total_combos += 1

        pit = c.get("pit") or c.get("pit_key") or c.get("pit_name")
        dst = c.get("dst") or c.get("dst_key") or c.get("dst_name")

        if not pit or pit not in super_data["luts"]:
            # pit ontbreekt in super json => we kunnen niet filteren
            stats_missing_pit += 1
            c2 = dict(c)
            c2.setdefault("notes", []).append("missing_pit_in_super_json")
            out_combos.append(c2)
            stats_kept_combos += 1
            continue

        pins = pit_inputs_set(super_data, pit)

        targets = c.get("targets", []) or []
        if not isinstance(targets, list):
            targets = []

        kept: List[Dict[str, Any]] = []
        dropped: List[Dict[str, Any]] = []

        for t in targets:
            stats_total_targets += 1
            support = t.get("support_nets", []) or []
            support_set = set(str(x) for x in support)

            # HARD RULE:
            ok = support_set.issubset(pins)

            if ok:
                kept.append(t)
                stats_kept_targets += 1
            else:
                # voor debug: bewaar waarom gedropt
                t2 = dict(t)
                t2["drop_reason"] = "support_not_subset_of_pit_inputs"
                t2["missing_from_pit_inputs"] = sorted(list(support_set - pins))
                dropped.append(t2)

        c_out = dict(c)
        c_out["pit_inputs_ordered"] = sorted(list(pins))
        c_out["targets_before"] = len(targets)
        c_out["targets_after"] = len(kept)
        c_out["targets"] = kept
        c_out["dropped_targets"] = dropped  # handig voor debug

        if args.drop_if_empty and len(kept) == 0:
            continue

        out_combos.append(c_out)
        stats_kept_combos += 1

    out_obj: Any
    if top_key is None:
        out_obj = out_combos
    else:
        out_obj = dict(tdata)
        out_obj[top_key] = out_combos

    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(out_obj, indent=2))

    print("=== FILTER TARGETS BY PIT INPUTS (Step 1) ===")
    print(f"Super   : {super_p}")
    print(f"Targets : {targets_p}")
    print(f"Output  : {out_p}")
    print(f"Combos  : {stats_total_combos} -> kept {stats_kept_combos} (missing pit: {stats_missing_pit})")
    print(f"Targets : {stats_total_targets} -> kept {stats_kept_targets}")


if __name__ == "__main__":
    main()
