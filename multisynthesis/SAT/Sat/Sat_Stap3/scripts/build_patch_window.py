#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


def load_json(p: str) -> Any:
    return json.loads(Path(p).read_text())


def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2))


def get_fanout_sinks(fanout: Dict[str, Any], lut: str) -> List[Dict[str, Any]]:
    # fanout_sinks maps LUT -> list of {dst, pin}
    return (fanout.get("fanout_sinks", {}) or {}).get(lut, []) or []


def fanout_cone(fanout: Dict[str, Any], seeds: Set[str], depth: int) -> Tuple[Set[str], Dict[str, Any]]:
    """
    Compute LUT set reachable by LUT->LUT fanout edges up to 'depth' steps, including seeds.
    Returns (window_set, debug_info)
    """
    window: Set[str] = set(seeds)
    debug_layers: List[Dict[str, Any]] = []

    q = deque([(s, 0) for s in seeds])
    seen_depth: Dict[str, int] = {s: 0 for s in seeds}

    while q:
        u, d = q.popleft()
        if d == depth:
            continue
        sinks = get_fanout_sinks(fanout, u)
        added: List[str] = []
        for e in sinks:
            v = e.get("dst")
            if not isinstance(v, str) or not v.startswith("LUT_"):
                continue
            nd = d + 1
            if v not in window:
                window.add(v)
                added.append(v)
                seen_depth[v] = nd
                q.append((v, nd))
            else:
                # If we found a shorter depth, keep it (not essential, but nice for debug)
                if seen_depth.get(v, nd) > nd:
                    seen_depth[v] = nd
                    q.append((v, nd))

        if added:
            debug_layers.append({"from": u, "depth_from_seed": d, "added": added})

    debug_info = {
        "depth": depth,
        "seeds": sorted(seeds),
        "expansion_events": debug_layers,
    }
    return window, debug_info


def compute_cutpoints(fanout: Dict[str, Any], window: Set[str]) -> Tuple[List[str], Dict[str, Any]]:
    """
    Cutpoints are outputs (nets) of LUTs in window that feed any LUT outside the window.
    Since net naming uses LUT output net == LUT name, the cutpoint net is just the LUT name.
    """
    cutpoints: Set[str] = set()
    edges_out: List[Dict[str, Any]] = []

    for u in sorted(window):
        sinks = get_fanout_sinks(fanout, u)
        for e in sinks:
            v = e.get("dst")
            pin = e.get("pin")
            if not isinstance(v, str) or not v.startswith("LUT_"):
                continue
            if v not in window:
                cutpoints.add(u)  # u's output net leaves the window
                edges_out.append({"from": u, "to": v, "to_pin": pin})

    debug = {
        "edges_leaving_window": edges_out,
        "num_edges_leaving_window": len(edges_out),
    }
    return sorted(cutpoints), debug


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="Path to TARGET super-json (with rewire_patches)")
    ap.add_argument("--fanout", required=True, help="Path to fanout.json from Step1")
    ap.add_argument("--outdir", required=True, help="Output directory")
    ap.add_argument("--depth", type=int, default=1, help="Fanout-cone depth D (default 1)")
    args = ap.parse_args()

    target = load_json(args.target)
    fanout = load_json(args.fanout)

    patches = target.get("rewire_patches", []) or []
    if not patches:
        raise RuntimeError("No rewire_patches found in TARGET super-json")

    p0 = patches[0]
    dst = p0["dst_lut"]
    pit = p0["new_driver"]  # pitstop output net == LUT name in your encoding

    if not (isinstance(dst, str) and dst.startswith("LUT_")):
        raise ValueError(f"Unexpected dst_lut: {dst}")
    if not (isinstance(pit, str) and pit.startswith("LUT_")):
        raise ValueError(f"Unexpected new_driver/pitstop: {pit}")

    seeds = {dst, pit}

    window, win_dbg = fanout_cone(fanout, seeds, depth=args.depth)

    # PATCH_LUTS = window (for now)
    cutpoints, cut_dbg = compute_cutpoints(fanout, window)

    # PATCH_LUTS = window minus cutpoints (do not patch boundary signals)
    patch_luts = sorted(set(window) - set(cutpoints))
    if set(patch_luts) & set(cutpoints):
        raise RuntimeError("Internal error: PATCH_LUTS intersects CUTPOINT_NETS")

    out = {
        "design": target.get("design"),
        "K": target.get("K"),
        "target_file": str(Path(args.target)),
        "fanout_file": str(Path(args.fanout)),
        "rewire_patch_used": p0,
        "depth": args.depth,
        "PATCH_LUTS": patch_luts,
        "CUTPOINT_NETS": cutpoints,
        "debug": {
            "window_expansion": win_dbg,
            "cutpoints": cut_dbg,
        },
    }

    outdir = Path(args.outdir).expanduser()
    outpath = outdir / "patch_window_feasible0.json"
    write_json(outpath, out)

    print("[OK] Wrote patch window spec:")
    print(f"  - {outpath}")
    print("[Summary]")
    print(f"  PATCH_LUTS: {len(patch_luts)}")
    print(f"  CUTPOINT_NETS: {len(cutpoints)}")
    print(f"  depth: {args.depth}")
    print(f"  seeds: {sorted(seeds)}")


if __name__ == "__main__":
    main()
