#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict


def load_json(p: str) -> Any:
    return json.loads(Path(p).read_text())


def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2))


def apply_patch(superj: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    dst_lut = patch["dst_lut"]
    pin = int(patch["replace_input_pin"])
    new_driver = patch["new_driver"]

    # --- hard checks ---
    if "luts" not in superj or dst_lut not in superj["luts"]:
        raise KeyError(f"dst_lut not found in super-json luts: {dst_lut}")

    if not (0 <= pin < int(superj.get("K", 4))):
        raise ValueError(f"replace_input_pin out of range: {pin}")

    if not (isinstance(new_driver, str) and new_driver.startswith("LUT_")):
        raise ValueError(f"new_driver must be LUT_* net, got: {new_driver}")

    if new_driver not in superj["luts"]:
        raise KeyError(f"new_driver LUT not found in super-json luts: {new_driver}")

    dst_entry = superj["luts"][dst_lut]
    netlist = dst_entry.get("netlist", {})
    ins = netlist.get("lut_inputs_ordered", None)

    if not isinstance(ins, list) or len(ins) != int(superj.get("K", 4)):
        raise ValueError(
            f"{dst_lut}.netlist.lut_inputs_ordered missing or not length K; got: {ins}"
        )

    old = ins[pin]
    if old == new_driver:
        raise ValueError(f"No-op patch: {dst_lut} pin {pin} already driven by {new_driver}")

    # --- apply change ---
    out = deepcopy(superj)
    out["rewire_patches"] = out.get("rewire_patches", [])
    out["rewire_patches"].append(patch)

    dst_netlist = out["luts"][dst_lut]["netlist"]
    dst_netlist["_rewire_debug"] = {
        "old_driver": old,
        "new_driver": new_driver,
        "pin": pin,
    }
    dst_netlist["lut_inputs_ordered"][pin] = new_driver

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--super", required=True, help="Path to original *.super.sat.v2.json")
    ap.add_argument("--step1", required=True, help="Path to step1_report.json")
    ap.add_argument("--index", type=int, default=0, help="feasible index to use (default 0)")
    ap.add_argument("--outdir", required=True, help="Output directory")
    args = ap.parse_args()

    superj = load_json(args.super)
    report = load_json(args.step1)

    feasible = report.get("feasible", [])
    if not feasible:
        raise RuntimeError("No feasible targets in step1_report.json")

    if not (0 <= args.index < len(feasible)):
        raise IndexError(f"feasible index out of range: {args.index} (len={len(feasible)})")

    f = feasible[args.index]

    # Build patch from feasible entry
    # We parse pin from "replace(N)"
    pin_strategy = f["pin_strategy"]
    if not (pin_strategy.startswith("replace(") and pin_strategy.endswith(")")):
        raise ValueError(f"Unexpected pin_strategy format: {pin_strategy}")
    pin = int(pin_strategy[len("replace("):-1])

    patch = {
        "dst_lut": f["dst"],
        "replace_input_pin": pin,
        "new_driver": f["pitstop"],
        "inversion": False,
        "meta": {
            "src": f["src"],
            "connection_index": f["connection_index"],
            "pitstop_index": f["pitstop_index"],
            "support_ok": f["support_ok"],
            "d_src_dst": f.get("d_src_dst"),
            "d_pit_dst": f.get("d_pit_dst"),
            "pitstop_fanout": f.get("pitstop_fanout"),
        },
    }

    outdir = Path(args.outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    patch_path = outdir / f"patch_feasible{args.index}.json"
    target_path = outdir / f"target_feasible{args.index}.super.sat.v2.json"

    write_json(patch_path, patch)

    target = apply_patch(superj, patch)
    write_json(target_path, target)

    # Print a small sanity summary
    old = target["luts"][patch["dst_lut"]]["netlist"]["_rewire_debug"]["old_driver"]
    new = target["luts"][patch["dst_lut"]]["netlist"]["_rewire_debug"]["new_driver"]
    pin = target["luts"][patch["dst_lut"]]["netlist"]["_rewire_debug"]["pin"]

    print("[OK] Rewire patch applied")
    print(f"  dst: {patch['dst_lut']} pin {pin}: {old} -> {new}")
    print(f"  wrote: {patch_path}")
    print(f"  wrote: {target_path}")


if __name__ == "__main__":
    main()
