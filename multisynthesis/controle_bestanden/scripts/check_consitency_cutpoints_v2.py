#!/usr/bin/env python3
import argparse, json
from pathlib import Path
from typing import Dict, Tuple, Set, List, Optional

def parse_aag(path: Path):
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    hdr = lines[0].split()
    assert hdr[0] == "aag"
    M, I, L, O, A = map(int, hdr[1:])
    assert L == 0
    idx = 1
    pis_lits = [int(lines[idx+i]) for i in range(I)]
    idx += I
    pos_lits = [int(lines[idx+i]) for i in range(O)]
    idx += O
    and_map: Dict[int, Tuple[int,int]] = {}
    for i in range(A):
        lhs, r0, r1 = map(int, lines[idx+i].split())
        and_map[lhs//2] = (r0, r1)
    pis_nodes = {lit//2 for lit in pis_lits}
    return {"M":M, "and":and_map, "pis_nodes":pis_nodes}

def lit_to_nid(lit: int) -> Optional[int]:
    if lit in (0,1): return None
    return lit//2

def cone_cutpoint_check(aig_and: Dict[int,Tuple[int,int]], root: int, leaves: Set[int]):
    """
    Traverse from root, stop on leaves.
    Track:
      - reached_leaves: leaves actually reached
      - boundary_outside_leaves: boundary nodes hit that are NOT leaves (real error)
    """
    seen: Set[int] = set()
    stack: List[int] = [root]
    reached_leaves: Set[int] = set()
    boundary_outside_leaves: Set[int] = set()

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
            # boundary node (PI) encountered BEFORE hitting a leaf => leak beyond cutpoints
            boundary_outside_leaves.add(n)
            continue

        for fan_lit in row:
            fan_nid = lit_to_nid(fan_lit)
            if fan_nid is not None:
                stack.append(fan_nid)

    return reached_leaves, boundary_outside_leaves

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aag", required=True, type=Path)
    ap.add_argument("--cones", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max_list", type=int, default=50)
    args = ap.parse_args()

    aag = parse_aag(args.aag)
    cones = json.loads(args.cones.read_text())
    lut_cones = cones["lut_cones"]

    report = {"summary":{"errors":0}, "errors":[],"lut_reports":{}}

    def err(msg, ctx):
        report["summary"]["errors"] += 1
        report["errors"].append({"msg":msg,"ctx":ctx})

    for c in lut_cones:
        name = c["lut_name"]
        root = int(c["lut_root"])
        leaves = set(int(x) for x in c.get("leaves", []))

        reached, boundary_outside = cone_cutpoint_check(aag["and"], root, leaves)
        missing = sorted(leaves - reached)

        lr = {
            "lut_root": root,
            "leaves": sorted(leaves),
            "reached_leaves": sorted(reached),
            "missing_leaves": missing[:args.max_list],
            "boundary_outside_leaves": sorted(boundary_outside)[:args.max_list],
            "boundary_outside_count": len(boundary_outside),
        }
        report["lut_reports"][name] = lr

        # Hard errors
        if missing:
            err("Missing leaves: listed as leaf but not reached when cutting at leaves", 
                {"lut":name, "missing_leaves": missing[:args.max_list], "missing_count": len(missing)})
        if boundary_outside:
            err("Cone leaks beyond leaves: hit PI/boundary node before encountering a leaf",
                {"lut":name, "boundary_outside_leaves": sorted(boundary_outside)[:args.max_list], "count": len(boundary_outside)})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(f"[DONE] Wrote {args.out}")
    print(f"Errors: {report['summary']['errors']}")
    return 0 if report["summary"]["errors"] == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
