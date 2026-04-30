#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_json(path: str) -> Any:
    return json.loads(Path(path).read_text())


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def build_fanout_from_lut_inputs_ordered(superj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reconstruct LUT->LUT fanout purely from netlist.lut_inputs_ordered.

    fanout(LUT_X) = number of LUT_Y such that "LUT_X" is in LUT_Y.netlist.lut_inputs_ordered
    We also store sink pin indices for each sink.

    This ignores PO fanout, and ignores PI fanout (piX), by design.
    """
    luts: Dict[str, Any] = superj.get("luts", {})
    fanout_sinks: Dict[str, List[Dict[str, int]]] = {}  # LUT_X -> [{dst, pin}, ...]
    fanout_count: Dict[str, int] = {}

    # initialize keys
    for lut_name in luts.keys():
        fanout_sinks[lut_name] = []
        fanout_count[lut_name] = 0

    for dst_name, dst_entry in luts.items():
        netlist = (dst_entry or {}).get("netlist", {}) or {}
        ins: List[str] = netlist.get("lut_inputs_ordered", []) or []
        for pin_idx, net in enumerate(ins):
            # only LUT_ nets create LUT fanout edges
            if isinstance(net, str) and net.startswith("LUT_"):
                if net not in fanout_sinks:
                    # Inconsistent naming: input references LUT that isn't in luts dict.
                    # Keep it but mark it as external.
                    fanout_sinks[net] = []
                    fanout_count[net] = 0
                fanout_sinks[net].append({"dst": dst_name, "pin": pin_idx})
                fanout_count[net] += 1

    return {
        "design": superj.get("design"),
        "K": superj.get("K"),
        "fanout_count": fanout_count,
        "fanout_sinks": fanout_sinks,
    }


def manhattan(a: Dict[str, int], b: Dict[str, int]) -> int:
    return abs(int(a["x"]) - int(b["x"])) + abs(int(a["y"]) - int(b["y"]))


def step1_feasibility(superj: Dict[str, Any], fanout: Dict[str, Any]) -> Dict[str, Any]:
    """
    Feasibility gate over superj["connections"][*]["pitstops"] candidates.

    Policy:
      - pitstop inputs do NOT change
      - support check (A): src_net in pitstop.lut.netlist.lut_inputs_ordered

    Pin-budget:
      - In your data, LUTs are LUT4 => always replace, never append
      - We take the dst_input_pin from net_link if present (enforced pin from src arc),
        otherwise fallback to src_to_dst_link if present.
    """
    connections = superj.get("connections", []) or []
    luts = superj.get("luts", {}) or {}
    fanout_count = fanout.get("fanout_count", {}) or {}

    feasible: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for c_idx, c in enumerate(connections):
        src = c.get("src", {}) or {}
        dst = c.get("dst", {}) or {}
        pits = c.get("pitstops", []) or []

        src_name = src.get("lut_name") or src.get("block")
        dst_name = dst.get("lut_name") or dst.get("block")

        src_out_net = (c.get("src_to_dst_link", {}) or {}).get("src_output_net")
        if not src_out_net and src_name:
            src_out_net = src_name  # usually "LUT_97"

        # distances (if coords exist in connection)
        src_coords = (src.get("coords") or {})
        dst_coords = (dst.get("coords") or {})

        for p_idx, p in enumerate(pits):
            pit_name = p.get("lut_name")
            pit_coords = (p.get("coords") or {})

            # --- support check (A) ---
            pit_lut = (p.get("lut") or {})  # already merged in build_super_json_sat.py
            pit_inputs = ((pit_lut.get("netlist") or {}).get("lut_inputs_ordered") or [])
            support_ok = bool(src_out_net and (src_out_net in pit_inputs))

            # --- pin strategy (always replace in LUT4 flow) ---
            net_link = p.get("net_link", {}) or {}
            dst_pin = net_link.get("dst_input_pin")
            if dst_pin is None:
                dst_pin = (c.get("src_to_dst_link", {}) or {}).get("dst_input_pin")
            pin_strategy = f"replace({dst_pin})" if dst_pin is not None else "replace(UNKNOWN)"

            # --- fanout pitstop ---
            pit_fanout = int(fanout_count.get(pit_name, 0))
            fanout_risk = "low" if pit_fanout <= 1 else ("medium" if pit_fanout <= 3 else "high")

            # --- routing plausibility ---
            timing_likely = None
            d_src_dst = None
            d_pit_dst = None
            if src_coords and dst_coords and pit_coords:
                d_src_dst = manhattan(src_coords, dst_coords)
                d_pit_dst = manhattan(pit_coords, dst_coords)
                timing_likely = (d_pit_dst < d_src_dst)

            # expected window size heuristic (only for reporting)
            expected_window = "min{pitstop,dst}" if pit_fanout <= 1 else "expand(depth>=1 or include fanouts)"

            rec = {
                "connection_index": c_idx,
                "pitstop_index": p_idx,
                "src": src_name,
                "dst": dst_name,
                "pitstop": pit_name,
                "support_ok": support_ok,
                "pin_strategy": pin_strategy,
                "pitstop_fanout": pit_fanout,
                "fanout_risk": fanout_risk,
                "d_src_dst": d_src_dst,
                "d_pit_dst": d_pit_dst,
                "timing_likely": timing_likely,
                "expected_window": expected_window,
            }

            # HARD GATE: support_ok must be true
            if support_ok:
                feasible.append(rec)
            else:
                rejected.append({**rec, "reject_reason": "support_fail: src not in pitstop.lut_inputs_ordered"})

    return {
        "design": superj.get("design"),
        "K": superj.get("K"),
        "counts": {
            "connections": len(connections),
            "feasible_targets": len(feasible),
            "rejected_targets": len(rejected),
        },
        "feasible": feasible,
        "rejected": rejected,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--super", required=True, help="Path to *.super.sat.v2.json")
    ap.add_argument("--outdir", required=True, help="Output directory for fanout + step1 report")
    args = ap.parse_args()

    super_path = Path(args.super)
    outdir = Path(args.outdir).expanduser()

    ensure_dir(outdir)

    superj = load_json(str(super_path))

    fanout = build_fanout_from_lut_inputs_ordered(superj)
    (outdir / "fanout.json").write_text(json.dumps(fanout, indent=2))

    report = step1_feasibility(superj, fanout)
    (outdir / "step1_report.json").write_text(json.dumps(report, indent=2))

    print("[OK] Wrote:")
    print(f"  - {outdir / 'fanout.json'}")
    print(f"  - {outdir / 'step1_report.json'}")
    print("[Summary]")
    print(json.dumps(report["counts"], indent=2))


if __name__ == "__main__":
    main()
