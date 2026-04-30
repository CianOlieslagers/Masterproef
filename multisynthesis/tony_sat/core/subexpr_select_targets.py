#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_json(p: str) -> Any:
    return json.loads(Path(p).read_text())


def build_dst_index(dst_subexprs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    # dst -> report
    idx: Dict[str, Dict[str, Any]] = {}
    for rep in dst_subexprs.get("reports", []):
        dst = rep.get("dst")
        if isinstance(dst, str):
            idx[dst] = rep
    return idx


def build_reach_index(reach: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    # (dst,pit) -> report
    idx: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rep in reach.get("results", []):
        dst = rep.get("dst")
        pit = rep.get("pit")
        if isinstance(dst, str) and isinstance(pit, str):
            idx[(dst, pit)] = rep
    return idx


def iter_combos(superj: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for conn in superj.get("connections", []) or []:
        dst = (conn.get("dst", {}) or {}).get("lut_name")
        src = (conn.get("src", {}) or {}).get("lut_name")
        for ps in conn.get("pitstops", []) or []:
            pit = ps.get("lut_name")
            net_link = ps.get("net_link", {}) or {}
            out.append({
                "conn_id": conn.get("conn_id"),
                "src": src,
                "dst": dst,
                "pit": pit,
                "net_link": net_link,
                "gain": (ps.get("costs", {}) or {}).get("gain"),
                "d_ab": conn.get("d_ab"),
                "d_ac": (ps.get("distances", {}) or {}).get("d_ac"),
                "d_cb": (ps.get("distances", {}) or {}).get("d_cb"),
            })
    return out


def score_subexpr(sub: Dict[str, Any], dst_pin: int, num_dc: int) -> Tuple[int, int, int]:
    """
    Lower is better. We sort by:
      1) support_size (small first)
      2) prefer supports that include dst_pin (already filtered, but keep as tie-break)
      3) prefer larger num_dc (more freedom) -> negative in key
    """
    support_size = int(sub.get("support_size", 99))
    support_pin_idx = sub.get("support_pin_idx", []) or []
    includes = 0 if dst_pin in support_pin_idx else 1
    return (support_size, includes, -int(num_dc))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--super", required=True, help="example_big_300.super.sat.v2.json")
    ap.add_argument("--dst-subexprs", required=True, help="dst_subexprs.json")
    ap.add_argument("--reachable", required=True, help="reachable_rows_test1.json")
    ap.add_argument("--out", required=True, help="output json")
    ap.add_argument("--top", type=int, default=10, help="top-N targets per combo")
    ap.add_argument("--max-support", type=int, default=4, help="only keep subexprs with support_size <= this")
    args = ap.parse_args()

    superj = load_json(args.super)
    dst_subexprs = load_json(args.dst_subexprs)
    reachable = load_json(args.reachable)

    dst_idx = build_dst_index(dst_subexprs)
    reach_idx = build_reach_index(reachable)

    combos = iter_combos(superj)

    results: List[Dict[str, Any]] = []
    for c in combos:
        dst = c["dst"]
        pit = c["pit"]
        net_link = c.get("net_link", {}) or {}
        dst_pin = net_link.get("dst_input_pin", None)

        rep_dst = dst_idx.get(dst)
        rep_reach = reach_idx.get((dst, pit))

        notes: List[str] = []
        if rep_dst is None:
            notes.append("missing_dst_subexpr_report")
        if rep_reach is None:
            notes.append("missing_reachable_report_for_combo")
        if not isinstance(dst_pin, int):
            notes.append("missing_dst_input_pin")

        targets: List[Dict[str, Any]] = []
        if rep_dst is not None and rep_reach is not None and isinstance(dst_pin, int):
            num_dc = int(rep_reach.get("num_dc", 0))
            subexprs = rep_dst.get("subexprs", []) or []

            # filter: must depend on the pin that pit feeds
            for s in subexprs:
                sup_idx = s.get("support_pin_idx", []) or []
                if not isinstance(sup_idx, list):
                    continue
                if dst_pin not in sup_idx:
                    continue
                if int(s.get("support_size", 99)) > args.max_support:
                    continue
                targets.append(s)

            targets.sort(key=lambda s: score_subexpr(s, dst_pin, num_dc))
            targets = targets[: args.top]

        results.append({
            **c,
            "dst_input_pin": dst_pin,
            "num_dc": None if rep_reach is None else rep_reach.get("num_dc"),
            "num_reachable": None if rep_reach is None else rep_reach.get("num_reachable"),
            "targets": targets,
            "notes": notes,
        })

    out_obj = {
        "super": args.super,
        "dst_subexprs": args.dst_subexprs,
        "reachable": args.reachable,
        "top": args.top,
        "max_support": args.max_support,
        "results": results,
    }

    Path(args.out).write_text(json.dumps(out_obj, indent=2))
    print("=== SELECT TARGET SUBEXPRS (per dst,pit) ===")
    print("Combos:", len(results))
    kept = sum(1 for r in results if len(r.get("targets", [])) > 0)
    print("With >=1 target:", kept)
    print("Output:", args.out)


if __name__ == "__main__":
    main()
