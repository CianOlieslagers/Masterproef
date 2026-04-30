#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set

from pysat.solvers import Solver


def lit(v: int, bit: int) -> int:
    return v if bit == 1 else -v


def solve_with_assumptions(
    solver_name: str,
    cnf: List[List[int]],
    assumptions: List[int],
) -> Tuple[bool, Optional[List[int]]]:
    with Solver(name=solver_name) as s:
        for c in cnf:
            s.add_clause(c)
        ok = s.solve(assumptions=assumptions)
        return (ok, s.get_model()) if ok else (False, None)


def extract_ce_pi_assignment(name2var: Dict[str, int], model: List[int]) -> Dict[str, int]:
    """
    Extract PI assignment from model using the S__pi* variables.
    Returns mapping like {"pi2":0/1, "pi3":0/1, ...}
    """
    mset = set(model)
    pis = sorted(k for k in name2var if k.startswith("S__pi"))
    ce: Dict[str, int] = {}
    for sk in pis:
        # sk looks like "S__pi2"
        pin = sk[len("S__"):]  # -> "pi2"
        ce[pin] = 1 if name2var[sk] in mset else 0
    return ce


def bits_to_hex16(vbits: List[int]) -> str:
    val = 0
    for i, b in enumerate(vbits):
        val |= (int(b) & 1) << i
    return f"{val:04x}"


def max_var_in_cnf(clauses: List[List[int]]) -> int:
    m = 0
    for c in clauses:
        for l in c:
            m = max(m, abs(l))
    return m


def build_tts(name2var: Dict[str, int], patch_luts: List[str]) -> Dict[str, List[int]]:
    """
    tt_vars[lut] = [var_id for row 0..15]
    """
    out: Dict[str, List[int]] = {}
    for lut in patch_luts:
        rows = []
        for r in range(16):
            key = f"TT__{lut}__{r}"
            if key not in name2var:
                raise KeyError(f"Missing TT var in name2var: {key}")
            rows.append(int(name2var[key]))
        out[lut] = rows
    return out


def build_tt_var_set(name2var: Dict[str, int]) -> Set[int]:
    return {int(v) for k, v in name2var.items() if k.startswith("TT__")}


def map_lit(l: int, k: int, base_max: int, tt_set: Set[int]) -> int:
    """
    Variable remapping for pattern replica k:
      - TT vars stay identical (shared)
      - all other vars shift by k*base_max
    """
    v = abs(l)
    nv = v if v in tt_set else v + k * base_max
    return nv if l > 0 else -nv


def replicate_cnf_for_patterns(
    base_cnf: List[List[int]],
    patterns: List[Dict[str, int]],
    base_max: int,
    tt_set: Set[int],
) -> List[List[int]]:
    """
    Returns CNF that is the conjunction of replicas of base_cnf, one per pattern.
    """
    cnfW: List[List[int]] = []
    for k in range(len(patterns)):
        for c in base_cnf:
            cnfW.append([map_lit(l, k, base_max, tt_set) for l in c])
    return cnfW


def solve_candidate(
    solver_name: str,
    base_cnf: List[List[int]],
    name2var: Dict[str, int],
    diff_or_var: int,
    patterns: List[Dict[str, int]],
    base_max: int,
    tt_set: Set[int],
    tt_all_vars: List[int],
    verbose: bool = False,
) -> Optional[Dict[int, int]]:
    """
    SAT-A:
      Find TT assignment v such that for all patterns mu in patterns:
        diff(mu) == 0   (i.e., -diff_or_var_k)
        and PIs fixed to mu for both S__pi and T__pi in replica k
    Returns mapping {tt_var_id: 0/1} if SAT, else None.
    """
    if not patterns:
        raise ValueError("patterns must be non-empty")

    cnfW = replicate_cnf_for_patterns(base_cnf, patterns, base_max, tt_set)

    # Build assumptions enforcing diff=0 and PI bindings for each replica k
    ass: List[int] = []
    # Determine PI keys (e.g., "pi2", "pi3", ...)
    pi_keys = sorted(k[len("S__"):] for k in name2var.keys() if k.startswith("S__pi"))

    for k, mu in enumerate(patterns):
        # diff_k = 0
        diff_k = diff_or_var + k * base_max  # diff var is NOT a TT var, so shifted
        ass.append(-diff_k)

        for pi in pi_keys:
            if pi not in mu:
                raise KeyError(f"Pattern missing PI '{pi}': {mu}")

            b = int(mu[pi]) & 1

            s_pi = int(name2var[f"S__{pi}"])
            t_pi = int(name2var[f"T__{pi}"])

            # shift them (not TT vars)
            s_pi_k = s_pi + k * base_max
            t_pi_k = t_pi + k * base_max

            ass.append(lit(s_pi_k, b))
            ass.append(lit(t_pi_k, b))

    ok, model = solve_with_assumptions(solver_name, cnfW, ass)
    if not ok:
        if verbose:
            print("[SAT-A] UNSAT for |W| =", len(patterns))
        return None

    mset = set(model)
    v_cand: Dict[int, int] = {}
    for tv in tt_all_vars:
        v_cand[tv] = 1 if tv in mset else 0

    if verbose:
        print("[SAT-A] SAT. Extracted TT bits =", len(v_cand))

    return v_cand


def find_counterexample(
    solver_name: str,
    base_cnf: List[List[int]],
    name2var: Dict[str, int],
    diff_or_var: int,
    v_cand: Dict[int, int],
    verbose: bool = False,
) -> Optional[Dict[str, int]]:
    """
    SAT-B:
      Fix TT vars to v_cand, then ask for existence of an input x such that diff=1.
      Solve with assumptions: [diff] + TT_fixes.
    Returns a counterexample pattern mapping {"pi2":0/1,...} if SAT, else None.
    """
    ass: List[int] = [diff_or_var]
    for tv, b in v_cand.items():
        ass.append(lit(tv, b))

    ok, model = solve_with_assumptions(solver_name, base_cnf, ass)
    if not ok:
        if verbose:
            print("[SAT-B] UNSAT (no counterexample) -> SOLUTION")
        return None

    ce = extract_ce_pi_assignment(name2var, model)
    if verbose:
        print("[SAT-B] SAT (found CE):", ce)
    return ce


def sanity_one_pattern_sat(
    solver_name: str,
    base_cnf: List[List[int]],
    name2var: Dict[str, int],
    diff_or_var: int,
    pattern: Dict[str, int],
) -> None:
    """
    Killer sanity check:
      For one concrete PI pattern, enforcing diff=0 should be SAT with free TT bits.
      If UNSAT, your CNF / PI wiring / miter is inconsistent.
    """
    ass: List[int] = [-diff_or_var]
    for pi, b in pattern.items():
        ass.append(lit(int(name2var[f"S__{pi}"]), int(b)))
        ass.append(lit(int(name2var[f"T__{pi}"]), int(b)))

    ok, _ = solve_with_assumptions(solver_name, base_cnf, ass)
    if not ok:
        raise SystemExit(
            "[SANITY FAIL] Even for one fixed PI pattern, diff=0 is UNSAT with free TT bits.\n"
            "=> CNF / PI binding / miter inconsistency (NOT a CEGAR issue)."
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cnfjson", required=True, help="spec_target.cnf.json from step4")
    ap.add_argument("--out", required=True, help="output json with full TT assignment")
    ap.add_argument("--max-iters", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--init", choices=["zeros", "random"], default="random")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    J = json.loads(Path(args.cnfjson).read_text())
    base_cnf: List[List[int]] = J["clauses_dimacs"]
    name2var: Dict[str, int] = J["name2var"]
    diff_or_var: int = int(J["diff_or_var"])
    solver_name: str = J.get("solver", "glucose4")

    patch_luts: List[str] = list(J.get("patch_luts") or [])

    # Determine base_max (var id range) robustly
    base_max = int(J.get("vars") or max_var_in_cnf(base_cnf))

    # TT vars
    tt_set = build_tt_var_set(name2var)
    tt_vars_by_lut = build_tts(name2var, patch_luts)

    tt_all_vars: List[int] = []
    for lut in patch_luts:
        tt_all_vars.extend(tt_vars_by_lut[lut])

    # PI list
    pi_keys = sorted(k[len("S__"):] for k in name2var.keys() if k.startswith("S__pi"))
    if not pi_keys:
        raise SystemExit("No S__pi* keys found in name2var")

    rnd = random.Random(args.seed)

    def make_init_pattern() -> Dict[str, int]:
        if args.init == "zeros":
            return {pi: 0 for pi in pi_keys}
        return {pi: rnd.randint(0, 1) for pi in pi_keys}

    # CEGAR patterns
    patterns: List[Dict[str, int]] = [make_init_pattern()]

    # Sanity: diff=0 must be SAT for one pattern with free TT bits
    sanity_one_pattern_sat(solver_name, base_cnf, name2var, diff_or_var, patterns[0])

    v_cand: Optional[Dict[int, int]] = None
    for it in range(1, args.max_iters + 1):
        if args.verbose:
            print(f"\n[ITER {it}] |W|={len(patterns)}")

        v_cand = solve_candidate(
            solver_name=solver_name,
            base_cnf=base_cnf,
            name2var=name2var,
            diff_or_var=diff_or_var,
            patterns=patterns,
            base_max=base_max,
            tt_set=tt_set,
            tt_all_vars=tt_all_vars,
            verbose=args.verbose,
        )
        if v_cand is None:
            raise SystemExit(
                "[RESULT] UNSAT in SAT-A.\n"
                "=> For this rewiring/window, no global TT assignment can satisfy accumulated patterns.\n"
                "   Typical causes: window too small, cutpoints wrong, or rewiring infeasible."
            )

        ce = find_counterexample(
            solver_name=solver_name,
            base_cnf=base_cnf,
            name2var=name2var,
            diff_or_var=diff_or_var,
            v_cand=v_cand,
            verbose=args.verbose,
        )
        if ce is None:
            # Found solution
            break

        # Append CE if new
        if ce not in patterns:
            patterns.append(ce)
        else:
            # If the exact same CE repeats, something is fishy; stop early with info.
            raise SystemExit(
                "[RESULT] Repeated identical counterexample.\n"
                "=> This usually indicates a modelling issue (e.g., CE extraction mismatch, PI naming mismatch,\n"
                "   or TT vars not actually influencing diff)."
            )

    if v_cand is None:
        raise SystemExit("No candidate found (unexpected).")

    # Write full TT assignment per LUT (bits + hex)
    out_luts = []
    for lut in patch_luts:
        bits = [v_cand[tt_vars_by_lut[lut][r]] for r in range(16)]
        out_luts.append({
            "lut": lut,
            "bits_lsb_first": bits,
            "func_hex": bits_to_hex16(bits),
        })

    out = {
        "solver": solver_name,
        "base_max": base_max,
        "iters": len(patterns) - 1,  # number of added CEs
        "patterns": patterns,
        "patch_luts": patch_luts,
        "tt": out_luts,
    }

    Path(args.out).write_text(json.dumps(out, indent=2))
    print("[OK] Wrote", args.out)


if __name__ == "__main__":
    main()
