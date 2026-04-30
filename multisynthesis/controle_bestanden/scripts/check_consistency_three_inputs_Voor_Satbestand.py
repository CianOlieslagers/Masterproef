#!/usr/bin/env python3
"""
check_consistency_cutpoints.py

Correcte consistentie-check voor jouw flow:
- leaves in lut_cones.json worden behandeld als CUTPOINTS (drivers van LUT pins)
- traversal vanaf lut_root stopt op leaves (snijdt de cone af op LUT inputs)
- check: bereikbare cutpoints == leaves   (closure binnen cutpoint-grens)
- NIET: doorlopen tot PIs (dat geeft false positives)

Daarnaast:
- vergelijkt cones.json met embedded aig info in lut_connections_full.json
- valideert node-id ranges en AND/PI membership op basis van AAG

Usage:
  python3 check_consistency_cutpoints.py \
    --aag   /path/to/example_big_300.clean.postopt.aag \
    --cones /path/to/example_big_300.lut_cones.json \
    --conns /path/to/example_big_300.lut_connections_full.json \
    --out   /path/to/report_cutpoint.json

Exit code:
  0 = geen errors
  1 = errors
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional


# -----------------------------
# AAG parsing (ASCII AIGER)
# -----------------------------
def parse_aag(path: Path) -> dict:
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip() != ""]
    if not lines or not lines[0].startswith("aag "):
        raise ValueError(f"Not an ASCII AAG file (missing 'aag' header): {path}")

    parts = lines[0].split()
    if len(parts) != 6:
        raise ValueError(f"Bad AAG header: {lines[0]}")
    _, M, I, L, O, A = parts
    M, I, L, O, A = int(M), int(I), int(L), int(O), int(A)
    if L != 0:
        raise ValueError(f"Unexpected latch count L={L}. Script expects combinational AAG (L=0).")

    idx = 1
    pis_lits = [int(lines[idx + k]) for k in range(I)]
    idx += I
    pos_lits = [int(lines[idx + k]) for k in range(O)]
    idx += O

    and_map: Dict[int, Tuple[int, int]] = {}
    for k in range(A):
        lhs, r0, r1 = lines[idx + k].split()
        lhs_lit, r0_lit, r1_lit = int(lhs), int(r0), int(r1)
        nid = lhs_lit // 2
        and_map[nid] = (r0_lit, r1_lit)

    pis_nodes = {lit // 2 for lit in pis_lits}

    return {
        "M": M, "I": I, "O": O, "A": A,
        "pis_lits": pis_lits, "pos_lits": pos_lits,
        "pis_nodes": pis_nodes,
        "and": and_map
    }


def lit_to_nid(lit: int) -> Optional[int]:
    if lit in (0, 1):
        return None
    return lit // 2


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def norm_lut(name: str) -> str:
    return name.strip()


# -----------------------------
# Cutpoint traversal: stop at leaves
# -----------------------------
def compute_cutpoint_boundary(
    aig_and: Dict[int, Tuple[int, int]],
    root: int,
    leaves: Set[int]
) -> Tuple[Set[int], Set[int]]:
    """
    Traverse vanaf root door AND fanins, maar STOP bij nodes in 'leaves'.
    Return:
      reached_leaves: welke leaves effectief bereikt worden
      extra_cutpoints: cutpoints die ontstaan doordat je een fanin tegenkomt die
                       geen AND-row heeft én ook niet in leaves zit (dus een PI/boundary
                       die niet als cutpoint verwacht was)
    Intuïtie:
      - In een correcte LUT cone hoort ALLES onder root uiteindelijk af te kappen
        op de 4 leaves (cutpoints).
      - Als je onderweg een PI/boundary tegenkomt die niet in leaves zit => cone/leaves inconsistent.
    """
    seen: Set[int] = set()
    stack: List[int] = [root]

    reached_leaves: Set[int] = set()
    extra_cutpoints: Set[int] = set()

    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)

        if n in leaves:
            reached_leaves.add(n)
            continue

        row = aig_and.get(n)
        if row is None:
            # We zitten op een boundary node (PI of iets zonder AND-row),
            # maar dit is geen leaf cutpoint => inconsistent cone model.
            extra_cutpoints.add(n)
            continue

        for fan_lit in row:
            fan_nid = lit_to_nid(fan_lit)
            if fan_nid is None:
                continue
            # Als fan_nid leaf is, zal volgende iteratie het cap'en.
            stack.append(fan_nid)

    return reached_leaves, extra_cutpoints


# -----------------------------
# Main
# -----------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aag", required=True, type=Path)
    ap.add_argument("--cones", required=True, type=Path)
    ap.add_argument("--conns", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max_list", type=int, default=50, help="limit how many node ids are listed per issue")
    args = ap.parse_args()

    aag = parse_aag(args.aag)
    cones = load_json(args.cones)
    conns = load_json(args.conns)

    cones_list = cones.get("lut_cones", [])
    cones_by_name = {norm_lut(x["lut_name"]): x for x in cones_list}

    and_nodes = set(aag["and"].keys())
    pis_nodes = set(aag["pis_nodes"])
    M = int(aag["M"])

    report = {
        "inputs": {
            "aag": str(args.aag),
            "cones": str(args.cones),
            "conns": str(args.conns),
        },
        "summary": {
            "errors": 0,
            "warnings": 0,
            "checked_luts": 0,
            "checked_connections": 0,
        },
        "errors": [],
        "warnings": [],
        "lut_reports": {}
    }

    def err(msg: str, ctx: dict | None = None):
        report["summary"]["errors"] += 1
        report["errors"].append({"msg": msg, "ctx": ctx or {}})

    def warn(msg: str, ctx: dict | None = None):
        report["summary"]["warnings"] += 1
        report["warnings"].append({"msg": msg, "ctx": ctx or {}})

    # metadata check
    if conns.get("design") and cones.get("circuit") and conns["design"] != cones["circuit"]:
        err("Design mismatch conns.design != cones.circuit", {"conns": conns["design"], "cones": cones["circuit"]})

    if cones.get("K") != 4:
        warn("cones.K != 4 (expected LUT4)", {"cones.K": cones.get("K")})

    def check_nid_in_range(nid: int, where: str, lut: str):
        if nid < 1 or nid > M:
            err("Node id outside AAG range", {"lut": lut, "where": where, "nid": nid, "M": M})

    # collect referenced LUTs from conns
    referenced: Set[str] = set()
    for c in conns.get("connections", []):
        report["summary"]["checked_connections"] += 1
        referenced.add(norm_lut(c["src"]["lut_name"]))
        referenced.add(norm_lut(c["dst"]["lut_name"]))
        for p in c.get("pitstops", []):
            referenced.add(norm_lut(p["lut_name"]))

    # helper: compare with embedded aig block in conns
    def compare_embedded(lut_name: str, cone: dict, embedded: dict, label: str):
        if not embedded or not embedded.get("found", False):
            return
        root_c = int(cone["lut_root"])
        root_e = int(embedded.get("lut_root"))
        if root_c != root_e:
            err("lut_root mismatch cones vs conns-embedded", {"lut": lut_name, "label": label, "cones": root_c, "embedded": root_e})

        leaves_c = set(int(x) for x in cone.get("leaves", []))
        leaves_e = set(int(x) for x in embedded.get("leaves", []))
        if leaves_c != leaves_e:
            err("leaves mismatch cones vs conns-embedded", {
                "lut": lut_name, "label": label,
                "only_in_embedded": sorted(leaves_e - leaves_c)[:args.max_list],
                "only_in_cones": sorted(leaves_c - leaves_e)[:args.max_list],
            })

        int_c = set(int(x) for x in cone.get("internal_nodes", []))
        int_e = set(int(x) for x in embedded.get("internal_nodes", []))
        if int_c != int_e:
            err("internal_nodes mismatch cones vs conns-embedded", {
                "lut": lut_name, "label": label,
                "only_in_embedded": sorted(int_e - int_c)[:args.max_list],
                "only_in_cones": sorted(int_c - int_e)[:args.max_list],
            })

        fh_c = str(cone.get("func_hex", "")).lower()
        fh_e = str(embedded.get("func_hex", "")).lower()
        if fh_c and fh_e and fh_c != fh_e:
            err("func_hex mismatch cones vs conns-embedded", {"lut": lut_name, "label": label, "cones": fh_c, "embedded": fh_e})

    # index conns embedded aig blocks by lut_name for quick compare
    embedded_blocks: Dict[str, List[Tuple[str, dict]]] = {}
    for c in conns.get("connections", []):
        for role in ("src", "dst"):
            ln = norm_lut(c[role]["lut_name"])
            embedded_blocks.setdefault(ln, []).append((role, c[role].get("aig", {})))
        for p in c.get("pitstops", []):
            ln = norm_lut(p["lut_name"])
            embedded_blocks.setdefault(ln, []).append(("pitstop", p.get("aig", {})))

    # main per-LUT checks
    for lut_name in sorted(referenced):
        report["summary"]["checked_luts"] += 1
        cone = cones_by_name.get(lut_name)
        lr = {"lut_name": lut_name, "errors": [], "warnings": [], "checks": {}}
        report["lut_reports"][lut_name] = lr

        if cone is None:
            err("Referenced LUT missing in lut_cones.json", {"lut": lut_name})
            continue

        root = int(cone["lut_root"])
        leaves = set(int(x) for x in cone.get("leaves", []))
        internals = set(int(x) for x in cone.get("internal_nodes", []))

        # basic node id validity
        check_nid_in_range(root, "lut_root", lut_name)
        for n in leaves:
            check_nid_in_range(n, "leaf", lut_name)
        for n in internals:
            check_nid_in_range(n, "internal_node", lut_name)

        # root should be AND node (in jouw data lijkt dat zo)
        if root not in and_nodes:
            err("lut_root not found as AND node in AAG", {"lut": lut_name, "lut_root": root})

        # internal nodes must be AND nodes
        bad_internal = sorted([n for n in internals if n not in and_nodes])
        if bad_internal:
            err("Some internal_nodes are not AND nodes in AAG", {"lut": lut_name, "bad_internal": bad_internal[:args.max_list], "count": len(bad_internal)})

        # leaves being AND nodes is OK (cutpoints can be AND outputs), so no warning here.

        # cutpoint-closure check: stop traversal at leaves
        reached_leaves, extra_cutpoints = compute_cutpoint_boundary(aag["and"], root, leaves)

        missing_leaves = sorted(leaves - reached_leaves)
        unexpected_cutpoints = sorted(extra_cutpoints)

        lr["checks"]["cutpoint_closure"] = {
            "leaves_count": len(leaves),
            "reached_leaves_count": len(reached_leaves),
            "missing_leaves": missing_leaves[:args.max_list],
            "missing_count": len(missing_leaves),
            "unexpected_cutpoints": unexpected_cutpoints[:args.max_list],
            "unexpected_count": len(unexpected_cutpoints),
            "unexpected_that_are_PIs": [n for n in unexpected_cutpoints if n in pis_nodes][:args.max_list],
        }

        # hard correctness: all leaves must be reachable as cutpoints, and there must be no extra cutpoints
        if missing_leaves:
            err("Cutpoint closure FAIL: some leaves are not reached from lut_root when stopping at leaves",
                {"lut": lut_name, "lut_root": root, "missing_leaves": missing_leaves[:args.max_list], "missing_count": len(missing_leaves)})

        if unexpected_cutpoints:
            err("Cutpoint closure FAIL: traversal hits boundary nodes that are not declared as leaves (cone not cut at pins)",
                {"lut": lut_name, "lut_root": root, "unexpected_cutpoints": unexpected_cutpoints[:args.max_list], "unexpected_count": len(unexpected_cutpoints)})

        # sanity: LUT4 should have exactly 4 leaves (in jouw format)
        if len(leaves) != 4:
            warn("LUT does not have exactly 4 leaves (unexpected for LUT4 cones)", {"lut": lut_name, "leaves_count": len(leaves), "leaves": sorted(leaves)[:args.max_list]})

        # compare with embedded conns aig blocks when present
        for label, emb in embedded_blocks.get(lut_name, []):
            compare_embedded(lut_name, cone, emb, label)

    # write
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(f"[DONE] Wrote report to {args.out}")
    print(f"Errors: {report['summary']['errors']}, Warnings: {report['summary']['warnings']}")
    return 0 if report["summary"]["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
