#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

# ----------------------------
# LUT resolving helpers
# ----------------------------

def build_lutroot_index(luts: Dict[str, Any]) -> Dict[int, str]:
    idx: Dict[int, str] = {}
    for k, v in luts.items():
        if not isinstance(v, dict):
            continue
        r = v.get("lut_root", None)
        if isinstance(r, int):
            if r in idx and idx[r] != k:
                raise ValueError(f"Duplicate lut_root {r}: {idx[r]} and {k}")
            idx[r] = k
    return idx


def get_lut_by_root(luts: Dict[str, Any], lutroot_index: Dict[int, str], root: int) -> Optional[Tuple[str, Dict[str, Any]]]:
    key = lutroot_index.get(root)
    if key is None:
        return None
    lut = luts.get(key)
    if not isinstance(lut, dict):
        return None
    return key, lut


def lut_ready_for_v2(lut: Dict[str, Any], expect_k: int = 4) -> Tuple[bool, List[str]]:
    """
    Structural readiness for later cone-SAT:
      - K matches
      - has func_hex
      - has leaves/internal_nodes/node_functions
      - has netlist.lut_inputs_ordered and output_net
    """
    reasons: List[str] = []

    k = lut.get("K")
    if k != expect_k:
        reasons.append(f"K_mismatch(K={k})")

    if not isinstance(lut.get("func_hex"), str):
        reasons.append("missing_func_hex")

    leaves = lut.get("leaves", None)
    internal_nodes = lut.get("internal_nodes", None)
    node_functions = lut.get("node_functions", None)

    if not isinstance(leaves, list) or len(leaves) == 0:
        reasons.append("missing_leaves")
    if not isinstance(internal_nodes, list) or len(internal_nodes) == 0:
        reasons.append("missing_internal_nodes")
    if not isinstance(node_functions, list) or len(node_functions) == 0:
        reasons.append("missing_node_functions")

    netlist = lut.get("netlist", {}) or {}
    if not isinstance(netlist, dict):
        reasons.append("missing_netlist")
    else:
        if not isinstance(netlist.get("lut_inputs_ordered"), list) or len(netlist.get("lut_inputs_ordered")) != expect_k:
            reasons.append("missing_or_bad_lut_inputs_ordered")
        if netlist.get("output_net") is None:
            reasons.append("missing_output_net")

    return (len(reasons) == 0), reasons


def net_link_ok(net_link: Any) -> Tuple[bool, List[str]]:
    """
    For now we require that net_link identifies at least the dst input net or pin.
    """
    reasons: List[str] = []
    if not isinstance(net_link, dict):
        return False, ["missing_net_link_dict"]

    dst_pin = net_link.get("dst_input_pin", None)
    dst_net = net_link.get("dst_input_net", None)

    if dst_pin is None and dst_net is None:
        reasons.append("net_link_missing_dst_pin_and_net")

    # Optional: if you want to require BOTH pin and net, tighten here.
    return (len(reasons) == 0), reasons


# ----------------------------
# Reporting structs
# ----------------------------

@dataclass
class ComboResult:
    conn_id: Any
    src_root: Optional[int]
    dst_root: Optional[int]
    pit_root: Optional[int]

    src_key: Optional[str]
    dst_key: Optional[str]
    pit_key: Optional[str]

    structural_ok: bool
    reasons: List[str]

    # useful metadata:
    gain: Any = None
    d_ap: Any = None
    d_pb: Any = None
    d_ab: Any = None
    net_link: Any = None


@dataclass
class BatchReport:
    json_path: str
    total_connections: int
    total_pitstop_entries: int
    structural_ok_count: int
    failed_count: int
    results: List[ComboResult]


# ----------------------------
# Batch scan
# ----------------------------

def scan_all_combos(data: Dict[str, Any], expect_k: int = 4) -> BatchReport:
    luts = data.get("luts")
    if not isinstance(luts, dict):
        raise RuntimeError("JSON missing top-level 'luts' dict")

    lutroot_index = build_lutroot_index(luts)

    conns = data.get("connections", []) or []
    if not isinstance(conns, list):
        raise RuntimeError("JSON 'connections' is not a list")

    results: List[ComboResult] = []
    total_pitstop_entries = 0

    for conn in conns:
        conn_id = conn.get("conn_id", None)

        # src/dst roots (as stored inside connection block)
        src_root = None
        dst_root = None

        try:
            src_lut = ((conn.get("src", {}) or {}).get("lut", {}) or {})
            dst_lut = ((conn.get("dst", {}) or {}).get("lut", {}) or {})
            src_root = src_lut.get("lut_root", None)
            dst_root = dst_lut.get("lut_root", None)
        except Exception:
            pass

        pitstops = conn.get("pitstops", []) or []
        if not isinstance(pitstops, list):
            continue

        for ps in pitstops:
            total_pitstop_entries += 1

            # pit root
            # pit root  (in jouw JSON zit pitstop LUT direct onder ps["lut"])
            pit_root = None
            try:
                pit_lut = (ps.get("lut", {}) or {})
                pit_root = pit_lut.get("lut_root", None)
            except Exception:
                pit_root = None

            # map to LUTs table
            src_key = dst_key = pit_key = None
            src_obj = dst_obj = pit_obj = None

            if isinstance(src_root, int):
                got = get_lut_by_root(luts, lutroot_index, src_root)
                if got:
                    src_key, src_obj = got
            if isinstance(dst_root, int):
                got = get_lut_by_root(luts, lutroot_index, dst_root)
                if got:
                    dst_key, dst_obj = got
            if isinstance(pit_root, int):
                got = get_lut_by_root(luts, lutroot_index, pit_root)
                if got:
                    pit_key, pit_obj = got

            reasons: List[str] = []

            if src_obj is None:
                reasons.append("missing_src_lut_in_luts_table")
            if dst_obj is None:
                reasons.append("missing_dst_lut_in_luts_table")
            if pit_obj is None:
                reasons.append("missing_pit_lut_in_luts_table")

            # structural readiness for v2 (cone SAT) on dst and pit
            if dst_obj is not None:
                ok, rs = lut_ready_for_v2(dst_obj, expect_k=expect_k)
                if not ok:
                    reasons.extend([f"dst:{r}" for r in rs])
            if pit_obj is not None:
                ok, rs = lut_ready_for_v2(pit_obj, expect_k=expect_k)
                if not ok:
                    reasons.extend([f"pit:{r}" for r in rs])

            # net_link presence (needed to know which dst input is fed)
            net_link = ps.get("net_link", None)
            ok_nl, rs_nl = net_link_ok(net_link)
            if not ok_nl:
                reasons.extend(rs_nl)

            structural_ok = (len(reasons) == 0)
            dist = ps.get("distances", {}) or {}
            cost = ps.get("costs", {}) or {}
            gain = cost.get("gain", ps.get("gain", None))
            d_ap = dist.get("d_ap", ps.get("d_ap", None))
            d_pb = dist.get("d_pb", ps.get("d_pb", None))

            results.append(
                ComboResult(
                    conn_id=conn_id,
                    src_root=src_root if isinstance(src_root, int) else None,
                    dst_root=dst_root if isinstance(dst_root, int) else None,
                    pit_root=pit_root if isinstance(pit_root, int) else None,
                    src_key=src_key,
                    dst_key=dst_key,
                    pit_key=pit_key,
                    structural_ok=structural_ok,
                    reasons=reasons,
                    gain=gain,
                    d_ap=d_ap,
                    d_pb=d_pb,
                    d_ab=conn.get("d_ab", None),
                    net_link=net_link,
                )
            )

    ok_count = sum(1 for r in results if r.structural_ok)
    fail_count = len(results) - ok_count

    return BatchReport(
        json_path="",
        total_connections=len(conns),
        total_pitstop_entries=total_pitstop_entries,
        structural_ok_count=ok_count,
        failed_count=fail_count,
        results=results,
    )


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="Path to example_big_300.super.sat.v2.json")
    ap.add_argument("--out", required=True, help="Output JSON report path")
    ap.add_argument("--k", type=int, default=4, help="Expected LUT K (default 4)")
    ap.add_argument("--only-ok", action="store_true", help="Write only structural_ok results")
    args = ap.parse_args()

    p = Path(args.json)
    if not p.exists():
        raise FileNotFoundError(p)

    data = json.loads(p.read_text())
    report = scan_all_combos(data, expect_k=args.k)
    report.json_path = str(p)

    # Filter if requested
    results = report.results
    if args.only_ok:
        results = [r for r in results if r.structural_ok]

    out_obj = {
        "json_path": report.json_path,
        "total_connections": report.total_connections,
        "total_pitstop_entries": report.total_pitstop_entries,
        "structural_ok_count": sum(1 for r in results if r.structural_ok),
        "failed_count": sum(1 for r in results if not r.structural_ok),
        "results": [asdict(r) for r in results],
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(out_obj, indent=2))
    print("=== BATCH FEASIBILITY (structural) ===")
    print(f"Input : {p}")
    print(f"Output: {out_path}")
    print(f"Total pitstop entries scanned: {report.total_pitstop_entries}")
    print(f"Structural OK: {out_obj['structural_ok_count']}")
    print(f"Failed       : {out_obj['failed_count']}")

    reason_counts = Counter()
    for r in report.results:
        for reason in r.reasons:
            reason_counts[reason] += 1

    print("\n[TOP FAILURE REASONS]")
    for reason, cnt in reason_counts.most_common(15):
        print(f"  {reason}: {cnt}")
if __name__ == "__main__":
    main()
