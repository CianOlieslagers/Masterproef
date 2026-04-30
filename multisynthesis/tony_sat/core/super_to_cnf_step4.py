#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set

from pysat.solvers import Solver

from tony_sat.core.cnf_builder import CNFBuilder
from tony_sat.core.cnf_gates import gate_xor, gate_or

SolverName = "glucose4"

def load_json(p: str) -> Any:
    return json.loads(Path(p).read_text())

def hex16_to_bits(h: str) -> List[int]:
    hs = h.lower().strip()
    if hs.startswith("0x"):
        hs = hs[2:]
    val = int(hs, 16) & 0xFFFF
    return [(val >> i) & 1 for i in range(16)]  # LSB-first

def ensure_var(cnf: CNFBuilder, name: str) -> int:
    if name in cnf.name2var:
        return cnf.var(name)
    return cnf.new_var(name)

def lit_for_match(x: int, bit: int) -> int:
    # if bit==1 => x must be True => literal x
    # if bit==0 => x must be False => literal -x
    return x if bit == 1 else -x

def add_lut4_fixed(cnf: CNFBuilder, xs: List[int], y: int, vbits: List[int]) -> None:
    if len(xs) != 4 or len(vbits) != 16:
        raise ValueError("bad lut sizes")
    x0, x1, x2, x3 = xs
    for r in range(16):
        b0 = (r >> 0) & 1
        b1 = (r >> 1) & 1
        b2 = (r >> 2) & 1
        b3 = (r >> 3) & 1
        m0 = lit_for_match(x0, b0)
        m1 = lit_for_match(x1, b1)
        m2 = lit_for_match(x2, b2)
        m3 = lit_for_match(x3, b3)
        # (~m0 or ~m1 or ~m2 or ~m3 or (y == vbits[r]))
        if vbits[r] == 1:
            cnf.add_clause([-m0, -m1, -m2, -m3, y])
        else:
            cnf.add_clause([-m0, -m1, -m2, -m3, -y])

def add_lut4_patch(cnf: CNFBuilder, xs: List[int], y: int, tvars: List[int]) -> None:
    if len(xs) != 4 or len(tvars) != 16:
        raise ValueError("bad lut sizes")
    x0, x1, x2, x3 = xs
    for r in range(16):
        b0 = (r >> 0) & 1
        b1 = (r >> 1) & 1
        b2 = (r >> 2) & 1
        b3 = (r >> 3) & 1
        m0 = lit_for_match(x0, b0)
        m1 = lit_for_match(x1, b1)
        m2 = lit_for_match(x2, b2)
        m3 = lit_for_match(x3, b3)
        t = tvars[r]
        # (match -> (y <-> t))
        cnf.add_clause([-m0, -m1, -m2, -m3, -y, t])
        cnf.add_clause([-m0, -m1, -m2, -m3, y, -t])

def get_lut_pins(S: Dict[str, Any], lut: str) -> List[str]:
    nl = (S["luts"][lut].get("netlist") or {})

    pins = list(nl.get("lut_inputs_ordered") or [])
    if len(pins) == 4:
        return pins

    clb = list(nl.get("clb_inputs") or [])
    rot = list(nl.get("rotation_map") or [])

    # fallback: rotation_map maps logical pin index -> clb_inputs index
    if rot and clb and len(rot) <= len(clb):
        pins2 = [clb[i] for i in rot]
    else:
        pins2 = clb

    while len(pins2) < 4:
        pins2.append("open")
    pins2 = pins2[:4]

    if len(pins2) != 4:
        raise RuntimeError(f"{lut}: cannot derive 4 pins (lut_inputs_ordered={len(pins)}, clb_inputs={len(clb)}, rotation_map={len(rot)})")

    return pins2

def get_lut_func_hex(S: Dict[str, Any], lut: str) -> str:
    ent = S["luts"][lut]
    h = ent.get("func_hex")
    if not isinstance(h, str):
        raise RuntimeError(f"{lut}: missing func_hex")
    return h

def build_circuit(
    cnf: CNFBuilder,
    S: Dict[str, Any],
    side_prefix: str,
    patch_luts: Set[str],
    patch_tt_prefix: str = "TT__",
) -> Dict[str, int]:
    """
    Build LUT-level CNF for one circuit.
    Returns net_name -> var_id (for this side).
    """
    net2var: Dict[str, int] = {}
    const0 = cnf.new_var(f"{side_prefix}CONST0")
    cnf.add_unit(const0, False)
    # Inputs: from blif_inputs
    blif_inputs = (S.get("aig_graph") or {}).get("blif_inputs") or []
    if not isinstance(blif_inputs, list) or len(blif_inputs) == 0:
        raise RuntimeError("Missing aig_graph.blif_inputs in super-json")
    for net in blif_inputs:
        if not isinstance(net, str):
            continue
        v = ensure_var(cnf, f"{side_prefix}{net}")
        net2var[net] = v

    # LUT outputs
    for lut in sorted(S["luts"].keys()):
        y = ensure_var(cnf, f"{side_prefix}{lut}")
        net2var[lut] = y

    # LUT constraints
    for lut in sorted(S["luts"].keys()):
        pins = get_lut_pins(S, lut)
        xs: List[int] = []
        for net in pins:
            if net == "open":
                xs.append(const0)
            else:
                if net not in net2var:
                    net2var[net] = ensure_var(cnf, f"{side_prefix}{net}")
                xs.append(net2var[net])

        y = net2var[lut]
        if lut in patch_luts:
            tvars = [ensure_var(cnf, f"{patch_tt_prefix}{lut}__{r}") for r in range(16)]
            add_lut4_patch(cnf, xs, y, tvars)
        else:
            vbits = hex16_to_bits(get_lut_func_hex(S, lut))
            add_lut4_fixed(cnf, xs, y, vbits)

    return net2var

def build_diff_or(cnf: CNFBuilder, diffs: List[int]) -> int:
    if not diffs:
        raise RuntimeError("No diffs to OR")
    cur = diffs[0]
    for i in range(1, len(diffs)):
        nxt = cnf.new_var(f"diff_or_{i}")
        gate_or(cnf, cur, diffs[i], nxt)
        cur = nxt
    return cur

def solve_assuming(cnf: CNFBuilder, assumptions: List[int]) -> bool:
    with Solver(name=SolverName) as s:
        for cl in cnf.clauses:
            s.add_clause(cl)
        return s.solve(assumptions=assumptions)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--window", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--selfcheck", action="store_true", help="Run SPEC-vs-SPEC UNSAT(diff=1) check on CUTPOINT_NETS")
    args = ap.parse_args()

    spec = load_json(args.spec)
    tgt = load_json(args.target)
    win = load_json(args.window)

    patch_luts = set(win.get("PATCH_LUTS") or [])
    cutpoints = list(win.get("CUTPOINT_NETS") or [])
    if not patch_luts or not cutpoints:
        raise RuntimeError("window json missing PATCH_LUTS or CUTPOINT_NETS")

    cnf = CNFBuilder()

    # Build SPEC and TARGET
    S_net = build_circuit(cnf, spec, side_prefix="S__", patch_luts=set())
    T_net = build_circuit(cnf, tgt, side_prefix="T__", patch_luts=patch_luts, patch_tt_prefix="TT__")
    # ----------------------------
# Tie primary inputs: S__pi == T__pi
# ----------------------------
    blif_inputs = (spec.get("aig_graph") or {}).get("blif_inputs") or []
    if not isinstance(blif_inputs, list) or len(blif_inputs) == 0:
         raise RuntimeError("Missing aig_graph.blif_inputs for PI tying")

    for pi in blif_inputs:
        if not isinstance(pi, str):
            continue
        if pi not in S_net or pi not in T_net:
            raise RuntimeError(f"PI net missing in net maps: {pi} (S_has={pi in S_net}, T_has={pi in T_net})")
        s = S_net[pi]
        t = T_net[pi]
    # s <-> t
        cnf.add_clause([-s, t])
        cnf.add_clause([s, -t])

    # Build miter diffs on cutpoints (for later steps)
    diffs: List[int] = []
    for cp in cutpoints:
        if cp not in S_net or cp not in T_net:
            raise RuntimeError(f"Cutpoint {cp} not found as net in both circuits")
        d = cnf.new_var(f"xor__{cp}")
        gate_xor(cnf, S_net[cp], T_net[cp], d)
        diffs.append(d)
    diff_or = build_diff_or(cnf, diffs)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    (outdir / "spec_target.cnf.json").write_text(json.dumps({
        "spec": args.spec,
        "target": args.target,
        "window": args.window,
        "solver": SolverName,
        "vars": cnf.var_count,
        "clauses": len(cnf.clauses),
        "cutpoints": cutpoints,
        "patch_luts": sorted(patch_luts),
        "diff_or_var": diff_or,
        "name2var": cnf.name2var,
        "clauses_dimacs": cnf.clauses,
    }, indent=2))

    print("[OK] Wrote spec_target.cnf.json")
    print(f"[Stats] vars={cnf.var_count} clauses={len(cnf.clauses)} cutpoints={len(cutpoints)} patch_luts={len(patch_luts)}")

    if args.selfcheck:
        # Build SPEC2 and prove SPEC == SPEC2 (diff=1 UNSAT) on same cutpoints
        cnf2 = CNFBuilder()
        S1 = build_circuit(cnf2, spec, side_prefix="A__", patch_luts=set())
        S2 = build_circuit(cnf2, spec, side_prefix="B__", patch_luts=set())
# --- IMPORTANT: tie the PI nets between A__ and B__ ---
        blif_inputs = (spec.get("aig_graph") or {}).get("blif_inputs") or []
        for net in blif_inputs:
            if not isinstance(net, str):
                continue
            a = S1[net]   # A__pi...
            b = S2[net]   # B__pi...
            # enforce a <-> b
            cnf2.add_clause([-a, b])
            cnf2.add_clause([a, -b])
       # ------------------------------------------------------
        diffs2: List[int] = []
        for cp in cutpoints:
            d = cnf2.new_var(f"xor__{cp}")
            gate_xor(cnf2, S1[cp], S2[cp], d)
            diffs2.append(d)
        diff_or2 = build_diff_or(cnf2, diffs2)

        sat = solve_assuming(cnf2, assumptions=[diff_or2])  # try to find a mismatch
        (outdir / "spec_spec_selfcheck.json").write_text(json.dumps({
            "sat_for_diff1": sat,
            "expected": "UNSAT (sat_for_diff1 should be false)",
            "vars": cnf2.var_count,
            "clauses": len(cnf2.clauses),
            "diff_or_var": diff_or2,
        }, indent=2))
        print("[Selfcheck] SPEC vs SPEC diff=1 SAT?", sat, "(should be False)")

if __name__ == "__main__":
    main()
